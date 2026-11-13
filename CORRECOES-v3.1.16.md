# v3.1.16

## Pinterest
- Domínios regionais (`.com.br`, `br.pinterest.com`, UK, FR, etc.)
- Resolve `pin.it` → URL final antes do download
- gallery-dl com User-Agent, retries e config de extractor reforçada
- Mensagens de erro mais claras (pin privado / cookies)

## Imagens
- Lead de estilo anti-vampiro (chibi/foto/anime) + sufixo no final do prompt
- Negative ampliado; Pollinations recebe `negative` na query
- Hugging Face imagem: tenta providers `together` / `fal-ai` / `nebius` no router

## Já na 3.1.15
- HF conversa prioritária, detecção automática, limpeza de XML/meta-prompt

## PostgreSQL
- Continua SQLite (`DB_PATH`). Use volume persistente no host.
- `DATABASE_URL` reservado — ver POSTGRES.md
