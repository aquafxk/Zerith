# Correções v3.0.35

- Downloader: `/baixar status`, ajuda e menu agora listam explicitamente YouTube e Shorts.
- Downloader: erro de verificação anti-bot do YouTube recebe explicação específica; não é mascarado como falha genérica.
- Montagem por IA: sanitização de nomes remove prefixos internos `cogs.setup` mesmo quando vêm delimitados ou repetidos.

## Limitação conhecida

O YouTube pode exigir verificação anti-bot para IPs de hospedagem. O código não tenta contornar essa verificação nem pede senha/cookies pessoais. A disponibilidade depende da plataforma e da rede do host.
