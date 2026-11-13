# PostgreSQL e persistência

## Situação atual (v3.1.16)

O bot usa **SQLite** (`DB_PATH`, padrão `hellsing.db`) via `aiosqlite`. Todo o schema (users, economia, tickets, etc.) foi escrito para SQLite (`PRAGMA`, `INSERT OR IGNORE`, `AUTOINCREMENT`).

A variável `DATABASE_URL` pode ser preenchida no painel (vários hosts injetam isso automaticamente), mas **esta versão ainda grava em SQLite**. Migrar o schema inteiro para PostgreSQL sem quebrar economia, gacha e tickets exige um passo dedicado.

## O que fazer no host agora

1. Defina `DB_PATH` em um **volume persistente** (não só o disco efêmero do container).
2. Faça backup periódico do arquivo `.db` (o bot já tem comandos/rotinas de backup em alguns cogs).
3. Não apague o `.db` ao atualizar o código.

## Próximo passo (PostgreSQL de verdade)

Quando for migrar:

1. Instalar `asyncpg` no ambiente.
2. Converter DDL (`SERIAL`/`BIGSERIAL`, `ON CONFLICT DO NOTHING`).
3. Trocar placeholders `?` por `$1, $2…`.
4. Remover `PRAGMA` e adaptar `transaction()`.

Até lá, **SQLite em volume persistente** é o caminho estável.
