"""
RANDOM • HELLSING — Bot Supremo v3.1.4
Estrutura em cogs + tickets, reaction roles, giveaways, cases, lockdown.
"""
import asyncio
from collections import OrderedDict
import logging
import os
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Bot-Hosting instala dependências com `pip --prefix .local`.
# O Python não adiciona esse prefixo automaticamente ao sys.path.
_local_site = (
    Path(__file__).resolve().parent
    / ".local"
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
if _local_site.is_dir():
    sys.path.insert(0, str(_local_site))

import discord
from discord.ext import commands
from dotenv import load_dotenv
from core import init_db, close_db

load_dotenv()
TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
DEV_GUILD_ID = (os.getenv("DEV_GUILD_ID") or "").strip()

# Prefixo configurável. Mantém ; como padrão e aceita ! como compatibilidade.
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", os.getenv("DEFAULT_PREFIX", ";")).strip() or ";"
_bang = os.getenv("ALLOW_BANG_PREFIX", "1").strip() in ("1", "true", "True", "yes")
COMMAND_PREFIXES = tuple(dict.fromkeys((COMMAND_PREFIX, ";") + (("!",) if _bang else ())))

BOT_VERSION = "3.1.4"



class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class VoiceOptionalFilter(logging.Filter):
    """Silencia avisos de PyNaCl/davey quando voz nao e requisito do bot."""

    _SKIP = (
        "PyNaCl is not installed, voice will NOT be supported",
        "davey is not installed, voice will NOT be supported",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(s in msg for s in self._SKIP)


def _setup_logging() -> None:
    """Console + arquivo rotativo, com nível configurável pelo .env.

    LOG_LEVEL   DEBUG | INFO | WARNING | ERROR (padrão INFO)
    LOG_DIR     pasta dos arquivos (padrão ./logs)
    LOG_FILE    1 = grava em arquivo (padrão), 0 = só console
    """
    level_name = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    use_json = (os.getenv("LOG_JSON") or "0").strip().lower() in ("1", "true", "yes", "on")
    if use_json:
        fmt = JSONFormatter()
    else:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-18s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    logging.getLogger("discord.client").addFilter(VoiceOptionalFilter())

    if (os.getenv("LOG_FILE") or "1").strip().lower() not in ("0", "false", "no", "off"):
        log_dir = Path(os.getenv("LOG_DIR") or "logs").expanduser()
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            # 5 arquivos de 5 MB: o disco da hospedagem não enche.
            file_handler = RotatingFileHandler(
                log_dir / "hellsing.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
            # Arquivo separado só com erros, para achar problemas rápido.
            error_handler = RotatingFileHandler(
                log_dir / "erros.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(fmt)
            root.addHandler(error_handler)
        except OSError as exc:
            root.warning("Não foi possível gravar logs em arquivo (%s); usando só o console.", exc)

    # Bibliotecas barulhentas ficam mais quietas, a menos que LOG_LEVEL=DEBUG.
    if level > logging.DEBUG:
        logging.getLogger("discord.http").setLevel(logging.WARNING)
        logging.getLogger("discord.gateway").setLevel(logging.WARNING)
        logging.getLogger("aiosqlite").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)


_setup_logging()
log = logging.getLogger("hellsing")
cmd_log = logging.getLogger("hellsing.comandos")


def _where(guild: "discord.Guild | None", user: "discord.abc.User | None") -> str:
    """Contexto curto e padronizado para as linhas de log."""
    g = f"{guild.name} ({guild.id})" if guild else "DM"
    u = f"{user} ({user.id})" if user else "?"
    return f"guild={g} user={u}"


intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # necessário para comandos de prefixo, anti-link e XP
intents.voice_states = True  # necessário para recompensas de XP em call


class HellsingBot(commands.Bot):
    def __init__(self):
        self._message_context_cache = OrderedDict()
        super().__init__(
            command_prefix=commands.when_mentioned_or(*COMMAND_PREFIXES),
            intents=intents,
            help_command=None,
            case_insensitive=True,
            status=discord.Status.online,
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name="use /ajuda para começar",
            ),
        )

    async def get_context(self, origin, /, *, cls=commands.Context):
        """Reutiliza o Context de uma mensagem entre o pipeline e listeners dos Cogs."""
        if isinstance(origin, discord.Message):
            key = (origin.id, cls)
            cached = self._message_context_cache.get(key)
            if cached is not None and cached.message is origin:
                self._message_context_cache.move_to_end(key)
                return cached
            context = await super().get_context(origin, cls=cls)
            self._message_context_cache[key] = context
            self._message_context_cache.move_to_end(key)
            while len(self._message_context_cache) > 512:
                self._message_context_cache.popitem(last=False)
            return context
        return await super().get_context(origin, cls=cls)

    async def setup_hook(self):
        log.info(
            "Iniciando RANDOM • HELLSING v%s | Python %s | discord.py %s | %s",
            BOT_VERSION, platform.python_version(), discord.__version__, platform.platform(terse=True),
        )
        # Exceções de tasks soltas (create_task) passam a ir para o log com traceback.
        loop = asyncio.get_running_loop()

        def _loop_exception_handler(_loop, context):
            exc = context.get("exception")
            logging.getLogger("hellsing.asyncio").error(
                "Erro não tratado em tarefa assíncrona: %s", context.get("message", ""),
                exc_info=(type(exc), exc, exc.__traceback__) if exc else None,
            )

        loop.set_exception_handler(_loop_exception_handler)
        await init_db()
        log.info("✅ Banco migrado para aiosqlite (WAL, busy_timeout=5000, Row)")
        cogs = [
            "cogs.economia",
            "cogs.dados",
            "cogs.curiosidades",
            "cogs.gacha",
            "cogs.quiz",
            "cogs.moderacao",
            "cogs.config_cog",
            "cogs.ia",
            "cogs.tickets",
            "cogs.roles",
            "cogs.giveaways",
            "cogs.events",
            "cogs.utilidades",
            "cogs.video",
            "cogs.personagens",
            "cogs.painel",
            "cogs.setup_servidor",
            "cogs.bump",
            "cogs.acoes",
            "cogs.app_servidor",
            "cogs.logs_servidor",
            "cogs.boas_vindas",
            "cogs.automod",
            "cogs.loja",
            "cogs.cassino",
            "cogs.social",
            "cogs.activity_tracker",
            "cogs.comunidade_extra",
        ]
        failed_extensions = []
        for ext in cogs:
            try:
                await self.load_extension(ext)
                log.debug("Cog carregado: %s", ext)
            except Exception as exc:
                failed_extensions.append(ext)
                log.exception("Falha ao carregar %s: %s", ext, exc)

        # Não sincroniza comandos de uma instalação parcial: isso esconderia
        # falhas e poderia deixar recursos administrativos indisponíveis.
        log.info("%d/%d cog(s) carregado(s).", len(cogs) - len(failed_extensions), len(cogs))
        if failed_extensions:
            raise RuntimeError(
                "Inicialização abortada. Falha ao carregar: "
                + ", ".join(failed_extensions)
            )

        if DEV_GUILD_ID:
            try:
                dev_guild_id = int(DEV_GUILD_ID)
                if dev_guild_id <= 0:
                    raise ValueError
            except ValueError as exc:
                raise RuntimeError("DEV_GUILD_ID precisa ser um ID numérico positivo.") from exc
            guild = discord.Object(id=dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Modo dev: %d comando(s) sincronizado(s) na guild de teste.", len(synced))
        else:
            synced = await self.tree.sync()
            log.info("%d comando(s) sincronizado(s) globalmente.", len(synced))
        log.info("⌨️ Prefixos ativos: %s", ", ".join(COMMAND_PREFIXES))

    async def close(self):
        # Primeiro consolida o WAL e fecha o SQLite; depois encerra HTTP/WebSockets.
        try:
            await close_db()
        finally:
            await super().close()


bot = HellsingBot()



@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    from discord import app_commands

    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ Você não tem permissão para usar este comando."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "❌ Eu não tenho as permissões necessárias neste canal/servidor."
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "❌ Este comando só funciona em servidores."
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Aguarde {error.retry_after:.1f}s antes de repetir este comando."
    elif isinstance(error, app_commands.CheckFailure):
        msg = "❌ Você não atende aos requisitos de permissão deste comando."
    else:
        original = getattr(error, "original", error)
        cmd_name = interaction.command.qualified_name if interaction.command else "?"
        log.error(
            "Erro no comando /%s (%s): %s: %s",
            cmd_name, _where(interaction.guild, interaction.user), type(original).__name__, original,
            exc_info=(type(original), original, original.__traceback__),
        )
        msg = "💀 As sombras falharam. Tente novamente em instantes."
    if isinstance(error, (app_commands.CheckFailure, app_commands.CommandOnCooldown)):
        cmd_name = interaction.command.qualified_name if interaction.command else "?"
        cmd_log.info("Bloqueado /%s (%s): %s", cmd_name, _where(interaction.guild, interaction.user), type(error).__name__)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        # Interação expirada ou mensagem apagada: não há onde avisar o usuário.
        log.debug("Não foi possível avisar o usuário sobre o erro em /%s.", interaction.command)


@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    cmd_log.info("/%s (%s)", command.qualified_name, _where(interaction.guild, interaction.user))


@bot.event
async def on_command_completion(ctx: commands.Context):
    cmd_log.info("%s%s (%s)", ctx.prefix or "", ctx.command.qualified_name if ctx.command else "?", _where(ctx.guild, ctx.author))


@bot.event
async def on_error(event_method: str, *args, **kwargs):
    log.exception("Erro não tratado no evento %s", event_method)


@bot.event
async def on_message(message: discord.Message):
    # Mass-mention e automod antes de process_commands (evita corrida).
    if message.guild and not message.author.bot:
        events = bot.get_cog("Events")
        if events is not None and hasattr(events, "_handle_mass_mention"):
            if await events._handle_mass_mention(message):
                return
        automod = bot.get_cog("AutoMod")
        if automod is not None and await automod.check_message(message):
            return
    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    # Silencioso: evita responder a !play / !rank de outros bots
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        message = "❌ Você não tem as permissões necessárias para esse comando."
    elif isinstance(error, commands.BotMissingPermissions):
        message = "❌ Não tenho as permissões necessárias neste servidor/canal."
    elif isinstance(error, commands.NoPrivateMessage):
        message = "❌ Esse comando só pode ser usado em um servidor."
    elif isinstance(error, commands.CommandOnCooldown):
        message = f"⏳ Aguarde {error.retry_after:.1f}s antes de tentar novamente."
    elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument, commands.TooManyArguments)):
        # Erro de digitação do usuário: responde com o uso correto, sem traceback no log.
        usage = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}".strip() if ctx.command else ""
        message = f"❌ Uso: `{usage}`" if usage else "❌ Argumentos inválidos."
    elif isinstance(error, commands.CheckFailure):
        message = "❌ Você não pode usar este comando aqui."
    else:
        original = getattr(error, "original", error)
        log.error(
            "Erro no comando %s%s (%s): %s: %s",
            ctx.prefix or "", ctx.command.qualified_name if ctx.command else "?",
            _where(ctx.guild, ctx.author), type(original).__name__, original,
            exc_info=(type(original), original, original.__traceback__),
        )
        message = "💀 O comando falhou. Confira o console do bot para ver o erro."
    try:
        await ctx.reply(message, mention_author=False, delete_after=15)
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("❌ DISCORD_TOKEN não encontrado. Defina no Ambiente do painel.")
    bot.run(TOKEN, log_handler=None)
