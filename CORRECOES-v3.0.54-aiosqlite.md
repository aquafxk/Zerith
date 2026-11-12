# Correções v3.0.54 — SQLite assíncrono

## Alterações

- Camada principal de banco mantida em `aiosqlite`; conexão criada com timeout de 5 segundos.
- `row_factory` definido como `sqlite3.Row`, preservando acesso por nome (`row["campo"]`).
- PRAGMAs aplicados na inicialização: `journal_mode=WAL`, `synchronous=NORMAL` e `busy_timeout=5000`.
- Helpers `get_user`, `update_user`, `get_config` e `set_config` permanecem `async def` e usam exclusivamente operações assíncronas.
- `add_case` convertido para `async def`; chamadas no cog de moderação agora aguardam a operação.
- Corrigidas consultas dos cogs que tentavam chamar `fetchone`/`fetchall` diretamente no coroutine retornado por `db.execute`.
- Corrigidos acessos a configurações que indexavam o resultado antes de aguardar `get_config`.
- `main.py` fecha primeiro o cliente Discord e, em `finally`, executa `PRAGMA wal_checkpoint(TRUNCATE)` e fecha a conexão SQLite.
- O backup usa `sqlite3.Connection.backup()` apenas dentro de `asyncio.to_thread`, portanto não bloqueia o event loop; isso foi preservado intencionalmente.

## Compatibilidade

- Nenhuma tabela ou coluna existente foi removida.
- A dependência `aiosqlite` já consta em `requirements.txt`; não é necessário adicionar outra biblioteca.
- Banco de produção não é recriado nem substituído por esta atualização.

## Validação

- `python -m compileall -q .`: aprovado.
- Auditoria estática dos usos de `db.execute`: todos os acessos encontrados nos cogs são aguardados (`await`) ou usados como context manager assíncrono.
- Teste de integração com Discord/aiosqlite não executado neste ambiente: as dependências não estão instaladas e o ambiente não conseguiu acessá-las pela rede.
