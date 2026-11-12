# v3.1.2 — correções da auditoria

1. `transaction()`: COMMIT/ROLLBACK explícitos (não usa `in_transaction` com isolation_level=None).
2. `tasks.loop`: start em `on_ready` (curiosidades, app_servidor, social, bump, giveaways).
3. `/automod` e `/boasvindas`: `@app_commands.checks.has_permissions(manage_guild=True)` nos subcomandos.
4. `RoleMenuView`: precedência do `if/else` no embed corrigida.
5. `/nuke`: confirmação enviada no canal clonado (não no followup do canal apagado).
6. `ZoneInfo` com fallback UTC-3 em curiosidades.
7. `parse_duration`: `"s": 1` (não mais 604800).
