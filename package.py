from __future__ import annotations

import logging
import zipfile
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("hellsing.packager")

EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
EXCLUDED_FILES = {".env", ".env.local", ".env.production", "bot.log", "debug.log"}


def excluded(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
        name = path.name.lower()
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            return True
        if name in EXCLUDED_FILES:
            return True
        if name.startswith(".env.") and name != ".env.example":
            return True
        if path.suffix.lower() in {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3"}:
            return True
        if name.endswith((".db-wal", ".db-shm", ".db-journal")):
            return True
        return False
    except Exception:
        log.exception("Erro ao avaliar exclusão de %s", path)
        return True


def create_package() -> Path | None:
    root = Path(__file__).resolve().parent
    output = root / f"bot_deploy_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    count = 0
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in root.rglob("*"):
                try:
                    if not path.is_file() or excluded(path, root) or path.resolve() == output.resolve():
                        continue
                    archive.write(path, path.relative_to(root).as_posix())
                    count += 1
                except OSError:
                    log.exception("Não foi possível adicionar %s", path)
        with zipfile.ZipFile(output, "r") as archive:
            bad = archive.testzip()
            if bad:
                raise zipfile.BadZipFile(f"Entrada inválida: {bad}")
        log.info("Pacote criado: %s (%d arquivos)", output, count)
        return output
    except Exception:
        log.exception("Falha ao gerar ZIP")
        output.unlink(missing_ok=True)
        return None


if __name__ == "__main__":
    result = create_package()
    print(f"Pacote criado: {result}" if result else "Falha ao criar pacote")
