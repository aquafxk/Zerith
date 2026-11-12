# RANDOM • HELLSING v3.1.5 — correções de downloader e UX

## Pinterest
- Diagnóstico específico para bloqueio de sessão, autenticação, rate limit e pins sem mídia acessível.
- Verificação do caminho de cookies para o gallery-dl e aviso no log se o arquivo configurado não existir.
- `/baixar status` agora informa a presença de `YTDLP_COOKIES_PINTEREST`.
- Mensagens finais incluem Pinterest no fallback de publicação sem mídia.
- Variável opcional: `YTDLP_COOKIES_PINTEREST=/home/container/pinterest-cookies.txt` (formato Netscape).

## Boas-vindas
- Substituídos os comandos separados por `/boasvindas configurar`, `/boasvindas cargo`, `/boasvindas ver` e `/boasvindas testar`.
- `configurar` altera somente os campos informados; opções omitidas preservam os valores existentes.
- `/config boasvindas` removido para eliminar configuração duplicada.
- Menus atualizados para refletir os comandos reais.

## Compatibilidade e limitações
- Banco de dados e nomes das chaves de configuração foram preservados.
- Pinterest depende do suporte atual dos extratores e das permissões de acesso à publicação; cookies não contornam bloqueios nem tornam pins privados acessíveis.
- Não foi possível testar downloads reais sem uma sessão Pinterest e links de teste autorizados.
