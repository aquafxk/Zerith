"""Extras de comunidade: status, ranking de rolls, regras, evento semanal, sugestoes staff."""
from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import (
    COLOR,
    emb,
    economy_log,
    get_config,
    get_db,
    get_feature,
    get_user,
    set_feature,
    set_config,
    update_user,
)

log = logging.getLogger("hellsing.comunidade_extra")

FEATURE_WEEKLY = "weekly_event"
WEEKLY_DEFAULTS = {"active": False, "roll_discount": 50, "bonus_souls": 100, "ends_at": 0}
FEATURE_RULES = "rules_accept"
RULES_DEFAULTS = {"role_id": None, "channel_id": None}
BUMP_REWARD = int(os.getenv("BUMP_REWARD_SOULS", "50") or "50")


class RulesAcceptView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @discord.ui.button(label="Li as regras", style=discord.ButtonStyle.success, custom_id="hellsing:rules:accept", emoji="📜")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Só funciona no servidor.", ephemeral=True)
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            return await interaction.response.send_message("Cargo de regras não existe mais.", ephemeral=True)
        if role in interaction.user.roles:
            return await interaction.response.send_message("Você já aceitou as regras.", ephemeral=True)
        try:
            await interaction.user.add_roles(role, reason="Aceite de regras")
        except discord.HTTPException:
            return await interaction.response.send_message("Não consegui atribuir o cargo (hierarquia/permissões).", ephemeral=True)
        await interaction.response.send_message(f"Bem-vindo(a). Cargo {role.mention} concedido.", ephemeral=True)


