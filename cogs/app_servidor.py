"""Aplicação do servidor: checklist de setup + painel do dono."""
from __future__ import annotations

import asyncio
import gzip
import logging
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import COLOR, FOOTER, emb, get_config, is_bot_owner, owner_ids, get_db, db_file

START_TIME = time.time()
log = logging.getLogger("hellsing.backups")
BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
MAX_DISCORD_UPLOAD_FALLBACK = 8 * 1024 * 1024


def _channel_mention(guild: discord.Guild, channel_id) -> str:
    if not channel_id:
        return "❌ não configurado"
    ch = guild.get_channel(int(channel_id))
    return ch.mention if ch else f"⚠️ ID `{channel_id}` (canal sumiu)"


def _role_mention(guild: discord.Guild, role_id) -> str:
    if not role_id:
        return "❌ não configurado"
    role = guild.get_role(int(role_id))
    return role.mention if role else f"⚠️ ID `{role_id}` (cargo sumiu)"


class AppServidor(commands.Cog):
    """Central da aplicação do servidor (setup + dono)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)


    @commands.Cog.listener()
    async def on_ready(self):
        if not self.backup_diario.is_running():
            self.backup_diario.start()
    async def cog_unload(self) -> None:
        self.backup_diario.cancel()

    @staticmethod
    def _backup_sqlite_sync(destination: Path) -> Path:
        """Cria um snapshot consistente usando sqlite3.Connection.backup()."""
        source_path = Path(db_file).expanduser().resolve()
        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)

        if not source_path.is_file():
            raise FileNotFoundError(f"Banco SQLite não encontrado: {source_path}")

        # Gera primeiro em arquivo temporário; só publica o destino após validar.
        temp_path = destination.with_name(
            f".{destination.name}.{os.getpid()}.{time.time_ns()}.tmp"
        )
        source = None
        target = None
        try:
            source = sqlite3.connect(str(source_path), timeout=30.0)
            target = sqlite3.connect(str(temp_path), timeout=30.0)
            source.backup(target, pages=256, sleep=0.05)
            target.commit()
            target.close()
            target = None
            source.close()
            source = None

            check = sqlite3.connect(str(temp_path), timeout=30.0)
            try:
                result = check.execute("PRAGMA quick_check").fetchone()
                if not result or result[0] != "ok":
                    raise sqlite3.DatabaseError(
                        f"Verificação do backup falhou: {result[0] if result else 'sem resultado'}"
                    )
            finally:
                check.close()

            os.replace(temp_path, destination)
            return destination
        except Exception:
            if target is not None:
                target.close()
            if source is not None:
                source.close()
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _cleanup_backups_sync() -> int:
        """Mantém somente os cinco backups diários mais recentes por mtime."""
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backups = sorted(
            BACKUP_DIR.glob("hellsing_backup_*.bak"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old_backup in backups[5:]:
            try:
                old_backup.unlink(missing_ok=True)
            except OSError:
                log.exception("Não foi possível remover backup antigo: %s", old_backup)
        return min(len(backups), 5)

    @tasks.loop(hours=24)
    async def backup_diario(self) -> None:
        """Executa um backup ao iniciar e repete a cada 24 horas."""
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"hellsing_backup_{datetime.now(timezone.utc):%Y%m%d}.bak"
            destination = BACKUP_DIR / filename
            backup_path = await asyncio.to_thread(self._backup_sqlite_sync, destination)
            retained = await asyncio.to_thread(self._cleanup_backups_sync)
            size_mb = backup_path.stat().st_size / (1024 * 1024)
            log.info(
                "📦 Backup SQLite concluído: %s (%.2f MB); %d backup(s) mantido(s).",
                backup_path.name,
                size_mb,
                retained,
            )
        except Exception:
            log.exception("❌ Falha ao executar o backup diário do SQLite.")

    @backup_diario.before_loop
    async def before_backup_diario(self) -> None:
        await self.bot.wait_until_ready()

    async def _checklist_embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = await get_config(guild.id)
        levels = (await (await get_db().execute(
            "SELECT COUNT(*) AS c FROM users WHERE guild_id=?",
            (guild.id,),
        )).fetchone())
        user_count = int(levels["c"]) if levels else 0

        lines = [
            f"**Boas-vindas:** {_channel_mention(guild, cfg.get('welcome_channel'))}",
            f"**Logs:** {_channel_mention(guild, cfg.get('log_channel'))}",
            f"**Regras:** {_channel_mention(guild, cfg.get('rules_channel'))}",
            f"**Tickets — categoria:** {_channel_mention(guild, cfg.get('ticket_category'))}",
            f"**Tickets — log:** {_channel_mention(guild, cfg.get('ticket_log'))}",
            f"**Tickets — staff:** {_role_mention(guild, cfg.get('ticket_staff_role'))}",
            f"**Anti-spam:** {'✅ ligado' if cfg.get('antispam') else '⚪ off'}",
            f"**Anti-link:** {'✅ ligado' if cfg.get('antilink') else '⚪ off'}",
            f"**Bump:** {'✅ ativo' if cfg.get('bump_enabled') else '⚪ off'} · {_channel_mention(guild, cfg.get('bump_channel'))}",
            f"**Membros no rank/XP:** `{user_count}`",
        ]
        embed = discord.Embed(
            title="🦇 Aplicação do servidor — Hellsing",
            description=(
                "Status da **aplicação** neste servidor.\n"
                "Use os comandos abaixo para completar o que estiver ❌."
            ),
            color=COLOR,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Checklist", value="\n".join(lines), inline=False)
        embed.add_field(
            name="Comandos de setup",
            value=(
                "`/montar_servidor` — gerar canais/cargos com IA\n"
                "`/config boasvindas` · `/config logs`\n"
                "`/config ticket_categoria` · `/config ticket_staff`\n"
                "`/config cargo_nivel` · `/painel_ticket`\n"
                "`/bump_lembrete` · `/config antispam`"
            ),
            inline=False,
        )
        embed.set_footer(text=FOOTER)
        return embed

    @app_commands.command(
        name="app_servidor",
        description="Painel da aplicação do servidor: checklist de setup (tickets, níveis, logs…).",
    )
    @app_commands.guild_only()
    async def app_servidor(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        await interaction.response.send_message(
            embed=await self._checklist_embed(interaction.guild),
            ephemeral=True,
        )

    @commands.command(name="app_servidor", aliases=["appservidor", "aplicacao"])
    @commands.guild_only()
    async def app_servidor_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(embed=await self._checklist_embed(ctx.guild))

    # --- Painel do dono ---

    dono = app_commands.Group(
        name="dono",
        description="Comandos exclusivos do dono do bot (OWNER_ID).",
    )

    @dono.command(
        name="backup",
        description="Gera e envia uma cópia segura do banco SQLite (somente dono).",
    )
    async def dono_backup(self, interaction: discord.Interaction) -> None:
        if not is_bot_owner(interaction.user.id):
            return await interaction.response.send_message(
                "❌ Só o **dono do bot** pode gerar backups. Configure `OWNER_ID` no `.env`.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        raw_path: Optional[Path] = None
        gzip_path: Optional[Path] = None
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            with tempfile.NamedTemporaryFile(
                prefix=f"manual_hellsing_backup_{stamp}_",
                suffix=".bak",
                dir=BACKUP_DIR,
                delete=False,
            ) as temp_file:
                raw_path = Path(temp_file.name)
            # O destino temporário já existe vazio; removê-lo garante que o
            # backup() sempre escreva em um arquivo novo.
            raw_path.unlink(missing_ok=True)
            await asyncio.to_thread(self._backup_sqlite_sync, raw_path)

            upload_path = raw_path
            upload_limit = int(
                getattr(interaction, "filesize_limit", MAX_DISCORD_UPLOAD_FALLBACK)
                or MAX_DISCORD_UPLOAD_FALLBACK
            )
            if raw_path.stat().st_size > upload_limit:
                gzip_path = raw_path.with_suffix(raw_path.suffix + ".gz")
                def _compress() -> None:
                    with raw_path.open("rb") as source_file, gzip.open(
                        gzip_path, "wb", compresslevel=6
                    ) as compressed_file:
                        shutil.copyfileobj(source_file, compressed_file)
                await asyncio.to_thread(_compress)
                upload_path = gzip_path

            if upload_path.stat().st_size > upload_limit:
                size_mb = upload_path.stat().st_size / (1024 * 1024)
                await interaction.edit_original_response(
                    content=(
                        f"⚠️ O backup foi gerado, mas mesmo compactado ocupa **{size_mb:.2f} MB**, "
                        "acima do limite de anexo desta interação. Nenhum arquivo foi enviado."
                    )
                )
                return

            file = discord.File(upload_path, filename=upload_path.name)
            try:
                await interaction.edit_original_response(
                    content="✅ Backup do banco gerado. Guarde o arquivo em local seguro.",
                    attachments=[file],
                )
            finally:
                file.close()
            log.info(
                "Backup manual enviado ao dono %s (%s; %.2f MB).",
                interaction.user.id,
                upload_path.name,
                upload_path.stat().st_size / (1024 * 1024),
            )
        except Exception:
            log.exception("Falha no comando /dono backup.")
            message = "❌ Não foi possível gerar ou enviar o backup. Consulte os logs do bot."
            try:
                await interaction.edit_original_response(content=message, attachments=[])
            except discord.HTTPException:
                pass
        finally:
            if gzip_path is not None:
                gzip_path.unlink(missing_ok=True)
            if raw_path is not None:
                raw_path.unlink(missing_ok=True)

    @dono.command(name="status", description="Status técnico do bot (somente dono).")
    async def dono_status(self, interaction: discord.Interaction) -> None:
        if not is_bot_owner(interaction.user.id):
            return await interaction.response.send_message(
                "❌ Só o **dono do bot** pode usar isto. Configure `OWNER_ID` no `.env`.",
                ephemeral=True,
            )
        uptime = int(time.time() - START_TIME)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)
        keys = {
            "OpenRouter": bool(os.getenv("OPENROUTER_API_KEY")),
            "Gemini": bool(os.getenv("GEMINI_API_KEY")),
            "NVIDIA": bool(os.getenv("NVIDIA_API_KEY")),
            "OpenAI": bool(os.getenv("OPENAI_API_KEY")),
            "Groq": bool(os.getenv("GROQ_API_KEY")),
            "Cloudflare": bool(os.getenv("CLOUDFLARE_API_TOKEN") and os.getenv("CLOUDFLARE_ACCOUNT_ID")),
            # Mesmos nomes de variável lidos pelo core.py / cog de IA.
            "Pollinations": bool(os.getenv("POLLINATIONS_KEY")),
            "Stability": bool(os.getenv("STABLE_DIFFUSION_KEY")),
        }
        key_lines = "\n".join(
            f"{'✅' if ok else '⚪'} **{name}**" for name, ok in keys.items()
        )
        owners = ", ".join(f"`{i}`" for i in sorted(owner_ids())) or "_nenhum OWNER_ID no .env_"
        embed = emb(
            "🔑 Painel do dono",
            (
                f"**Uptime:** `{h}h {m}m {s}s`\n"
                f"**Latência:** `{round(self.bot.latency * 1000)} ms`\n"
                f"**Guilds:** `{len(self.bot.guilds)}`\n"
                f"**Owners:** {owners}\n\n"
                f"**Chaves detectadas**\n{key_lines}"
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @dono.command(name="guilds", description="Lista servidores em que o bot está (somente dono).")
    async def dono_guilds(self, interaction: discord.Interaction) -> None:
        if not is_bot_owner(interaction.user.id):
            return await interaction.response.send_message("❌ Só o dono do bot.", ephemeral=True)
        lines = []
        for g in sorted(self.bot.guilds, key=lambda x: x.member_count or 0, reverse=True)[:25]:
            lines.append(f"• **{g.name}** (`{g.id}`) — `{g.member_count}` membros")
        text = "\n".join(lines) or "Nenhum servidor."
        await interaction.response.send_message(embed=emb("🌐 Guilds", text), ephemeral=True)

    @commands.command(name="dono")
    async def dono_prefix(self, ctx: commands.Context) -> None:
        """Atalho prefixo: status do dono (usa is_owner do discord.py + OWNER_ID)."""
        if not is_bot_owner(ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.reply("❌ Só o dono do bot.", mention_author=False)
        uptime = int(time.time() - START_TIME)
        await ctx.send(
            embed=emb(
                "🔑 Painel do dono",
                f"Uptime `{uptime}s` · Guilds `{len(self.bot.guilds)}` · ping `{round(self.bot.latency*1000)}ms`\n"
                "Slash: `/dono status` · `/dono guilds`",
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AppServidor(bot))
