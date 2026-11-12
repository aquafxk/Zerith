# v3.0.31 — correção da inicialização e timeout da IA

## Inicialização (bot não subia)
- `/ajuda` estava registrado em `cogs/utilidades.py` e em `cogs/painel.py`. O discord.py recusa nome repetido
  (`CommandAlreadyRegistered`), o `painel` falhava e o `main.py` aborta a inicialização quando qualquer cog falha.
- Removido o `/ajuda` de `utilidades.py` (era antigo: chamava `HellsingMenuView` com argumento errado). O menu V2 do `painel` continua
  respondendo a `/ajuda`, `/menu`, `;ajuda`, `;menu`.
- Novo `tools/checar_comandos.py`: rode `python tools/checar_comandos.py` antes de subir; ele lista nomes de comandos slash/prefixo/grupos
  duplicados entre os cogs (sai com código 1 se achar).

## Timeout da IA
- `AI_PROVIDER_TIMEOUT_SEC` agora aceita de 8 a 300 s (antes o teto era 45 s: 120 virava 45). Padrão: 120.
- O timeout HTTP do aiohttp (antes fixo em 30 s) acompanha o do provedor; sem isso a chamada era cortada em 30 s.
- NVIDIA: cada modelo recebe 1/3 do tempo do provedor (12 a 60 s) em vez de 12 s fixos.
- Novo `AI_TOTAL_TIMEOUT_SEC` (padrão 720, máx. 840): prazo total do fallback, para não passar dos 15 min do token da interação.
