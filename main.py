"""
RANDOM • HELLSING — Bot Supremo v3.1.16
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

BOT_VERSION = "3.1.16"
