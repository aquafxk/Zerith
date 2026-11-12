# v3.1.8 — Anti-abuso econômico + log Discord

## Camadas
1. **Memória (AbuseGuard)** — janela deslizante contra rajada de cliques:
   - roll: max 4 em 45s (env `ABUSE_ROLL_LIMIT` / `ABUSE_ROLL_WINDOW`)
   - aposta: max 6 em 20s (env `ABUSE_BET_LIMIT` / `ABUSE_BET_WINDOW`)
2. **SQLite (já existia)** — rolls/hora, rolls/dia, cooldown de aposta, UPDATE atômico
3. **Discord API** — `economy_log()` → `send_log()` → `channel.send(embed)` no canal de `/config logs`
   - marco de rolls (10/20/limite diário)
   - apostas/resultados com |líquido| ou aposta >= `ABUSE_BIG_BET` (default 25000)

## Config
Canal de logs: o mesmo de moderação (`log_channel`).
Envs opcionais: ABUSE_ROLL_WINDOW, ABUSE_ROLL_LIMIT, ABUSE_BET_WINDOW, ABUSE_BET_LIMIT, ABUSE_BIG_BET.
