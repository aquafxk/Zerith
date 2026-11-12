"""Lembretes de bump manual; não executa comandos em nome dos usuários."""
from __future__ import annotations

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import get_db, get_config, set_config, economy_log, update_user, emb

log = logging.getLogger("hellsing.bump")
DEFAULT_INTERVAL_MINUTES = 120


class BumpReminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def cog_unload(self) -> None:
        if self.reminder_loop.is_running():
            self.reminder_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.reminder_loop.is_running():
            self.reminder_loop.start()

    @tasks.loop(minutes=1)
    async def reminder_loop(self) -> None:
        try:
            await self._reminder_tick()
        except Exception:
            log.exception("Falha no ciclo de lembretes de bump.")

    async def _reminder_tick(self) -> None:
        now = int(time.time())
        pending = await (await get_db().execute(
            "SELECT guild_id, bump_channel, bump_interval FROM config "
            "WHERE bump_enabled=1 AND bump_next_at > 0 AND bump_next_at <= ?",
            (now,),
        )).fetchall()
        for row in pending:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None:
                continue
            channel = guild.get_channel(int(row["bump_channel"])) if row["bump_channel"] else None
            if not isinstance(channel, discord.TextChannel):
                log.warning("Canal de lembrete de bump não existe em %s; lembrete desativado.", guild.id)
                await set_config(guild.id, bump_enabled=0, bump_next_at=0)
                continue

            interval = max(DEFAULT_INTERVAL_MINUTES, int(row["bump_interval"] or DEFAULT_INTERVAL_MINUTES))
            try:
                reminder = discord.Embed(
                    title="🩸 HORA DO BUMP",
                    description=(
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "O intervalo de divulgação terminou. A Organização precisa de você.\n\n"
                        "**Ação necessária**\n"
                        "Faça o bump manualmente no serviço de divulgação e, quando concluir, "
                        "use `/bump_confirmar` para iniciar a próxima contagem.\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    ),
                    color=0x89282B,
                )
                reminder.set_footer(text="RANDOM • HELLSING  ·  lembrete de bump")
                await channel.send(embed=reminder)
            except discord.HTTPException as exc:
                log.warning("Falha ao enviar lembrete de bump em %s: HTTP %s", guild.id, exc.status)
            await set_config(guild.id, bump_next_at=now + interval * 60)

    @reminder_loop.before_loop
    async def before_reminder(self) -> None:
        await self.bot.wait_until_ready()


    @app_commands.command(name="bump_lembrete", description="Configura lembretes para fazer bump manualmente.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(canal="Canal que receberá o lembrete", intervalo_minutos="Intervalo entre lembretes (120 a 1440 minutos)")
    async def bump_lembrete(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        intervalo_minutos: app_commands.Range[int, 120, 1440] = DEFAULT_INTERVAL_MINUTES,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Você precisa de Gerenciar Servidor.", ephemeral=True)
        interval = int(intervalo_minutos)
        await set_config(
            interaction.guild_id,
            bump_channel=canal.id,
            bump_enabled=1,
            bump_interval=interval,
            bump_next_at=int(time.time()) + interval * 60,
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🩸 LEMBRETES DE BUMP ATIVADOS",
                description=(
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"**Canal:** {canal.mention}\n"
                    f"**Intervalo:** `{interval}` minutos\n"
                    "**Próxima etapa:** faça o bump manualmente e use `/bump_confirmar`.\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=0x89282B,
                timestamp=discord.utils.utcnow(),
            ).set_footer(text="RANDOM • HELLSING  •  Divulgação manual"),
            ephemeral=True,
        )

    @app_commands.command(name="bump_confirmar", description="Registra que você concluiu um bump manual.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def bump_confirmar(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Só no servidor.", ephemeral=True)
        config = await get_config(interaction.guild_id)
        if not config.get("bump_enabled"):
            return await interaction.response.send_message("⚪ Os lembretes não estão configurados. Use `/bump_lembrete`.", ephemeral=True)
        interval = max(DEFAULT_INTERVAL_MINUTES, int(config.get("bump_interval") or DEFAULT_INTERVAL_MINUTES))
        await set_config(interaction.guild_id, bump_next_at=int(time.time()) + interval * 60)
        reward = 50
        try:
            from core import get_user
            await get_user(interaction.guild_id, interaction.user.id)
            await get_db().execute(
                "UPDATE users SET souls=souls+? WHERE guild_id=? AND user_id=?",
                (reward, interaction.guild_id, interaction.user.id),
            )
            await get_db().commit()
        except Exception:
            reward = 0
        # contador de bumps na config panel_messages json is messy — feature_settings
        try:
            from core import get_feature, set_feature
            data = await get_feature(interaction.guild_id, "bump_stats", {"count": 0})
            count = int(data.get("count") or 0) + 1
            await set_feature(interaction.guild_id, "bump_stats", count=count)
        except Exception:
            count = "?"
        msg = (
            f"✅ Bump confirmado por {interaction.user.mention}.\n"
            f"Próximo aviso em **{interval}** min · total de confirmações: **{count}**"
        )
        if reward:
            msg += f"\n+`{reward}` Souls de agradecimento da Organização."
        await interaction.response.send_message(msg)
        try:
            await economy_log(
                interaction.guild,
                title="📣 Bump confirmado",
                description=f"{interaction.user.mention} · +{reward} Souls · total `{count}`",
                user=interaction.user,
            )
        except Exception:
            pass

    @app_commands.command(name="bump_desativar", description="Desativa os lembretes de bump.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def bump_desativar(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Você precisa de Gerenciar Servidor.", ephemeral=True)
        await set_config(interaction.guild_id, bump_enabled=0, bump_next_at=0)
        await interaction.response.send_message("✅ Lembretes de bump desativados.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BumpReminder(bot))
