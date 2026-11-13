# PostgreSQL neste bot

## Resposta direta

**Nesta versao o banco de producao e SQLite (`DB_PATH` / `hellsing.db`).**

A variavel `DATABASE_URL` existe no `.env.example` apenas como reserva futura.
O codigo (`core.py`) abre **aiosqlite** com WAL. Nao ha `asyncpg` nem migracao automatica.

## Voce consegue usar PostgreSQL?

| Ambiente | Realidade |
|----------|-----------|
| Bot-Hosting (plano comum) | Quase sempre **so arquivo local**. Postgres gerenciado e raro/pago. |
| VPS propria | Sim, mas exige reescrever a camada DB (todas as queries, migrations, backups). |
| Este ZIP | **Nao** troca sozinho para Postgres. |

## Por que SQLite continua

- 1 processo do bot, carga moderada de servidor Discord
- Zero dependencia externa de DB
- Backup = copiar `hellsing.db`
- `transaction()` + WAL ja resolvem race de economia

## Se no futuro migrar

1. Adicionar `asyncpg` no requirements
2. Abstrair `get_db()` / `transaction()` para dual backend
3. Reescrever SQL especifico (PRAGMA, INSERT OR IGNORE, AUTOINCREMENT)
4. Testar economia (souls, roll, cassino) sob concorrencia

Ate la: use `DB_PATH` e faca backup periodico (`/backup_db` se disponivel).
