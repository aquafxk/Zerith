# Correções v3.0.49 — Recompensas por voz

- Adicionado listener `on_voice_state_update` para registrar entradas, saídas e alterações de mute/deaf.
- Adicionada tarefa `@tasks.loop(minutes=5)` iniciada em `cog_load` e cancelada em `cog_unload`.
- Recompensas por ciclo: 10–20 XP e 15–30 Souls por membro elegível.
- Exige pelo menos dois humanos no mesmo canal; bots não contam.
- Ignora canal AFK, bots, auto-mute, auto-deaf, server mute, server deaf e membros suprimidos em Stage.
- Reutiliza `level_roles` e `apply_level_roles` ao subir de nível; falhas individuais não interrompem a varredura.
- Corrigida a ausência de `xp_needed()` no `core.py`, que já era importada pelos Cogs de eventos e economia. A progressão adotada é `100 XP × nível atual`.
- As recompensas usam uma atualização SQL única por membro para creditar XP/Souls e persistir nível.

## Validação

Compilação sintática dos módulos alterados e inspeção estática concluídas. Não houve teste integrado com Gateway Discord ou SQLite de produção.
