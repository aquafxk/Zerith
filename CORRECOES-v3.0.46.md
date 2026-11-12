# v3.0.46 — SQLite assíncrono (aiosqlite)

## core.py
- `sqlite3` síncrono → `aiosqlite`
- `init_db()`: abre conexão, `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, schema + migrations
- `close_db()`: `PRAGMA wal_checkpoint(TRUNCATE)` + `close()`
- Helpers async: `get_user`, `update_user`, `get_config`, `set_config`
- `row_factory = aiosqlite.Row`

## main.py
- `setup_hook`: `await init_db()` antes de carregar cogs
- `close()`: `await close_db()` antes de `super().close()`

## Cogs
- Todas as leituras/escritas no banco usam `await`
- Menu: textos custom via `build_menu_view()` async (View `__init__` permanece síncrono)

## requirements
- `aiosqlite>=0.20.0`
