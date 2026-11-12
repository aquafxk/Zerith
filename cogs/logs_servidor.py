"""Registro de eventos do servidor no canal de logs (/config logs).

Mensagens apagadas/editadas, entradas e saídas, banimentos, expulsões,
apelidos, cargos, timeouts, voz, canais e cargos criados/apagados.
Ligue/desligue com /config logs_eventos. Ações feitas pelos comandos de
moderação do próprio bot já são registradas por elas e não se repetem aqui.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

import discord
from discord.ext import commands

from core import FOOTER, get_config, send_log

log = logging.getLogger("hellsing.logs")

# Cores por tipo de evento
RED, ORANGE, YELLOW, GREEN, BLUE, PURPLE, GREY = (
    0xE74C3C, 0xE67E22, 0xF1C40F, 0x2ECC71, 0x3498DB, 0x9B59B6, 0x95A5A6,
)
AUDIT_WINDOW = dt.timedelta(seconds=15)


def _clip(text: Optional[str], limit: int = 1000) -> str:
    text = (text or "").strip()
    if not text:
        return "*(sem texto)*"
    text = discord.utils.escape_mentions(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _event(title: str, color: int, *, user: Optional[discord.abc.User] = None, desc: Optional[str] = None) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=color, timestamp=discord.utils.utcnow())
    if user is not None:
        e.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)
    e.set_footer(text=FOOTER)
    return e


def _rel(when: Optional[dt.datetime]) -> str:
    return discord.utils.format_dt(when, "R") if when else "?"


class LogsServidor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------ helpers
    async def _enabled(self, guild: Optional[discord.Guild]) -> bool:
        if guild is None:
            return False
        cfg = await get_config(guild.id)
        return bool(cfg.get("log_channel")) and bool(cfg.get("log_events", 1))

    async def _is_log_channel(self, guild: discord.Guild, channel_id: int) -> bool:
        cfg = await get_config(guild.id)
        return cfg.get("log_channel") == channel_id or cfg.get("ticket_log") == channel_id

    async def _audit(
        self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int
    ) -> Optional[discord.AuditLogEntry]:
        """Busca a entrada recente do audit log para o alvo (requer Ver registro de auditoria)."""
        me = guild.me
        if me is None or not me.guild_permissions.view_audit_log:
            return None
        try:
            async for entry in guild.audit_logs(limit=6, action=action):
                target = getattr(entry.target, "id", None)
                if target == target_id and discord.utils.utcnow() - entry.created_at <= AUDIT_WINDOW:
                    return entry
        except discord.HTTPException as exc:
            log.debug("Audit log indisponível em %s (HTTP %s).", guild.id, exc.status)
        return None

    def _by_bot(self, entry: Optional[discord.AuditLogEntry]) -> bool:
        return bool(entry and self.bot.user and entry.user and entry.user.id == self.bot.user.id)

    @staticmethod
    def _actor(entry: Optional[discord.AuditLogEntry]) -> str:
        if not entry or not entry.user:
            return "desconhecido"
        reason = f"\n**Motivo:** {_clip(entry.reason, 300)}" if entry.reason else ""
        return f"{entry.user.mention} (`{entry.user.id}`){reason}"

    # ---------------------------------------------------------------- mensagens
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None or message.author.bot or not await self._enabled(message.guild):
            return
        if await self._is_log_channel(message.guild, message.channel.id):
            return
        e = _event("🗑️ Mensagem apagada", RED, user=message.author)
        e.add_field(name="Canal", value=message.channel.mention, inline=True)
        e.add_field(name="Enviada", value=_rel(message.created_at), inline=True)
        e.add_field(name="Conteúdo", value=_clip(message.content), inline=False)
        if message.attachments:
            e.add_field(
                name=f"Anexos ({len(message.attachments)})",
                value=_clip("\n".join(a.filename for a in message.attachments), 500),
                inline=False,
            )
        e.set_footer(text=f"{FOOTER} • msg {message.id}")
        await send_log(message.guild, e)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if guild is None or not await self._enabled(guild):
            return
        if await self._is_log_channel(guild, payload.channel_id):
            return
        e = _event(
            "🧹 Limpeza em massa", ORANGE,
            desc=f"**{len(payload.message_ids)}** mensagem(ns) apagada(s) em <#{payload.channel_id}>.",
        )
        await send_log(guild, e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.guild is None or after.author.bot or before.content == after.content:
            return  # embeds carregando também disparam edição; ignoramos
        if not await self._enabled(after.guild) or await self._is_log_channel(after.guild, after.channel.id):
            return
        e = _event("✏️ Mensagem editada", YELLOW, user=after.author)
        e.add_field(name="Canal", value=f"{after.channel.mention} · [ir para a mensagem]({after.jump_url})", inline=False)
        e.add_field(name="Antes", value=_clip(before.content), inline=False)
        e.add_field(name="Depois", value=_clip(after.content), inline=False)
        e.set_footer(text=f"{FOOTER} • msg {after.id}")
        await send_log(after.guild, e)

    # ------------------------------------------------------------------ membros
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not await self._enabled(member.guild):
            return
        age = discord.utils.utcnow() - member.created_at
        e = _event("📥 Entrou no servidor", GREEN, user=member, desc=member.mention)
        e.add_field(name="Conta criada", value=_rel(member.created_at), inline=True)
        e.add_field(name="Membros", value=f"`{member.guild.member_count}`", inline=True)
        if member.bot:
            e.add_field(name="Tipo", value="🤖 Bot", inline=True)
        elif age < dt.timedelta(days=7):
            e.add_field(name="⚠️ Atenção", value="Conta com menos de 7 dias.", inline=False)
        await send_log(member.guild, e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not await self._enabled(member.guild):
            return
        if await self._audit(member.guild, discord.AuditLogAction.ban, member.id):
            return  # foi banimento: on_member_ban registra
        kick = await self._audit(member.guild, discord.AuditLogAction.kick, member.id)
        if self._by_bot(kick):
            return  # /kick do bot já registrou
        roles = [r.mention for r in reversed(member.roles) if not r.is_default()]
        if kick:
            e = _event("👢 Expulso", ORANGE, user=member, desc=f"{member.mention}\n**Por:** {self._actor(kick)}")
        else:
            e = _event("📤 Saiu do servidor", GREY, user=member, desc=member.mention)
        e.add_field(name="Entrou", value=_rel(member.joined_at), inline=True)
        e.add_field(name="Membros", value=f"`{member.guild.member_count}`", inline=True)
        if roles:
            e.add_field(name=f"Cargos ({len(roles)})", value=_clip(" ".join(roles[:25]), 1000), inline=False)
        await send_log(member.guild, e)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if not await self._enabled(guild):
            return
        entry = await self._audit(guild, discord.AuditLogAction.ban, user.id)
        if self._by_bot(entry):
            return  # /ban do bot já registrou
        await send_log(guild, _event("🔨 Banido", RED, user=user, desc=f"{user.mention}\n**Por:** {self._actor(entry)}"))

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        if not await self._enabled(guild):
            return
        entry = await self._audit(guild, discord.AuditLogAction.unban, user.id)
        if self._by_bot(entry):
            return
        await send_log(guild, _event("🔓 Banimento revogado", GREEN, user=user, desc=f"{user.mention}\n**Por:** {self._actor(entry)}"))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not await self._enabled(after.guild):
            return
        guild = after.guild

        if before.nick != after.nick:
            e = _event("🏷️ Apelido alterado", BLUE, user=after, desc=after.mention)
            e.add_field(name="Antes", value=_clip(before.nick or before.name, 200), inline=True)
            e.add_field(name="Depois", value=_clip(after.nick or after.name, 200), inline=True)
            await send_log(guild, e)

        if before.timed_out_until != after.timed_out_until:
            entry = await self._audit(guild, discord.AuditLogAction.member_update, after.id)
            if not self._by_bot(entry):  # /timeout do bot já registrou
                if after.timed_out_until and after.timed_out_until > discord.utils.utcnow():
                    e = _event("🔇 Timeout aplicado", ORANGE, user=after,
                               desc=f"{after.mention} até {discord.utils.format_dt(after.timed_out_until, 'f')}\n**Por:** {self._actor(entry)}")
                else:
                    e = _event("🔊 Timeout removido", GREEN, user=after, desc=f"{after.mention}\n**Por:** {self._actor(entry)}")
                await send_log(guild, e)

        if before.roles != after.roles:
            added = [r for r in after.roles if r not in before.roles]
            removed = [r for r in before.roles if r not in after.roles]
            if added or removed:
                entry = await self._audit(guild, discord.AuditLogAction.member_role_update, after.id)
                # Cargos dados pelo próprio bot (nível, reaction roles, verificação) não
                # são registrados, para o canal não virar spam.
                if self._by_bot(entry):
                    return
                e = _event("🎭 Cargos alterados", PURPLE, user=after, desc=after.mention)
                if added:
                    e.add_field(name="➕ Adicionados", value=_clip(" ".join(r.mention for r in added), 1000), inline=False)
                if removed:
                    e.add_field(name="➖ Removidos", value=_clip(" ".join(r.mention for r in removed), 1000), inline=False)
                if entry and entry.user:
                    e.add_field(name="Por", value=self._actor(entry), inline=False)
                await send_log(guild, e)

    # --------------------------------------------------------------------- voz
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or before.channel == after.channel or not await self._enabled(member.guild):
            return
        if before.channel is None:
            e = _event("🔊 Entrou na call", GREEN, user=member, desc=f"{member.mention} → {after.channel.mention}")
        elif after.channel is None:
            e = _event("🔇 Saiu da call", GREY, user=member, desc=f"{member.mention} ← {before.channel.mention}")
        else:
            e = _event("🔀 Trocou de call", BLUE, user=member,
                       desc=f"{member.mention}: {before.channel.mention} → {after.channel.mention}")
        await send_log(member.guild, e)

    # ---------------------------------------------------------- canais e cargos
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if not await self._enabled(channel.guild):
            return
        entry = await self._audit(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        if self._by_bot(entry):
            return  # tickets/setup criados pelo bot
        await send_log(channel.guild, _event(
            "📁 Canal criado", GREEN, desc=f"{channel.mention} (`{channel.name}`)\n**Por:** {self._actor(entry)}"
        ))

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if not await self._enabled(channel.guild):
            return
        entry = await self._audit(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if self._by_bot(entry):
            return  # tickets fechados pelo bot já têm log próprio
        await send_log(channel.guild, _event(
            "🗂️ Canal apagado", RED, desc=f"`#{channel.name}` (`{channel.id}`)\n**Por:** {self._actor(entry)}"
        ))

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if not await self._enabled(role.guild):
            return
        entry = await self._audit(role.guild, discord.AuditLogAction.role_create, role.id)
        if self._by_bot(entry):
            return
        await send_log(role.guild, _event("✨ Cargo criado", GREEN, desc=f"{role.mention} (`{role.name}`)\n**Por:** {self._actor(entry)}"))

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if not await self._enabled(role.guild):
            return
        entry = await self._audit(role.guild, discord.AuditLogAction.role_delete, role.id)
        if self._by_bot(entry):
            return
        await send_log(role.guild, _event("🗑️ Cargo apagado", RED, desc=f"`@{role.name}` (`{role.id}`)\n**Por:** {self._actor(entry)}"))


async def setup(bot: commands.Bot):
    await bot.add_cog(LogsServidor(bot))