class ComunidadeExtra(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def cog_unload(self):
        if self.weekly_tick.is_running():
            self.weekly_tick.cancel()

    async def cog_load(self):
        # Re-registra views persistentes de regras
        async with get_db().execute(
            "SELECT guild_id, data FROM feature_settings WHERE feature=?",
            (FEATURE_RULES,),
        ) as cur:
            rows = await cur.fetchall()
        for row in rows:
            try:
                import json
                data = json.loads(row["data"] if isinstance(row["data"], str) else "{}")
            except Exception:
                continue
            rid = data.get("role_id")
            if rid:
                self.bot.add_view(RulesAcceptView(int(rid)))

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.weekly_tick.is_running():
            self.weekly_tick.start()

    # ---------- 1 ranking rolls semana ----------
    @app_commands.command(name="rank_rolls", description="Quem mais invocou cartas (rolls) — ranking aproximado pelo contador diário agregado.")
    @app_commands.guild_only()
    async def rank_rolls(self, interaction: discord.Interaction):
        # rolls_today zera todo dia; usamos rolls_used na janela + duels como proxy fraco.
        # Melhor: tabela roll_stats — cria se não existir.
        db = get_db()
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roll_stats ("
            "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, week INTEGER NOT NULL, "
            "rolls INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, user_id, week))"
        )
        await db.commit()
        week = int(time.time()) // (7 * 86400)
        rows = await (
            await db.execute(
                "SELECT user_id, rolls FROM roll_stats WHERE guild_id=? AND week=? ORDER BY rolls DESC LIMIT 10",
                (interaction.guild_id, week),
            )
        ).fetchall()
        if not rows:
            return await interaction.response.send_message(
                "Nenhum roll registrado nesta semana ainda. Use `/roll`.", ephemeral=True
            )
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(rows):
            pos = medals[i] if i < 3 else f"`{i+1}.`"
            lines.append(f"{pos} <@{r['user_id']}> — **{r['rolls']}** rolls")
        await interaction.response.send_message(embed=emb("🎲 Ranking de rolls — semana", "\n".join(lines)))

    # ---------- 4 status servidor ----------
    @app_commands.command(name="status_servidor", description="Painel ao vivo: membros, tickets, bump, canal ativo.")
    @app_commands.guild_only()
    async def status_servidor(self, interaction: discord.Interaction):
        guild = interaction.guild
        cfg = await get_config(guild.id)
        open_tickets = await (
            await get_db().execute(
                "SELECT COUNT(*) AS c FROM tickets WHERE guild_id=? AND open=1", (guild.id,)
            )
        ).fetchone()
        tickets_n = int(open_tickets["c"]) if open_tickets else 0
        bump_next = int(cfg.get("bump_next_at") or 0)
        bump_txt = f"<t:{bump_next}:R>" if bump_next else "—"
        # canal mais ativo via activity_tracker table
        channel_txt = "—"
        try:
            row = await (
                await get_db().execute(
                    "SELECT channel_id, SUM(msg_count) AS t FROM channel_activity "
                    "WHERE guild_id=? GROUP BY channel_id ORDER BY t DESC LIMIT 1",
                    (guild.id,),
                )
            ).fetchone()
            if row:
                ch = guild.get_channel(int(row["channel_id"]))
                channel_txt = ch.mention if ch else f"`{row['channel_id']}`"
                channel_txt += f" ({int(row['t'])} msgs)"
        except Exception:
            pass
        weekly = await get_feature(guild.id, FEATURE_WEEKLY, WEEKLY_DEFAULTS)
        ends = int(weekly.get("ends_at") or 0)
        evento = "ativo até " + (f"<t:{ends}:R>" if ends > time.time() else "inativo")
        if not weekly.get("active"):
            evento = "inativo"
        e = emb(
            f"🦇 Status — {guild.name}",
            f"**Membros:** `{guild.member_count}`\n"
            f"**Tickets abertos:** `{tickets_n}`\n"
            f"**Próximo bump:** {bump_txt}\n"
            f"**Canal mais ativo:** {channel_txt}\n"
            f"**Evento semanal:** {evento}",
        )
        e.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=e)

    # ---------- 3 backup manual ----------
    @app_commands.command(name="backup_db", description="(Dono do bot) Gera backup do SQLite agora.")
    @app_commands.guild_only()
    async def backup_db(self, interaction: discord.Interaction):
        if not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message("Só o dono do bot pode usar este comando.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        src = Path(os.getenv("DB_PATH", "hellsing.db"))
        if not src.is_file():
            # try common paths
            for candidate in (Path("hellsing.db"), Path("data/hellsing.db")):
                if candidate.is_file():
                    src = candidate
                    break
        if not src.is_file():
            return await interaction.followup.send("Arquivo do banco não encontrado.", ephemeral=True)
        out_dir = Path("backups")
        out_dir.mkdir(exist_ok=True)
        dest = out_dir / f"hellsing_manual_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.bak"
        try:
            await discord.utils.maybe_coroutine(shutil.copy2, src, dest)
            # shutil.copy2 is sync
            shutil.copy2(src, dest)
        except Exception as exc:
            log.exception("backup manual falhou")
            return await interaction.followup.send(f"Falha: `{exc}`", ephemeral=True)
        size = dest.stat().st_size / (1024 * 1024)
        await interaction.followup.send(f"Backup ok: `{dest.name}` ({size:.2f} MB).", ephemeral=True)
        try:
            await interaction.followup.send(file=discord.File(dest), ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("Arquivo grande demais para anexar; ficou só no disco do host.", ephemeral=True)

    # ---------- 5 sugestoes staff ----------
    sugestao_staff = app_commands.Group(
        name="sugestao_mod",
        description="Staff: aprovar/rejeitar sugestões",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @sugestao_staff.command(name="aprovar", description="Aprova uma sugestão pelo ID.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def sug_aprovar(self, interaction: discord.Interaction, id: int, nota: Optional[str] = None):
        await self._set_suggestion_status(interaction, id, "aprovada", nota)

    @sugestao_staff.command(name="rejeitar", description="Rejeita uma sugestão pelo ID.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def sug_rejeitar(self, interaction: discord.Interaction, id: int, nota: Optional[str] = None):
        await self._set_suggestion_status(interaction, id, "rejeitada", nota)

    async def _set_suggestion_status(self, interaction: discord.Interaction, sid: int, status: str, nota: Optional[str]):
        db = get_db()
        # ensure status column
        try:
            await db.execute("ALTER TABLE suggestions ADD COLUMN status TEXT NOT NULL DEFAULT 'aberta'")
            await db.commit()
        except Exception:
            pass
        row = await (await db.execute("SELECT * FROM suggestions WHERE id=? AND guild_id=?", (sid, interaction.guild_id))).fetchone()
        if not row:
            return await interaction.response.send_message("Sugestão não encontrada.", ephemeral=True)
        await db.execute("UPDATE suggestions SET status=? WHERE id=?", (status, sid))
        await db.commit()
        note = f"\nNota: {nota}" if nota else ""
        await interaction.response.send_message(f"Sugestão `#{sid}` marcada como **{status}**.{note}", ephemeral=True)
        if row["message_id"] and row["channel_id"]:
            ch = interaction.guild.get_channel(int(row["channel_id"]))
            if isinstance(ch, discord.TextChannel):
                try:
                    msg = await ch.fetch_message(int(row["message_id"]))
                    e = msg.embeds[0] if msg.embeds else emb(f"Sugestão #{sid}", row["text"])
                    e.color = 0x2ECC71 if status == "aprovada" else 0xE74C3C
                    e.add_field(name="Status", value=status + note, inline=False)
                    await msg.edit(embed=e)
                except discord.HTTPException:
                    pass

    # ---------- 6 evento semanal ----------
    @app_commands.command(name="evento_semanal", description="(Staff) Liga/desliga evento: roll mais barato + bônus.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def evento_semanal(
        self,
        interaction: discord.Interaction,
        ligar: bool,
        horas: app_commands.Range[int, 1, 168] = 48,
        desconto_roll: app_commands.Range[int, 0, 100] = 50,
        bonus_souls: app_commands.Range[int, 0, 5000] = 100,
    ):
        ends = int(time.time()) + int(horas) * 3600 if ligar else 0
        await set_feature(
            interaction.guild_id,
            FEATURE_WEEKLY,
            active=ligar,
            roll_discount=int(desconto_roll),
            bonus_souls=int(bonus_souls),
            ends_at=ends,
        )
        if ligar:
            msg = f"Evento **ligado** por {horas}h · desconto roll {desconto_roll}% · bônus `{bonus_souls}` Souls no `/missao`."
        else:
            msg = "Evento **desligado**."
        await interaction.response.send_message(msg, ephemeral=True)

    @tasks.loop(minutes=30)
    async def weekly_tick(self):
        now = int(time.time())
        try:
            async with get_db().execute(
                "SELECT guild_id, data FROM feature_settings WHERE feature=?",
                (FEATURE_WEEKLY,),
            ) as cur:
                rows = await cur.fetchall()
            import json
            for row in rows:
                try:
                    data = json.loads(row["data"] if isinstance(row["data"], str) else "{}")
                except Exception:
                    continue
                if data.get("active") and int(data.get("ends_at") or 0) and int(data["ends_at"]) < now:
                    await set_feature(int(row["guild_id"]), FEATURE_WEEKLY, active=False, ends_at=0)
                    log.info("Evento semanal expirou guild=%s", row["guild_id"])
        except Exception:
            log.exception("weekly_tick falhou")

    @weekly_tick.before_loop
    async def _before_weekly(self):
        await self.bot.wait_until_ready()

    # ---------- 8 regras ----------
    @app_commands.command(name="painel_regras", description="(Staff) Publica botão 'Li as regras' que dá um cargo.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def painel_regras(
        self,
        interaction: discord.Interaction,
        cargo: discord.Role,
        texto: Optional[str] = None,
    ):
        body = texto or (
            "Leia as regras do servidor. Ao clicar no botão, você confirma que leu e recebe o cargo de membro."
        )
        view = RulesAcceptView(cargo.id)
        await set_feature(interaction.guild_id, FEATURE_RULES, role_id=cargo.id, channel_id=interaction.channel_id)
        self.bot.add_view(view)
        e = emb("📜 Regras da Organização", body)
        await interaction.channel.send(embed=e, view=view)
        await interaction.response.send_message("Painel publicado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ComunidadeExtra(bot))
