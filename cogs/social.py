"""Utilidades sociais: lembretes, enquetes, sugestões, aniversários e AFK (v3.1.0)."""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import emb, get_db, get_feature, set_feature
from cogs.roles import role_problem

log = logging.getLogger("hellsing.social")

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo(os.getenv("BOT_TZ", "America/Sao_Paulo"))
except Exception:  # tzdata ausente (comum no Windows): usa UTC-3 fixo
    TZ = timezone(timedelta(hours=-3))

FEATURE = "social"
DEFAULTS = {
    "suggest_channel": None,
    "bday_channel": None,
    "bday_role": None,
    "bday_message": "",
    "bday_role_holders": {},
}
DEFAULT_BDAY = "🎂 Hoje é aniversário de {membro}! Parabéns{idade}!"

MAX_REMINDERS = 25
MAX_REMINDER_SECONDS = 365 * 86400
_DUR_RE = re.compile(r"(\d+)\s*(semanas?|sem|w|dias?|d|horas?|hrs?|h|minutos?|mins?|m|segundos?|segs?|s)", re.I)
_UNIT = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}

STATUS = {
    "aprovada": ("✅ Aprovada", 0x2ECC71),
    "recusada": ("❌ Recusada", 0xE74C3C),
    "em_analise": ("🔎 Em análise", 0xF1C40F),
    "implementada": ("🚀 Implementada", 0x3498DB),
}
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def parse_duration(text: str) -> Optional[int]:
    """'10m', '2h30m', '1d 12h', '3 dias', '1 semana' -> segundos."""
    total, pos = 0, 0
    text = text.strip().lower()
    for m in _DUR_RE.finditer(text):
        if text[pos:m.start()].strip(" ,e"):
            return None
        unit = m.group(2).lower()
        if unit.startswith("sem") or unit == "w":
            mult = 604800
        elif unit.startswith("seg") or unit == "s":
            mult = 1
        else:
            mult = _UNIT[unit[0]]
        total += int(m.group(1)) * mult
        pos = m.end()
    if pos == 0 or text[pos:].strip():
        return None
    return total


def _valid_date(day: int, month: int) -> bool:
    try:
        datetime(2024, month, day)  # 2024 é bissexto: aceita 29/02
        return True
    except ValueError:
        return False


