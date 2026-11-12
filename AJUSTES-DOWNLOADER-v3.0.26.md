# Ajustes do downloader — v3.0.26

## Opções adicionadas ao Instagram

O comando `/baixar instagram` agora oferece três opções no próprio comando slash:

- **Automático (fotos + vídeos):** tenta baixar vídeo(s) com `yt-dlp` e fotos com `gallery-dl`. Em publicações/carrosséis mistos, combina os arquivos encontrados.
- **Somente fotos:** pula a etapa de vídeo e usa `gallery-dl` para imagens e carrosséis.
- **Somente vídeos:** usa `yt-dlp` e não tenta buscar imagens.

O usuário continua usando um único comando; basta selecionar o modo no parâmetro `modo`. Se não selecionar, o modo padrão é automático.

## Outras plataformas

- `/baixar tiktok`: vídeos com `yt-dlp`.
- `/baixar twitter`: vídeos com `yt-dlp`.
- Fotos do TikTok e do X/Twitter não são anunciadas como suportadas nesta versão.

## Dependências e hospedagem

`gallery-dl>=1.32.19,<2.0` está em `requirements.txt`. A instalação ocorre pelo comando Startup já usado na hospedagem. Não há variável nova nem chave de API obrigatória.

A execução do `gallery-dl` propaga `PYTHONPATH` do bot para também localizar pacotes instalados com `pip --prefix .local`; isso evita o caso em que o executável existe, mas o processo filho não consegue importar a biblioteca.

Se a plataforma exigir autenticação, `YTDLP_COOKIES_INSTAGRAM` pode apontar para um arquivo `cookies.txt` no formato Netscape. O mesmo arquivo é passado ao `yt-dlp` e ao `gallery-dl`. Mantenha-o privado, fora do ZIP e fora do GitHub.

## Limites e restrições

- Até 4 itens no total por publicação/carrossel, somando vídeos e imagens.
- Cada arquivo deve respeitar o limite de upload efetivo do Discord e o limite local.
- Os modos não contornam contas privadas, bloqueios geográficos, login exigido ou controles de acesso. A sessão usada precisa ter autorização para visualizar o conteúdo.
- Stories e publicações que exijam autenticação podem não estar disponíveis, mesmo com cookies.

## Validação

- Teste com stubs: allowlist de domínio, modo automático em publicação somente com fotos, modo somente fotos, modo somente vídeos e fallback para `gallery-dl`.
- A compilação sintática deve ser executada em todos os arquivos Python antes da entrega.
- Não foi possível validar downloads reais contra Instagram, TikTok ou X/Twitter nem executar uma sessão real conectada ao Discord neste ambiente.
