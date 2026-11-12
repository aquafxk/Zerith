# Auditoria — RANDOM • HELLSING v3.0.27

## Escopo
Atualização do downloader para oferecer fotos/GIFs/slideshows também no TikTok e X/Twitter, preservando vídeos via yt-dlp.

## Alterações
1. Comandos `/baixar tiktok` e `/baixar twitter` agora têm as opções Automático, Somente fotos e Somente vídeos.
2. gallery-dl é usado para imagens: TikTok com `photos=true` e `videos=false`; X/Twitter com `videos=false`, `cards=false`, `replies=false` e `retweets=false`.
3. yt-dlp continua responsável pelos vídeos. Quando não encontra faixa de vídeo, o fluxo tenta gallery-dl antes de retornar erro.
4. Adicionada `YTDLP_COOKIES_TWITTER` para sessão própria em arquivo Netscape, opcional.
5. Atualizados `/baixar ajuda`, `/baixar status`, `.env.example` e README.
6. Mantidos os limites e validações existentes.

## Limitações
- Os extratores podem quebrar quando as plataformas mudam APIs ou regras.
- Conteúdo indisponível, privado sem autorização ou bloqueado não é acessado.
- Não foi realizado teste de download real em contas ou serviços externos.
