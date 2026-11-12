# Auditoria — RANDOM • HELLSING v3.0.28

## Escopo
Direcionar as novas opções multimídia somente ao TikTok, sem ampliar o suporte do X/Twitter.

## Alterações
- `/baixar tiktok`: Automático, Somente fotos/slideshow e Somente vídeos.
- Instagram mantém o suporte multimídia já existente na versão anterior.
- X/Twitter volta a aceitar apenas o fluxo de vídeo, sem modo de fotos/GIFs.
- Ajuda, status, README e `.env.example` atualizados.
- Nenhuma chave/API do TikTok é necessária para yt-dlp/gallery-dl.

## Limitações
- Não há garantia de extração de toda publicação; o TikTok pode alterar endpoints, exigir sessão ou limitar requisições.
- Não foi realizado download real contra o TikTok nem teste conectado ao Discord.
- GitHub hospeda o código, não fornece cota ilimitada de API nem impede bloqueios/limites da plataforma.

## Verificações
- Compilação sintática dos arquivos Python.
- Testes unitários locais de validação de URL, modos e allowlist.
- Integridade do ZIP.
