# RANDOM • HELLSING v3.0.25 — ajuste de diagnóstico Instagram

## Alteração
- `cogs/video.py`: reconhece a mensagem `No video formats found!` e sua variante em português para Instagram.
- A resposta ao usuário agora informa que a publicação parece conter apenas fotos, explica que `/baixar instagram` baixa vídeos e esclarece que esse resultado não comprova falha nos cookies.
- A ajuda do comando foi atualizada para explicar o tratamento separado de publicações somente com fotos.

## O que não foi adicionado
- Não foi implementado download de fotos do Instagram. Esta atualização apenas identifica o caso e apresenta uma mensagem correta; o downloader continua focado em vídeos.
- Não foram adicionadas plataformas, comandos, variáveis de ambiente ou dependências novas.
- Nenhum cookie ou segredo foi incluído no pacote.

## Verificações
- Testes isolados de `explain_error`: 5 cenários aprovados (Instagram foto-only em inglês/português, post sem vídeo, formato indisponível e mensagem semelhante no TikTok).
- Compilação Python: todos os arquivos `.py` aprovados.
- Integridade CRC do ZIP verificada após empacotamento.
- Não foi realizado teste conectado ao Instagram/Discord nem download real.
