"""Rastreia atividade de canais e envia mensagens espontaneas no canal mais ativo."""
from __future__ import annotations

import logging
import os
import re
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import emb, get_db

log = logging.getLogger("hellsing.activity")

# Janela de atividade (dias) e intervalo padrao entre mensagens espontaneas (horas).
def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """Le inteiro do ambiente; valores invalidos caem no default (ex.: texto de ajuda no .env)."""
    raw = (os.getenv(name) or str(default)).strip()
    # Aceita so digitos; se veio "padrao 7" ou comentario, tenta extrair o primeiro numero.
    if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
        value = int(raw)
    else:
        m = re.search(r"-?\d+", raw)
        if not m:
            log.warning("Env %s=%r invalido; usando default %s", name, raw, default)
            return max(minimum, default)
        value = int(m.group(0))
        log.warning("Env %s=%r parcial; interpretado como %s", name, raw, value)
    return max(minimum, value)


ACTIVITY_WINDOW_DAYS = _env_int("ACTIVITY_WINDOW_DAYS", 7)
DEFAULT_INTERVAL_HOURS = _env_int("ACTIVITY_INTERVAL_HOURS", 6)
MIN_MESSAGES_TO_POST = _env_int("ACTIVITY_MIN_MESSAGES", 5)

# Mensagens curtas em PT-BR. Sem mencoes, sem spam.
SPONTANEOUS_MESSAGES = [
    "O silencio no servidor ficou estranho... alguem ai?",
    "Passando no canal mais movimentado so pra lembrar que a Organizacao esta de olho.",
    "Se o chat esfriou, e hora de reaquecer. Conta o que esta rolando.",
    "Zerith aqui. Este canal lidera a atividade da semana. Continuem assim.",
    "Dica da Mansao: interagir aqui rende mais vida no servidor do que sumir por dias.",
    "Alguem ai precisa de /ajuda, /roll ou so de conversa? Estou por perto.",
    "Atualizacao da Organizacao: este e o canal com mais movimento nos ultimos dias.",
    "Se voce leu isso, manda um oi. Estatistica gosta de movimento.",
]


