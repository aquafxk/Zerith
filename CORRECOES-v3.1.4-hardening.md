# v3.1.4 — hardening (auditoria parcial)

Aplicado o que reduz risco imediato sem reescrever a arvore de 26 cogs.

## Feito
1. `cogs/video.py`
   - `validate_url` resolve DNS e rejeita A/AAAA privados (mitigacao basica a DNS rebinding no momento da validacao).
   - Bloqueia URL com userinfo e hostname local.
   - `socket_timeout` 15s, menos fragments concorrentes, `geo_bypass=False`.
2. `cogs/boas_vindas.py`
   - Cartao Pillow em `ProcessPoolExecutor` (1 worker) em vez de so `to_thread`.

## Nao feito nesta entrega (custo alto / risco de regressao)
- Fusao de dominios economy/moderation/community
- Pipeline unico de on_message
- Redis/Celery
- Logs JSON obrigatorios
- Camada Repository completa em todos os cogs

Ordem sugerida depois: Repository so para souls (economia) -> unificar on_message -> logs JSON.
