# RANDOM • HELLSING — v3.0.34

## Alterações
- Downloader: adicionado `/baixar youtube` para vídeos públicos e Shorts por meio do yt-dlp já utilizado pelo projeto.
- Validação: o comando aceita somente domínios oficiais do YouTube e `youtu.be`; mantém limites globais de duração, tamanho, concorrência e timeout do downloader.
- Segurança/uso: playlists não são habilitadas como download em lote; links privados, removidos ou com restrição de idade continuam sem suporte. O usuário deve ter autorização para baixar/usar o conteúdo e respeitar direitos autorais e termos da plataforma.
- `/baixar ajuda` e `/baixar status`: documentação atualizada para incluir YouTube.
- `/montar_servidor`: corrigida a expressão regular de espaços em nomes gerados, evitando que a limpeza de nomes internos deixe sequências indesejadas.
- Logs: snapshot de servidores deduplicado por ID antes de registrar a contagem e a lista no `on_ready`.

## Limitações verificadas
- Não foi possível testar downloads reais contra o YouTube nesta etapa; disponibilidade depende da versão do yt-dlp, rede e regras da plataforma.
- A montagem de servidor continua sem apagar canais/categorias existentes. A exclusão em massa não foi ativada: exige fluxo explícito de confirmação e prévia do impacto para evitar perda acidental de conteúdo.
- Avisos de PyNaCl/davey não foram silenciados com dependências não verificadas; recursos de voz permanecem indisponíveis enquanto os pacotes compatíveis não forem instalados.
- As fontes de GIFs por personagem não foram inventadas nem simuladas. GIFs específicos dependem de cadastro/URL verificada; APIs aleatórias não garantem correspondência com o personagem.

## Validação
- Verificação sintática de todos os arquivos Python incluídos no pacote.
- Testes unitários de URL: domínios YouTube permitidos e domínio externo rejeitado.
- Integridade do ZIP verificada após a geração.
