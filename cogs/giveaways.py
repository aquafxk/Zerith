"""Sorteios persistentes (/sorteio iniciar|encerrar|reroll|cancelar|listar).

- Estado no banco: active -> ended | cancelled (transição atômica, sem await entre ler e gravar).
- Botão de participação persistente (custom_id fixo): continua funcionando após reiniciar o bot.
- Encerramento por tarefa periódica: sorteios vencidos durante uma queda são encerrados ao voltar.
- Anúncio com retentativa: se o Discord falhar, tenta de novo nas próximas passadas (até 24 h).
- Compatível com sorteios antigos (por reação 🎉): entram como 'active' e são encerrados lendo as reações.
"""
import random
import sqlite3
import time
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import get_db, emb, log, transaction

JOIN_ID = "hellsing:giveaway:join"
MAX_ACTIVE_PER_GUILD = 10
DUP_WINDOW = 30            # segundos: bloqueia o mesmo sorteio criado duas vezes seguidas
RETRY_WINDOW = 24 * 3600   # tempo máximo de retentativa de anúncio
STATUS_PT = {"active": "ativo", "ended": "encerrado", "cancelled": "cancelado"}


# -----------------------------------------------------------------------------
# Banco e regras (funções puras: não dependem do Discord)
# -----------------------------------------------------------------------------
async def migrate() -> None:
    """Idempotente: cria a tabela de participantes e as colunas novas sem perder dados."""
    await get_db().execute(
        """CREATE TABLE IF NOT EXISTS giveaway_entries(
            message_id INTEGER NOT NULL, user_id INTEGER NOT NULL, joined_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (message_id, user_id))"""
    )
    for col, ddl in (
        ("status", "TEXT NOT NULL DEFAULT 'active'"),
        ("host_id", "INTEGER"),
        ("winner_ids", "TEXT"),
        ("ended_at", "INTEGER"),
        ("announced", "INTEGER NOT NULL DEFAULT 1"),   # 1 = nada a anunciar (linhas antigas não reanunciam)
        ("created_at", "INTEGER"),                      # NULL = sorteio antigo (por reação)
    ):
        try:
            await get_db().execute(f"ALTER TABLE giveaways ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass
    await get_db().execute("UPDATE giveaways SET status='ended' WHERE ended=1 AND status='active'")
    await get_db().commit()


def pick_winners(pool: Sequence[int], k: int, exclude: Iterable[int] = ()) -> List[int]:
    banned = set(exclude)
    candidates = [u for u in dict.fromkeys(pool) if u not in banned]
    return random.sample(candidates, k=min(k, len(candidates)))


def parse_ids(raw: Optional[str]) -> List[int]:
    return [int(x) for x in (raw or "").split(",") if x.strip().isdigit()]


async def entry_ids(message_id: int) -> List[int]:
    cursor = await get_db().execute(
        "SELECT user_id FROM giveaway_entries WHERE message_id=?", (message_id,)
    )
    rows = await cursor.fetchall()
    return [row["user_id"] for row in rows]


async def toggle_entry(message_id: int, user_id: int, now: int) -> Tuple[str, int]:
    """Entra ou sai do sorteio. Retorna ('joined'|'left'|'closed', total de participantes)."""
    # Transação: dois cliques simultâneos não podem entrar e sair ao mesmo tempo.
    async with transaction() as tx:
        row = (await (await tx.execute("SELECT status, ends_at FROM giveaways WHERE message_id=?", (message_id,))).fetchone())
        if not row or row["status"] != "active" or row["ends_at"] <= now:
            return "closed", 0
        cur = await tx.execute("DELETE FROM giveaway_entries WHERE message_id=? AND user_id=?", (message_id, user_id))
        state = "left" if cur.rowcount else "joined"
        if state == "joined":
            await tx.execute("INSERT OR IGNORE INTO giveaway_entries(message_id, user_id, joined_at) VALUES(?,?,?)", (message_id, user_id, now))
        total = (await (await tx.execute("SELECT COUNT(*) c FROM giveaway_entries WHERE message_id=?", (message_id,))).fetchone())["c"]
    return state, total


async def finalize_db(message_id: int, is_member: Callable[[int], bool], now: int) -> Optional[List[int]]:
    """Encerra de forma atômica (sem await). Só uma chamada vence; as demais recebem None.

    Retorna a lista de vencedores (pode ser vazia) ou None se o sorteio não estava ativo.
    """
    row = (await (await get_db().execute("SELECT * FROM giveaways WHERE message_id=?", (message_id,))).fetchone())
    if not row or row["status"] != "active":
        return None
    winners = pick_winners([u for u in await entry_ids(message_id) if is_member(u)], row["winners"])
    cur = await get_db().execute(
        "UPDATE giveaways SET status='ended', ended=1, ended_at=?, winner_ids=?, announced=0 "
        "WHERE message_id=? AND status='active'",
        (now, ",".join(map(str, winners)), message_id),
    )
    await get_db().commit()
    return winners if cur.rowcount == 1 else None


async def cancel_db(message_id: int, guild_id: int, now: int) -> bool:
    cur = await get_db().execute(
        "UPDATE giveaways SET status='cancelled', ended=1, ended_at=?, announced=0 "
        "WHERE message_id=? AND guild_id=? AND status='active'",
        (now, message_id, guild_id),
    )
    await get_db().commit()
    return cur.rowcount == 1


async def get_row(message_id: int, guild_id: Optional[int] = None):
    if guild_id is None:
        return (await (await get_db().execute("SELECT * FROM giveaways WHERE message_id=?", (message_id,))).fetchone())
    return (await (await get_db().execute("SELECT * FROM giveaways WHERE message_id=? AND guild_id=?", (message_id, guild_id))).fetchone())


def parse_message_id(raw: str) -> Optional[int]:
    raw = raw.strip()
    return int(raw) if raw.isdigit() else None


# -----------------------------------------------------------------------------
# Visual
# -----------------------------------------------------------------------------
def prize_embed(row, status: str, winners: Sequence[int] = ()) -> discord.Embed:
    prize, host = row["prize"], row["host_id"]
    host_line = f"\n**Organizador:** <@{host}>" if host else ""
    if status == "active":
        return emb(
            "🎉 SORTEIO DA MANSÃO",
            f"**Prêmio:** {prize}\n**Vencedores:** {row['winners']}\n**Termina:** <t:{row['ends_at']}:R>{host_line}\n\n"
            "Clique no botão para participar. Clique de novo para sair.",
        )
    if status == "cancelled":
        return emb("🚫 SORTEIO CANCELADO", f"**Prêmio:** {prize}{host_line}")
    who = ", ".join(f"<@{u}>" for u in winners) or "Sem participantes elegíveis"
    return emb("🏆 SORTEIO ENCERRADO", f"**Prêmio:** {prize}\n**Vencedor(es):** {who}{host_line}")


class JoinView(discord.ui.View):
    """Persistente: custom_id fixo; o sorteio é identificado pelo ID da mensagem do botão."""

    def __init__(self, disabled: bool = False):
        super().__init__(timeout=None)
        self.join.disabled = disabled


    @commands.Cog.listener()
    async def on_ready(self):
        if not self.tick.is_running():
            self.tick.start()
    @discord.ui.button(label="Participar 🎉", style=discord.ButtonStyle.danger, custom_id=JOIN_ID)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        state, total = await toggle_entry(interaction.message.id, interaction.user.id, int(time.time()))
        text = {
            "joined": f"✅ Você está participando! Participantes: `{total}`. Clique de novo para sair.",
            "left": f"↩️ Você saiu do sorteio. Participantes: `{total}`.",
            "closed": "⏰ Este sorteio já terminou.",
        }[state]
        await interaction.response.send_message(text, ephemeral=True)


# -----------------------------------------------------------------------------
# Cog
# -----------------------------------------------------------------------------
class Giveaways(commands.Cog):
    sorteio = app_commands.Group(
        name="sorteio",
        description="Sorteios da Mansão.",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._announcing: set = set()

    async def cog_load(self):
        await migrate()
        self.bot.add_view(JoinView())

    async def cog_unload(self):
        self.tick.cancel()

    # ---- infraestrutura ----------------------------------------------------
    async def _get_channel(self, channel_id: int):
        """Canal, ou None se sumiu/sem acesso. Erros temporários de rede propagam (haverá retentativa)."""
        channel = self.bot.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await self.bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            return None

    async def _import_legacy_reactions(self, row) -> None:
        """Sorteios antigos usavam a reação 🎉: importa quem reagiu como participante."""
        try:
            channel = await self._get_channel(row["channel_id"])
            if channel is None:
                return
            msg = await channel.fetch_message(row["message_id"])
            for reaction in msg.reactions:
                if str(reaction.emoji) == "🎉":
                    async for user in reaction.users():
                        if not user.bot:
                            await get_db().execute(
                                "INSERT OR IGNORE INTO giveaway_entries(message_id, user_id, joined_at) VALUES(?,?,?)",
                                (row["message_id"], user.id, int(time.time())),
                            )
                    await get_db().commit()
                    break
        except discord.HTTPException as exc:
            log.warning("Sorteio %s: não consegui ler reações antigas: %s", row["message_id"], exc)

    async def finish(self, message_id: int) -> bool:
        """Encerra um sorteio ativo. True se esta chamada o encerrou."""
        row = await get_row(message_id)
        if not row or row["status"] != "active":
            return False
        guild = self.bot.get_guild(row["guild_id"])
        if row["created_at"] is None and not await entry_ids(message_id):
            await self._import_legacy_reactions(row)
        is_member = (lambda uid: guild.get_member(uid) is not None) if guild else (lambda uid: False)
        return await finalize_db(message_id, is_member, int(time.time())) is not None

    async def _announce(self, message_id: int) -> None:
        if message_id in self._announcing:
            return
        self._announcing.add(message_id)
        try:
            row = await get_row(message_id)
            if not row or row["announced"] or row["status"] == "active":
                return
            try:
                channel = await self._get_channel(row["channel_id"])
            except discord.HTTPException:
                return  # temporário: tenta na próxima passada
            if channel is None:
                log.warning("Sorteio %s: canal indisponível; anúncio descartado.", message_id)
                await self._mark_announced(message_id)
                return
            try:
                msg = await channel.fetch_message(message_id)
            except (discord.NotFound, discord.Forbidden):
                msg = None
            except discord.HTTPException:
                return
            status = row["status"]
            winners = parse_ids(row["winner_ids"])
            try:
                if msg:
                    await msg.edit(embed=prize_embed(row, status, winners), view=JoinView(disabled=True))
                if status == "ended":
                    link = f"https://discord.com/channels/{row['guild_id']}/{row['channel_id']}/{message_id}"
                    if winners:
                        mentions = ", ".join(f"<@{u}>" for u in winners)
                        e = emb("🎉 Sorteio encerrado!", f"**Prêmio:** {row['prize']}\n**Vencedor(es):** {mentions}\n[Ver sorteio]({link})")
                        await channel.send(content=mentions, embed=e, allowed_mentions=discord.AllowedMentions(users=True))
                    else:
                        await channel.send(embed=emb("🎉 Sorteio encerrado", f"**{row['prize']}**\nNinguém elegível participou.\n[Ver sorteio]({link})"))
            except discord.Forbidden:
                log.warning("Sorteio %s: sem permissão para editar/anunciar no canal.", message_id)
            except discord.HTTPException as exc:
                log.warning("Sorteio %s: falha temporária ao anunciar: %s", message_id, exc)
                return
            await self._mark_announced(message_id)
        finally:
            self._announcing.discard(message_id)

    @staticmethod
    async def _mark_announced(message_id: int) -> None:
        await get_db().execute("UPDATE giveaways SET announced=1 WHERE message_id=?", (message_id,))
        await get_db().commit()

    @tasks.loop(seconds=15)
    async def tick(self):
        now = int(time.time())
        for r in (await (await get_db().execute("SELECT message_id FROM giveaways WHERE status='active' AND ends_at<=?", (now,))).fetchall()):
            try:
                if await self.finish(r["message_id"]):
                    await self._announce(r["message_id"])
            except Exception:
                log.exception("Erro ao encerrar o sorteio %s", r["message_id"])
        pend = (await (await get_db().execute(
            "SELECT message_id FROM giveaways WHERE status IN ('ended','cancelled') AND announced=0 AND ended_at>?",
            (now - RETRY_WINDOW,),
        )).fetchall())
        for r in pend:
            try:
                await self._announce(r["message_id"])
            except Exception:
                log.exception("Erro ao anunciar o sorteio %s", r["message_id"])

    @tick.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_ready()

    # ---- autocomplete ------------------------------------------------------
    async def _choices(self, interaction: discord.Interaction, current: str, status: str):
        rows = (await (await get_db().execute(
            "SELECT message_id, prize FROM giveaways WHERE guild_id=? AND status=? ORDER BY ends_at DESC LIMIT 25",
            (interaction.guild_id, status),
        )).fetchall())
        cur = current.lower()
        return [
            app_commands.Choice(name=f"{r['prize'][:70]} ({r['message_id']})", value=str(r["message_id"]))
            for r in rows
            if cur in r["prize"].lower() or cur in str(r["message_id"])
        ]

    # ---- comandos ----------------------------------------------------------
    @sorteio.command(name="iniciar", description="Inicia um sorteio com botão de participação.")
    @app_commands.describe(premio="O que será sorteado", minutos="Duração em minutos (até 7 dias)", vencedores="Número de vencedores")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def iniciar(
        self,
        interaction: discord.Interaction,
        premio: app_commands.Range[str, 1, 200],
        minutos: app_commands.Range[int, 1, 10080],
        vencedores: app_commands.Range[int, 1, 20] = 1,
    ):
        await interaction.response.defer(ephemeral=True)
        guild, channel = interaction.guild, interaction.channel
        if channel is None or not hasattr(channel, "send"):
            return await interaction.followup.send("❌ Use o comando em um canal de texto.", ephemeral=True)
        perms = channel.permissions_for(guild.me)
        if not (perms.send_messages and perms.embed_links):
            return await interaction.followup.send("❌ Preciso de **Enviar Mensagens** e **Inserir Links** neste canal.", ephemeral=True)

        now = int(time.time())
        active = (await (await get_db().execute("SELECT COUNT(*) c FROM giveaways WHERE guild_id=? AND status='active'", (guild.id,))).fetchone())["c"]
        if active >= MAX_ACTIVE_PER_GUILD:
            return await interaction.followup.send(f"❌ Limite de {MAX_ACTIVE_PER_GUILD} sorteios ativos. Encerre algum com `/sorteio encerrar`.", ephemeral=True)
        dup = (await (await get_db().execute(
            "SELECT 1 FROM giveaways WHERE guild_id=? AND channel_id=? AND host_id=? AND prize=? AND status='active' AND created_at>?",
            (guild.id, channel.id, interaction.user.id, premio, now - DUP_WINDOW),
        )).fetchone())
        if dup:
            return await interaction.followup.send("❌ Sorteio idêntico criado há instantes. Duplicata bloqueada.", ephemeral=True)

        ends = now + minutos * 60
        draft = {"prize": premio, "winners": vencedores, "ends_at": ends, "host_id": interaction.user.id}
        msg = await channel.send(embed=prize_embed(draft, "active"), view=JoinView())
        try:
            await get_db().execute(
                "INSERT INTO giveaways(message_id, channel_id, guild_id, prize, ends_at, winners, ended, status, host_id, created_at, announced) "
                "VALUES(?,?,?,?,?,?,0,'active',?,?,1)",
                (msg.id, channel.id, guild.id, premio, ends, vencedores, interaction.user.id, now),
            )
            await get_db().commit()
        except sqlite3.Error:
            await msg.delete()
            raise
        await interaction.followup.send(f"✅ Sorteio criado: {msg.jump_url}", ephemeral=True)

    @sorteio.command(name="encerrar", description="Encerra agora um sorteio ativo e sorteia os vencedores.")
    @app_commands.describe(sorteio="Sorteio ativo")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def encerrar(self, interaction: discord.Interaction, sorteio: str):
        mid = parse_message_id(sorteio)
        row = await get_row(mid, interaction.guild_id) if mid else None
        if not row:
            return await interaction.response.send_message("❌ Sorteio não encontrado neste servidor.", ephemeral=True)
        if row["status"] != "active":
            return await interaction.response.send_message(f"❌ Este sorteio já está {STATUS_PT[row['status']]}.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if await self.finish(mid):
            await self._announce(mid)
            return await interaction.followup.send("✅ Sorteio encerrado.", ephemeral=True)
        await interaction.followup.send("ℹ️ Este sorteio já tinha sido encerrado.", ephemeral=True)

    @encerrar.autocomplete("sorteio")
    async def encerrar_ac(self, interaction: discord.Interaction, current: str):
        return await self._choices(interaction, current, "active")

    @sorteio.command(name="cancelar", description="Cancela um sorteio ativo sem sortear.")
    @app_commands.describe(sorteio="Sorteio ativo")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cancelar(self, interaction: discord.Interaction, sorteio: str):
        mid = parse_message_id(sorteio)
        row = await get_row(mid, interaction.guild_id) if mid else None
        if not row:
            return await interaction.response.send_message("❌ Sorteio não encontrado neste servidor.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if not await cancel_db(mid, interaction.guild_id, int(time.time())):
            return await interaction.followup.send(f"❌ Este sorteio já está {STATUS_PT[await get_row(mid)['status']]}.", ephemeral=True)
        await self._announce(mid)
        await interaction.followup.send("✅ Sorteio cancelado.", ephemeral=True)

    @cancelar.autocomplete("sorteio")
    async def cancelar_ac(self, interaction: discord.Interaction, current: str):
        return await self._choices(interaction, current, "active")

    @sorteio.command(name="reroll", description="Sorteia novos vencedores de um sorteio encerrado.")
    @app_commands.describe(sorteio="Sorteio encerrado", quantidade="Quantos novos vencedores (padrão: o mesmo número do sorteio)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reroll(self, interaction: discord.Interaction, sorteio: str, quantidade: Optional[app_commands.Range[int, 1, 20]] = None):
        mid = parse_message_id(sorteio)
        row = await get_row(mid, interaction.guild_id) if mid else None
        if not row:
            return await interaction.response.send_message("❌ Sorteio não encontrado neste servidor.", ephemeral=True)
        if row["status"] != "ended":
            return await interaction.response.send_message("❌ Só é possível sortear de novo um sorteio **encerrado**.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        pool = [u for u in await entry_ids(mid) if guild.get_member(u)]
        new = pick_winners(pool, quantidade or row["winners"], exclude=parse_ids(row["winner_ids"]))
        if not new:
            return await interaction.followup.send("❌ Não há participantes elegíveis (todos já ganharam ou saíram do servidor).", ephemeral=True)
        previous = parse_ids(row["winner_ids"])
        all_winners = list(dict.fromkeys([*previous, *new]))
        await get_db().execute(
            "UPDATE giveaways SET winner_ids=? WHERE message_id=?",
            (",".join(map(str, all_winners)), mid),
        )
        await get_db().commit()
        try:
            channel = await self._get_channel(row["channel_id"])
            if channel is None:
                return await interaction.followup.send("❌ O canal do sorteio não existe mais.", ephemeral=True)
            mentions = ", ".join(f"<@{u}>" for u in new)
            await channel.send(
                content=mentions,
                embed=emb("🔁 Novo sorteio", f"**Prêmio:** {row['prize']}\n**Novo(s) vencedor(es):** {mentions}"),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"⚠️ Vencedores sorteados, mas o anúncio falhou: `{exc}`", ephemeral=True)
        await interaction.followup.send("✅ Novo(s) vencedor(es) anunciado(s).", ephemeral=True)

    @reroll.autocomplete("sorteio")
    async def reroll_ac(self, interaction: discord.Interaction, current: str):
        return await self._choices(interaction, current, "ended")

    @sorteio.command(name="listar", description="Lista os sorteios ativos do servidor.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def listar(self, interaction: discord.Interaction):
        rows = (await (await get_db().execute(
            "SELECT * FROM giveaways WHERE guild_id=? AND status='active' ORDER BY ends_at", (interaction.guild_id,)
        )).fetchall())
        if not rows:
            return await interaction.response.send_message("Nenhum sorteio ativo.", ephemeral=True)
        lines = [
            f"• **{r['prize'][:60]}** — termina <t:{r['ends_at']}:R> — "
            f"[abrir](https://discord.com/channels/{r['guild_id']}/{r['channel_id']}/{r['message_id']})"
            for r in rows
        ]
        await interaction.response.send_message(embed=emb("🎉 Sorteios ativos", "\n".join(lines)), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
