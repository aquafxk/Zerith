from __future__ import annotations

import logging
from pathlib import Path
from discord.ext import commands

log = logging.getLogger("hellsing.cog_loader")


def discover_extensions(package: str = "cogs") -> list[str]:
    """Descobre extensões Python recursivamente dentro de um pacote."""
    base = Path(*package.split(".")).resolve()
    if not base.is_dir():
        raise FileNotFoundError(f"Diretório de extensões não encontrado: {base}")
    found: list[str] = []
    for path in sorted(base.rglob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        relative = path.relative_to(base.parent)
        found.append(".".join(relative.with_suffix("").parts))
    return found


async def load_all_cogs(bot: commands.Bot, package: str = "cogs") -> dict[str, list[str]]:
    """Carrega extensões individualmente; uma falha não interrompe as demais."""
    result = {"loaded": [], "failed": [], "skipped": []}
    try:
        extensions = discover_extensions(package)
    except Exception:
        log.exception("Não foi possível descobrir extensões em %s", package)
        result["failed"].append(package)
        return result

    for extension in extensions:
        try:
            if extension in bot.extensions:
                result["skipped"].append(extension)
                continue
            await bot.load_extension(extension)
            result["loaded"].append(extension)
            log.info("Extensão carregada: %s", extension)
        except commands.ExtensionAlreadyLoaded:
            result["skipped"].append(extension)
        except commands.ExtensionError:
            result["failed"].append(extension)
            log.exception("Falha ao carregar extensão %s", extension)
        except Exception:
            result["failed"].append(extension)
            log.exception("Erro inesperado ao carregar %s", extension)
    log.info("Cogs: %d carregados, %d falhas, %d ignorados", len(result["loaded"]), len(result["failed"]), len(result["skipped"]))
    return result
