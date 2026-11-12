# Ajustes do downloader — v3.0.27

## Novidades
- TikTok: `/baixar tiktok` agora oferece Automático, Somente fotos/slideshow e Somente vídeos. `yt-dlp` continua tratando vídeo; `gallery-dl` busca fotos de posts/slideshows.
- X/Twitter: `/baixar twitter` agora oferece Automático, Somente fotos/GIFs e Somente vídeos. `gallery-dl` trata imagens/GIFs e `yt-dlp` trata vídeos.
- Instagram mantém os três modos anteriores.
- Adicionada a variável opcional `YTDLP_COOKIES_TWITTER`, caminho para arquivo Netscape privado.
- O diagnóstico `/baixar status` informa a presença do arquivo de cookies do X/Twitter e os três comandos multimídia.
- Mantidos allowlist de domínios, limite de quatro itens por publicação, limite de tamanho por arquivo e cooldown.

## Configuração
Não há chave de API nova. `gallery-dl` já está listado em `requirements.txt`. Se X/Twitter exigir sessão, configure `YTDLP_COOKIES_TWITTER` com o caminho para um `cookies.txt` próprio e privado. Para TikTok, o caminho opcional é `YTDLP_COOKIES_TIKTOK`.

## Limitações
A disponibilidade depende do tipo de post, região, sessão e versão dos extratores. Não há garantia de que toda publicação ou carrossel possa ser extraído. O bot não acessa conteúdo privado sem autorização nem contorna bloqueios da plataforma.

## Validação
A validação desta entrega cobre compilação Python, allowlist, configuração dos extratores e simulações com arquivos de mídia. Não foi possível fazer download real contra TikTok/X nem testar uma sessão real do Discord neste ambiente.
