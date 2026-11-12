# Correções v3.0.33

- `/montar_servidor`: remove prefixos internos `cogs.setup_`/`cogs_setup_` que eventualmente venham no nome gerado pela IA; normaliza underscores e hífens para espaços.
- Logs de inicialização: registra a contagem de servidores no cache e o nome/ID de cada servidor, permitindo identificar qual entrada explica uma contagem inesperada.

Observação: o log informa os servidores efetivamente presentes no cache do Discord no momento do evento `on_ready`; não inventa nem corrige a associação do bot.