class ActivityTracker(commands.Cog):
    """Conta mensagens por canal/dia e posta periodicamente no canal mais ativo."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def cog_unload(self) -> None:
        if self.activity_loop.is_running():
            self.activity_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.activity_loop.is_running():
            self.activity_loop.start()
            log.info(
                "Activity loop ativo | janela=%sd | intervalo padrao=%sh",
                ACTIVITY_WINDOW_DAYS,
                DEFAULT_INTERVAL_HOURS,
            )

    async def cog_load(self) -> None:
        db = get_db()
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS channel_activity (
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                day        TEXT    NOT NULL,
                msg_count  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, channel_id, day)
            );
            CREATE INDEX IF NOT EXISTS idx_channel_activity_guild_day
                ON channel_activity(guild_id, day);

            CREATE TABLE IF NOT EXISTS activity_settings (
                guild_id       INTEGER PRIMARY KEY,
                enabled        INTEGER NOT NULL DEFAULT 1,
                interval_hours INTEGER NOT NULL DEFAULT 6,
                last_sent_at   INTEGER NOT NULL DEFAULT 0,
                last_channel_id INTEGER
            );
            """
        )
        await db.commit()

    @staticmethod
    def _day_key(ts: Optional[float] = None) -> str:
        dt = datetime.fromtimestamp(ts or time.time(), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")

    @staticmethod
    def _cutoff_day(days: int = ACTIVITY_WINDOW_DAYS) -> str:
        dt = datetime.now(timezone.utc) - timedelta(days=days)
        return dt.strftime("%Y-%m-%d")

    async def _ensure_settings(self, guild_id: int) -> dict:
        db = get_db()
        row = await (
            await db.execute(
                "SELECT enabled, interval_hours, last_sent_at, last_channel_id "
                "FROM activity_settings WHERE guild_id=?",
                (guild_id,),
            )
        ).fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO activity_settings(guild_id, enabled, interval_hours, last_sent_at) "
                "VALUES(?,?,?,0)",
                (guild_id, 1, DEFAULT_INTERVAL_HOURS),
            )
            await db.commit()
            return {
                "enabled": 1,
                "interval_hours": DEFAULT_INTERVAL_HOURS,
                "last_sent_at": 0,
                "last_channel_id": None,
            }
        return dict(row)

    async def get_most_active_channel(
        self, guild: discord.Guild
    ) -> tuple[Optional[discord.TextChannel], int]:
        """Retorna (canal, total_msgs) com mais mensagens nos ultimos N dias."""
        cutoff = self._cutoff_day()
        db = get_db()
        rows = await (
            await db.execute(
                "SELECT channel_id, SUM(msg_count) AS total "
                "FROM channel_activity "
                "WHERE guild_id=? AND day >= ? "
                "GROUP BY channel_id "
                "ORDER BY total DESC "
                "LIMIT 15",
                (guild.id, cutoff),
            )
        ).fetchall()
        for row in rows:
            channel = guild.get_channel(int(row["channel_id"]))
            if channel is None:
                try:
                    channel = await guild.fetch_channel(int(row["channel_id"]))
                except (discord.NotFound, discord.HTTPException):
                    continue
            if not isinstance(channel, discord.TextChannel):
                continue
            me = guild.me or guild.get_member(self.bot.user.id) if self.bot.user else None
            if me is None:
                continue
            perms = channel.permissions_for(me)
            if not (perms.view_channel and perms.send_messages):
                continue
            return channel, int(row["total"] or 0)
        return None, 0

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        # Nao conta comandos de prefixo nem slash (interacoes nao passam aqui como Message de comando slash).
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return
        day = self._day_key(
            message.created_at.replace(tzinfo=timezone.utc).timestamp()
            if message.created_at.tzinfo is None
            else message.created_at.timestamp()
        )
        db = get_db()
        # UPSERT leve; WAL + busy_timeout no core cuidam de contencao.
        await db.execute(
            "INSERT INTO channel_activity(guild_id, channel_id, day, msg_count) "
            "VALUES(?,?,?,1) "
            "ON CONFLICT(guild_id, channel_id, day) DO UPDATE SET "
            "msg_count = msg_count + 1",
            (message.guild.id, message.channel.id, day),
        )
        await db.commit()

    @tasks.loop(hours=1)
    async def activity_loop(self) -> None:
        try:
            await self._tick()
        except Exception:
            log.exception("Falha no ciclo de atividade espontanea")

    @activity_loop.before_loop
    async def before_activity_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _tick(self) -> None:
        now = int(time.time())
        # Limpeza ocasional de dias antigos (mantem ~14 dias).
        if now % 3600 < 60:
            old = self._cutoff_day(ACTIVITY_WINDOW_DAYS + 7)
            try:
                db = get_db()
                await db.execute("DELETE FROM channel_activity WHERE day < ?", (old,))
                await db.commit()
            except Exception:
                log.exception("Falha ao limpar channel_activity antigo")

        for guild in list(self.bot.guilds):
            try:
                settings = await self._ensure_settings(guild.id)
                if not int(settings.get("enabled") or 0):
                    continue
                interval_h = max(1, int(settings.get("interval_hours") or DEFAULT_INTERVAL_HOURS))
                last = int(settings.get("last_sent_at") or 0)
                if now - last < interval_h * 3600:
                    continue
                channel, total = await self.get_most_active_channel(guild)
                if channel is None or total < MIN_MESSAGES_TO_POST:
                    continue
                text = random.choice(SPONTANEOUS_MESSAGES)
                try:
                    await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
                except discord.Forbidden:
                    log.warning(
                        "Sem permissao para enviar em guild=%s channel=%s",
                        guild.id,
                        channel.id,
                    )
                    continue
                except discord.HTTPException as exc:
                    log.warning(
                        "HTTP %s ao enviar espontanea guild=%s channel=%s",
                        exc.status,
                        guild.id,
                        channel.id,
                    )
                    continue
                db = get_db()
                await db.execute(
                    "UPDATE activity_settings SET last_sent_at=?, last_channel_id=? WHERE guild_id=?",
                    (now, channel.id, guild.id),
                )
                await db.commit()
                log.info(
                    "Mensagem espontanea em guild=%s channel=%s total7d=%s",
                    guild.id,
                    channel.id,
                    total,
                )
            except Exception:
                log.exception("Falha ao processar guild=%s no activity_loop", guild.id)

    # -------------------- comandos admin --------------------

    activity = app_commands.Group(
        name="atividade",
        description="Mensagens espontaneas no canal mais ativo",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @activity.command(name="status", description="Mostra canal mais ativo e configuracao.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        settings = await self._ensure_settings(interaction.guild_id)
        channel, total = await self.get_most_active_channel(interaction.guild)
        last = int(settings.get("last_sent_at") or 0)
        last_txt = (
            discord.utils.format_dt(datetime.fromtimestamp(last, tz=timezone.utc), style="R")
            if last
            else "nunca"
        )
        canal_txt = f"{channel.mention} ({total} msgs / {ACTIVITY_WINDOW_DAYS}d)" if channel else "nenhum"
        e = emb(
            "Atividade do servidor",
            f"**Ativo:** {'sim' if settings.get('enabled') else 'nao'}\n"
            f"**Intervalo:** {settings.get('interval_hours')}h\n"
            f"**Ultimo envio:** {last_txt}\n"
            f"**Canal mais ativo:** {canal_txt}\n"
            f"**Minimo de msgs para postar:** {MIN_MESSAGES_TO_POST}",
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @activity.command(name="intervalo", description="Define o intervalo em horas entre mensagens espontaneas.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def intervalo(
        self,
        interaction: discord.Interaction,
        horas: app_commands.Range[int, 1, 168],
    ) -> None:
        await self._ensure_settings(interaction.guild_id)
        db = get_db()
        await db.execute(
            "UPDATE activity_settings SET interval_hours=? WHERE guild_id=?",
            (int(horas), interaction.guild_id),
        )
        await db.commit()
        await interaction.response.send_message(
            f"Intervalo definido para **{horas}h**.", ephemeral=True
        )

    @activity.command(name="ligar", description="Liga as mensagens espontaneas neste servidor.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ligar(self, interaction: discord.Interaction) -> None:
        await self._ensure_settings(interaction.guild_id)
        db = get_db()
        await db.execute(
            "UPDATE activity_settings SET enabled=1 WHERE guild_id=?",
            (interaction.guild_id,),
        )
        await db.commit()
        await interaction.response.send_message("Mensagens espontaneas **ligadas**.", ephemeral=True)

    @activity.command(name="desligar", description="Desliga as mensagens espontaneas neste servidor.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def desligar(self, interaction: discord.Interaction) -> None:
        await self._ensure_settings(interaction.guild_id)
        db = get_db()
        await db.execute(
            "UPDATE activity_settings SET enabled=0 WHERE guild_id=?",
            (interaction.guild_id,),
        )
        await db.commit()
        await interaction.response.send_message("Mensagens espontaneas **desligadas**.", ephemeral=True)

    @activity.command(name="agora", description="Forca um envio agora no canal mais ativo (teste).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def agora(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        channel, total = await self.get_most_active_channel(interaction.guild)
        if channel is None:
            return await interaction.followup.send(
                "Nenhum canal elegivel com atividade recente.", ephemeral=True
            )
        if total < MIN_MESSAGES_TO_POST:
            return await interaction.followup.send(
                f"Atividade insuficiente ({total} < {MIN_MESSAGES_TO_POST}).",
                ephemeral=True,
            )
        text = random.choice(SPONTANEOUS_MESSAGES)
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"Falha ao enviar: HTTP {exc.status}", ephemeral=True)
        db = get_db()
        await db.execute(
            "UPDATE activity_settings SET last_sent_at=?, last_channel_id=? WHERE guild_id=?",
            (int(time.time()), channel.id, interaction.guild_id),
        )
        await db.commit()
        await interaction.followup.send(
            f"Enviado em {channel.mention} (total {ACTIVITY_WINDOW_DAYS}d: {total}).",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ActivityTracker(bot))