class Social(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._afk: dict[tuple[int, int], tuple[str, int]] = {}
        self._afk_notice: dict[tuple[int, int], float] = {}


    @commands.Cog.listener()
    async def on_ready(self):
        if not self.reminder_loop.is_running():
            self.reminder_loop.start()
        if not self.birthday_loop.is_running():
            self.birthday_loop.start()
    async def cog_load(self):
        async with get_db().execute("SELECT guild_id, user_id, reason, since FROM afk") as c:
            for r in await c.fetchall():
                self._afk[(r["guild_id"], r["user_id"])] = (r["reason"], r["since"])

    async def cog_unload(self):
        self.reminder_loop.cancel()
        self.birthday_loop.cancel()

    # ================================================================ lembretes
    lembrete = app_commands.Group(name="lembrete", description="Lembretes pessoais")

    async def create_reminder(self, user: discord.abc.User, guild_id, channel_id, when: str, text: str, in_channel: bool) -> str:
        seconds = parse_duration(when)
        if seconds is None:
            return "❌ Tempo inválido. Exemplos: `10m`, `2h30m`, `1d`, `3 dias`, `1 semana`."
        if seconds < 60 or seconds > MAX_REMINDER_SECONDS:
            return "❌ O lembrete precisa ser entre 1 minuto e 365 dias."
        async with get_db().execute("SELECT COUNT(*) AS n FROM reminders WHERE user_id=?", (user.id,)) as c:
            if (await c.fetchone())["n"] >= MAX_REMINDERS:
                return f"❌ Você já tem {MAX_REMINDERS} lembretes pendentes. Cancele algum com `/lembrete cancelar`."
        now = int(time.time())
        due = now + seconds
        cur = await get_db().execute(
            "INSERT INTO reminders(guild_id, channel_id, user_id, text, due_at, created_at, in_channel) VALUES(?,?,?,?,?,?,?)",
            (guild_id, channel_id, user.id, text[:1000], due, now, int(in_channel)),
        )
        log.info("Lembrete #%s criado user=%s guild=%s para %s", cur.lastrowid, user.id, guild_id, due)
        onde = "neste canal" if in_channel else "na sua DM"
        return f"⏰ Lembrete `#{cur.lastrowid}` marcado para <t:{due}:F> (<t:{due}:R>), {onde}."

    @lembrete.command(name="criar", description="Cria um lembrete.")
    @app_commands.describe(quando="Ex.: 10m, 2h30m, 1d, 3 dias", texto="Do que devo lembrar", aqui="Avisar neste canal em vez da DM")
    async def lembrete_criar(self, interaction: discord.Interaction, quando: str, texto: app_commands.Range[str, 1, 1000], aqui: bool = False):
        msg = await self.create_reminder(interaction.user, interaction.guild_id, interaction.channel_id, quando, texto, aqui and interaction.guild_id is not None)
        await interaction.response.send_message(msg, ephemeral=True)

    @lembrete.command(name="listar", description="Mostra seus lembretes pendentes.")
    async def lembrete_listar(self, interaction: discord.Interaction):
        async with get_db().execute(
            "SELECT id, text, due_at FROM reminders WHERE user_id=? ORDER BY due_at LIMIT 25", (interaction.user.id,)
        ) as c:
            rows = await c.fetchall()
        text = "\n".join(f"`#{r['id']}` <t:{r['due_at']}:R> — {discord.utils.escape_markdown(r['text'][:80])}" for r in rows) or "Nenhum lembrete."
        await interaction.response.send_message(embed=emb("⏰ Seus lembretes", text), ephemeral=True)

    async def _reminder_autocomplete(self, interaction: discord.Interaction, current: str):
        async with get_db().execute(
            "SELECT id, text FROM reminders WHERE user_id=? ORDER BY due_at LIMIT 25", (interaction.user.id,)
        ) as c:
            rows = await c.fetchall()
        return [app_commands.Choice(name=f"#{r['id']} {r['text']}"[:100], value=r["id"]) for r in rows if current.lower() in r["text"].lower() or current in str(r["id"])]

    @lembrete.command(name="cancelar", description="Cancela um lembrete.")
    @app_commands.autocomplete(id=_reminder_autocomplete)
    async def lembrete_cancelar(self, interaction: discord.Interaction, id: int):
        cur = await get_db().execute("DELETE FROM reminders WHERE id=? AND user_id=?", (id, interaction.user.id))
        await interaction.response.send_message("✅ Lembrete cancelado." if cur.rowcount else "❌ Lembrete não encontrado.", ephemeral=True)

    @commands.command(name="lembrar", aliases=["lembrete", "remind"])
    async def lembrar_prefix(self, ctx: commands.Context, quando: str, *, texto: str):
        msg = await self.create_reminder(ctx.author, getattr(ctx.guild, "id", None), ctx.channel.id, quando, texto, False)
        await ctx.reply(msg, mention_author=False)

    @tasks.loop(seconds=30)
    async def reminder_loop(self):
        now = int(time.time())
        async with get_db().execute("SELECT * FROM reminders WHERE due_at<=? ORDER BY due_at LIMIT 50", (now,)) as c:
            rows = await c.fetchall()
        for r in rows:
            cur = await get_db().execute("DELETE FROM reminders WHERE id=?", (r["id"],))
            if cur.rowcount != 1:
                continue  # já entregue
            e = emb("⏰ Lembrete", r["text"])
            e.add_field(name="Criado", value=f"<t:{r['created_at']}:R>")
            delivered = False
            channel = self.bot.get_channel(r["channel_id"]) if r["channel_id"] else None
            if not r["in_channel"]:
                try:
                    user = self.bot.get_user(r["user_id"]) or await self.bot.fetch_user(r["user_id"])
                    await user.send(embed=e)
                    delivered = True
                except discord.HTTPException:
                    pass
            if not delivered and isinstance(channel, (discord.TextChannel, discord.Thread)):
                try:
                    member = channel.guild.get_member(int(r['user_id'])) if getattr(channel, 'guild', None) else None
                    if member is None and getattr(channel, 'guild', None):
                        try:
                            member = await channel.guild.fetch_member(int(r['user_id']))
                        except discord.HTTPException:
                            member = None
                    if member is not None and not channel.permissions_for(member).view_channel:
                        continue
                    await channel.send(
                        f"<@{r['user_id']}>",
                        embed=e,
                        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                    )
                    delivered = True
                except discord.HTTPException:
                    pass
            (log.info if delivered else log.warning)(
                "Lembrete #%s user=%s %s (atraso %ss)", r["id"], r["user_id"], "entregue" if delivered else "não entregue", now - r["due_at"]
            )

    @reminder_loop.before_loop
    async def _before_reminders(self):
        await self.bot.wait_until_ready()

    @reminder_loop.error
    async def _reminder_error(self, error):
        log.exception("Erro no loop de lembretes", exc_info=error)

    # ================================================================ enquete
    @app_commands.command(name="enquete", description="Cria uma enquete nativa do Discord.")
    @app_commands.guild_only()
    @app_commands.describe(
        pergunta="A pergunta",
        opcoes="Opções separadas por | (ex.: Pizza | Hambúrguer | Sushi)",
        horas="Duração em horas (1 a 768)",
        multipla="Permitir votar em mais de uma opção",
    )
    async def enquete(
        self,
        interaction: discord.Interaction,
        pergunta: app_commands.Range[str, 1, 300],
        opcoes: str,
        horas: app_commands.Range[int, 1, 768] = 24,
        multipla: bool = False,
    ):
        items = [o.strip() for o in re.split(r"[|;\n]", opcoes) if o.strip()]
        if len(items) < 2 or len(items) > 10:
            return await interaction.response.send_message("❌ Informe de 2 a 10 opções separadas por `|`.", ephemeral=True)
        if any(len(o) > 55 for o in items):
            return await interaction.response.send_message("❌ Cada opção pode ter no máximo 55 caracteres.", ephemeral=True)
        if len(set(o.lower() for o in items)) != len(items):
            return await interaction.response.send_message("❌ Há opções repetidas.", ephemeral=True)
        perms = interaction.app_permissions
        if not getattr(perms, "send_polls", True):
            return await interaction.response.send_message("❌ Não tenho permissão de **Criar enquetes** neste canal.", ephemeral=True)
        poll = discord.Poll(question=pergunta, duration=timedelta(hours=horas), multiple=multipla)
        for o in items:
            poll.add_answer(text=o)
        try:
            await interaction.response.send_message(poll=poll)
        except discord.HTTPException as exc:
            log.warning("Falha ao criar enquete guild=%s: %s", interaction.guild_id, exc)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ O Discord recusou a enquete. Verifique as permissões do canal.", ephemeral=True)
            return
        log.info("Enquete criada guild=%s canal=%s por %s (%s opções, %sh)", interaction.guild_id, interaction.channel_id, interaction.user.id, len(items), horas)

    # ================================================================ sugestões
    sugestao = app_commands.Group(name="sugestao", description="Sugestões para o servidor", guild_only=True)

    @staticmethod
    def _suggestion_embed(row, author: Optional[discord.abc.User]) -> discord.Embed:
        label, color = STATUS.get(row["status"], ("🗳️ Aberta", 0x89282B))
        e = discord.Embed(title=f"💡 Sugestão #{row['id']}", description=row["text"], color=color)
        if author:
            e.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        e.add_field(name="Status", value=label)
        if row["reason"]:
            e.add_field(name="Resposta da staff", value=row["reason"][:1000], inline=False)
        e.set_footer(text="Vote com ✅ ou ❌")
        return e

    @sugestao.command(name="enviar", description="Envia uma sugestão.")
    async def sugestao_enviar(self, interaction: discord.Interaction, texto: app_commands.Range[str, 10, 1500]):
        data = await get_feature(interaction.guild_id, FEATURE, DEFAULTS)
        channel = interaction.guild.get_channel(int(data["suggest_channel"])) if data["suggest_channel"] else None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("❌ A staff ainda não definiu o canal com `/sugestao canal`.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        cur = await get_db().execute(
            "INSERT INTO suggestions(guild_id, channel_id, user_id, text, ts) VALUES(?,?,?,?,?)",
            (interaction.guild_id, channel.id, interaction.user.id, texto, int(time.time())),
        )
        sid = cur.lastrowid
        async with get_db().execute("SELECT * FROM suggestions WHERE id=?", (sid,)) as c:
            row = await c.fetchone()
        try:
            msg = await channel.send(embed=self._suggestion_embed(row, interaction.user))
            for emoji in ("✅", "❌"):
                await msg.add_reaction(emoji)
        except discord.HTTPException as exc:
            await get_db().execute("DELETE FROM suggestions WHERE id=?", (sid,))
            log.warning("Falha ao publicar sugestão guild=%s: %s", interaction.guild_id, exc)
            return await interaction.followup.send("❌ Não consegui publicar no canal de sugestões (permissões).", ephemeral=True)
        await get_db().execute("UPDATE suggestions SET message_id=? WHERE id=?", (msg.id, sid))
        try:
            await msg.create_thread(name=f"Sugestão #{sid}", auto_archive_duration=4320)
        except discord.HTTPException:
            pass
        log.info("Sugestão #%s enviada guild=%s por %s", sid, interaction.guild_id, interaction.user.id)
        await interaction.followup.send(f"✅ Sugestão `#{sid}` enviada em {channel.mention}.", ephemeral=True)

    @sugestao.command(name="canal", description="(Staff) Define o canal de sugestões.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def sugestao_canal(self, interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
        await set_feature(interaction.guild_id, FEATURE, suggest_channel=canal.id if canal else None)
        await interaction.response.send_message(f"✅ Sugestões: {canal.mention if canal else 'desativadas'}.", ephemeral=True)

    @sugestao.command(name="responder", description="(Staff) Aprova, recusa ou atualiza uma sugestão.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def sugestao_responder(
        self,
        interaction: discord.Interaction,
        id: int,
        status: Literal["aprovada", "recusada", "em_analise", "implementada"],
        motivo: Optional[app_commands.Range[str, 1, 1000]] = None,
    ):
        cur = await get_db().execute(
            "UPDATE suggestions SET status=?, staff_id=?, reason=? WHERE id=? AND guild_id=?",
            (status, interaction.user.id, motivo, id, interaction.guild_id),
        )
        if cur.rowcount != 1:
            return await interaction.response.send_message("❌ Sugestão não encontrada.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with get_db().execute("SELECT * FROM suggestions WHERE id=?", (id,)) as c:
            row = await c.fetchone()
        author = interaction.guild.get_member(row["user_id"]) or self.bot.get_user(row["user_id"])
        channel = interaction.guild.get_channel(row["channel_id"]) if row["channel_id"] else None
        if isinstance(channel, discord.TextChannel) and row["message_id"]:
            try:
                msg = await channel.fetch_message(row["message_id"])
                await msg.edit(embed=self._suggestion_embed(row, author))
            except discord.HTTPException:
                log.debug("Mensagem da sugestão #%s não encontrada", id)
        label = STATUS[status][0]
        if author is not None:
            try:
                await author.send(embed=emb(f"💡 Sua sugestão #{id} — {label}", (motivo or "Sem comentário da staff.") + f"\n\n> {row['text'][:500]}"))
            except discord.HTTPException:
                pass
        log.info("Sugestão #%s -> %s guild=%s por %s", id, status, interaction.guild_id, interaction.user.id)
        await interaction.followup.send(f"✅ Sugestão `#{id}` marcada como {label}.", ephemeral=True)

    # ================================================================ aniversários
    aniversario = app_commands.Group(name="aniversario", description="Aniversários dos membros", guild_only=True)

    @aniversario.command(name="definir", description="Salva a data do seu aniversário.")
    @app_commands.describe(ano="Opcional: mostra a idade no anúncio")
    async def aniv_definir(
        self,
        interaction: discord.Interaction,
        dia: app_commands.Range[int, 1, 31],
        mes: app_commands.Range[int, 1, 12],
        ano: Optional[app_commands.Range[int, 1900, 2025]] = None,
    ):
        if not _valid_date(dia, mes):
            return await interaction.response.send_message("❌ Data inválida.", ephemeral=True)
        await get_db().execute(
            "INSERT INTO birthdays(guild_id, user_id, day, month, year) VALUES(?,?,?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET day=excluded.day, month=excluded.month, year=excluded.year",
            (interaction.guild_id, interaction.user.id, dia, mes, ano),
        )
        await interaction.response.send_message(f"🎂 Aniversário salvo: **{dia} de {MONTHS[mes - 1]}**.", ephemeral=True)

    @aniversario.command(name="remover", description="Apaga a data do seu aniversário.")
    async def aniv_remover(self, interaction: discord.Interaction):
        cur = await get_db().execute("DELETE FROM birthdays WHERE guild_id=? AND user_id=?", (interaction.guild_id, interaction.user.id))
        await interaction.response.send_message("✅ Removido." if cur.rowcount else "Você não tinha data salva.", ephemeral=True)

    @aniversario.command(name="ver", description="Mostra o aniversário de um membro.")
    async def aniv_ver(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        target = membro or interaction.user
        async with get_db().execute("SELECT day, month FROM birthdays WHERE guild_id=? AND user_id=?", (interaction.guild_id, target.id)) as c:
            r = await c.fetchone()
        if not r:
            return await interaction.response.send_message(f"{target.display_name} ainda não salvou o aniversário.", ephemeral=True)
        await interaction.response.send_message(f"🎂 {target.mention}: **{r['day']} de {MONTHS[r['month'] - 1]}**.", allowed_mentions=discord.AllowedMentions.none())

    @aniversario.command(name="proximos", description="Próximos aniversários do servidor.")
    async def aniv_proximos(self, interaction: discord.Interaction):
        async with get_db().execute("SELECT user_id, day, month FROM birthdays WHERE guild_id=?", (interaction.guild_id,)) as c:
            rows = await c.fetchall()
        today = datetime.now(TZ).date()

        def days_until(r):
            for year in (today.year, today.year + 1):
                day = r["day"]
                if r["month"] == 2 and day == 29:
                    try:
                        datetime(year, 2, 29)
                    except ValueError:
                        day = 28
                d = datetime(year, r["month"], day).date()
                if d >= today:
                    return (d - today).days
            return 999

        members = [(days_until(r), r) for r in rows if interaction.guild.get_member(r["user_id"])]
        members.sort(key=lambda x: x[0])
        lines = [
            f"{'🎉 **hoje**' if n == 0 else f'em {n} dia(s)'} — <@{r['user_id']}> ({r['day']:02d}/{r['month']:02d})"
            for n, r in members[:15]
        ]
        await interaction.response.send_message(
            embed=emb("🎂 Próximos aniversários", "\n".join(lines) or "Ninguém salvou ainda. Use `/aniversario definir`."),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @aniversario.command(name="config", description="(Staff) Canal, cargo do dia e mensagem dos aniversários.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(mensagem="Variáveis: {membro} {nome} {idade}", cargo="Cargo dado durante o dia do aniversário")
    async def aniv_config(
        self,
        interaction: discord.Interaction,
        canal: Optional[discord.TextChannel] = None,
        cargo: Optional[discord.Role] = None,
        mensagem: Optional[app_commands.Range[str, 1, 500]] = None,
    ):
        if cargo is not None:
            problem = role_problem(interaction.guild, cargo, interaction.user)
            if problem:
                return await interaction.response.send_message(f"❌ {problem}", ephemeral=True)
        changes = {}
        if canal is not None:
            changes["bday_channel"] = canal.id
        if cargo is not None:
            changes["bday_role"] = cargo.id
        if mensagem:
            changes["bday_message"] = mensagem
        if not changes:
            return await interaction.response.send_message(
                "⚠️ Informe canal, cargo e/ou mensagem para atualizar.",
                ephemeral=True,
            )
        await set_feature(interaction.guild_id, FEATURE, **changes)
        await interaction.response.send_message(
            f"✅ Anúncios: {canal.mention if canal else 'desativados'} · cargo do dia: {cargo.mention if cargo else '—'}.\n"
            f"Os anúncios saem a partir da meia-noite ({TZ}).",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @tasks.loop(minutes=15)
    async def birthday_loop(self):
        now = datetime.now(TZ)
        today = now.date()
        leap = True
        try:
            datetime(today.year, 2, 29)
        except ValueError:
            leap = False
        for guild in self.bot.guilds:
            data = await get_feature(guild.id, FEATURE, DEFAULTS)
            if not data["bday_channel"] and not data["bday_role"]:
                continue
            try:
                await self._birthdays_for_guild(guild, data, today, leap)
            except Exception:
                log.exception("Erro nos aniversários do servidor %s", guild.id)

    async def _birthdays_for_guild(self, guild: discord.Guild, data: dict, today, leap: bool):
        role = guild.get_role(int(data["bday_role"])) if data["bday_role"] else None
        stamp = today.isoformat()
        holders = dict(data.get("bday_role_holders") or {})
        # Remove o cargo de quem ganhou em outro dia.
        changed = False
        for uid, day in list(holders.items()):
            if day == stamp:
                continue
            member = guild.get_member(int(uid))
            if member and role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Fim do dia de aniversário")
                except discord.HTTPException:
                    pass
            holders.pop(uid)
            changed = True

        days = [(today.day, today.month)]
        if not leap and today.month == 2 and today.day == 28:
            days.append((29, 2))
        q = " OR ".join("(day=? AND month=?)" for _ in days)
        params = [v for d in days for v in d]
        async with get_db().execute(
            f"SELECT * FROM birthdays WHERE guild_id=? AND ({q}) AND last_announced<?", (guild.id, *params, today.year)
        ) as c:
            rows = await c.fetchall()
        channel = guild.get_channel(int(data["bday_channel"])) if data["bday_channel"] else None
        for r in rows:
            member = guild.get_member(r["user_id"])
            cur = await get_db().execute(
                "UPDATE birthdays SET last_announced=? WHERE guild_id=? AND user_id=? AND last_announced<?",
                (today.year, guild.id, r["user_id"], today.year),
            )
            if cur.rowcount != 1 or member is None:
                continue
            idade = f" pelos {today.year - r['year']} anos" if r["year"] else ""
            text = (data["bday_message"] or DEFAULT_BDAY).replace("{membro}", member.mention).replace("{nome}", member.display_name).replace("{idade}", idade)
            if isinstance(channel, discord.TextChannel):
                try:
                    e = emb("🎂 Feliz aniversário", text)
                    e.set_thumbnail(url=member.display_avatar.url)
                    await channel.send(member.mention, embed=e, allowed_mentions=discord.AllowedMentions(users=[member]))
                except discord.HTTPException as exc:
                    log.warning("Falha no anúncio de aniversário guild=%s: %s", guild.id, exc)
            if role and not role_problem(guild, role):
                try:
                    await member.add_roles(role, reason="Aniversário")
                    holders[str(member.id)] = stamp
                    changed = True
                except discord.HTTPException:
                    pass
            log.info("Aniversário anunciado guild=%s user=%s", guild.id, member.id)
        if changed:
            await set_feature(guild.id, FEATURE, bday_role_holders=holders)

    @birthday_loop.before_loop
    async def _before_bday(self):
        await self.bot.wait_until_ready()

    @birthday_loop.error
    async def _bday_error(self, error):
        log.exception("Erro no loop de aniversários", exc_info=error)

    # ================================================================ AFK
    async def set_afk(self, member: discord.Member, reason: str) -> None:
        reason = (reason or "AFK").strip()[:200]
        now = int(time.time())
        await get_db().execute(
            "INSERT OR REPLACE INTO afk(guild_id, user_id, reason, since) VALUES(?,?,?,?)", (member.guild.id, member.id, reason, now)
        )
        self._afk[(member.guild.id, member.id)] = (reason, now)
        me = member.guild.me
        if me and me.guild_permissions.manage_nicknames and member.top_role < me.top_role and member.id != member.guild.owner_id:
            if not member.display_name.startswith("[AFK] "):
                try:
                    await member.edit(nick=f"[AFK] {member.display_name}"[:32], reason="AFK")
                except discord.HTTPException:
                    pass

    async def clear_afk(self, member: discord.Member) -> Optional[int]:
        entry = self._afk.pop((member.guild.id, member.id), None)
        if entry is None:
            return None
        await get_db().execute("DELETE FROM afk WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
        if member.nick and member.nick.startswith("[AFK] "):
            try:
                await member.edit(nick=member.nick[6:] or None, reason="Voltou do AFK")
            except discord.HTTPException:
                pass
        return entry[1]

    @app_commands.command(name="afk", description="Avisa a quem te mencionar que você está ausente.")
    @app_commands.guild_only()
    async def afk(self, interaction: discord.Interaction, motivo: Optional[app_commands.Range[str, 1, 200]] = None):
        await self.set_afk(interaction.user, motivo or "AFK")
        await interaction.response.send_message(f"💤 {interaction.user.mention} está AFK: {motivo or 'AFK'}", allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="afk")
    @commands.guild_only()
    async def afk_prefix(self, ctx: commands.Context, *, motivo: str = "AFK"):
        await self.set_afk(ctx.author, motivo)
        await ctx.send(f"💤 {ctx.author.mention} está AFK: {discord.utils.escape_mentions(motivo[:200])}", allowed_mentions=discord.AllowedMentions.none())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return
        if not self._afk:
            return
        automod = self.bot.get_cog("AutoMod")
        if automod is not None and await automod.check_message(message):
            return
        gid = message.guild.id
        entry = self._afk.get((gid, message.author.id))
        if entry and time.time() - entry[1] > 10:
            # mensagens nos primeiros 10s (ex.: o próprio ;afk) não tiram o AFK
            since = await self.clear_afk(message.author)
            try:
                await message.channel.send(
                    f"👋 Bem-vindo(a) de volta, {message.author.mention}! Você ficou AFK desde <t:{since}:R>.",
                    delete_after=10,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass
        notices = []
        now = time.monotonic()
        for user in message.mentions[:5]:
            info = self._afk.get((gid, user.id))
            if not info or user.id == message.author.id:
                continue
            key = (message.channel.id, user.id)
            if now - self._afk_notice.get(key, 0) < 60:
                continue
            self._afk_notice[key] = now
            notices.append(f"💤 **{discord.utils.escape_markdown(user.display_name)}** está AFK <t:{info[1]}:R>: {discord.utils.escape_mentions(info[0])}")
        if len(self._afk_notice) > 2000:
            self._afk_notice = {k: v for k, v in self._afk_notice.items() if now - v < 60}
        if notices:
            try:
                await message.reply("\n".join(notices[:3]), mention_author=False, allowed_mentions=discord.AllowedMentions.none(), delete_after=30)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Social(bot))
