# Correções — RANDOM • HELLSING v3.0.30

## Testes de modelos (zero bala)

- Adicionado filtro `_filter_chat_compatible_models` que remove automaticamente:
  - Groq: whisper*, canopylabs/*, prompt-guard, orpheus, llama-3.3-70b-versatile
  - Gemini: gemini-2.5-*, TTS, imagen, veo
  - NVIDIA: synthetic-video, yi-large, embed/rerank, vision-only
  - OpenRouter / OpenAI: áudio, TTS, embedding, moderation
- A varredura `/ia_modelos` deixa de poluir o relatório com 404 de modelos mortos.

## Prioridade de provedores

- OpenRouter passou a ser o primeiro na ordem automática.
- OpenAI foi removido da ordem automática (só entra se pedido explicitamente).
- Fallback continua funcionando para os demais.

## Defaults

- `GROQ_MODEL` padrão alterado de `llama-3.3-70b-versatile` (404 frequente) para `llama-3.1-8b-instant`.

## Validação

- Compilação sintática OK.
- Filtros aplicados em todos os catálogos (OpenAI-compatible, OpenRouter free, Gemini, NVIDIA).

## Comandos de ação (v3.0.30)

Novo cog `cogs/acoes.py` com GIFs via waifu.pics (SFW, sem chave):

| Slash | Descrição |
|-------|-----------|
| `/abracar` | Abraça alguém |
| `/beijar` | Beija alguém |
| `/cafune` | Faz cafuné |
| `/tapa` | Dá um tapa |
| `/socar` | Dá um soco |
| `/acariciar` | Se aconchega |
| `/morder` | Morde |
| `/lambida` | Dá lambida |
| `/dancar` | Dança |
| `/acenar` | Acena |
| `/piscar` | Pisca |
| `/carinho` | Segura a mão |

Também aliases de prefixo: `;abracar`, `;beijar`, `;cafune`, `;tapa`.
Cooldowndown 5s por usuário. Não funciona em bots.

## Cloudflare (v3.0.30b)

- Modelo padrão trocado de `@cf/zai-org/glm-4.7-flash` (HTTP 200 + resposta vazia) para `@cf/meta/llama-3.1-8b-instruct`.
- `glm-4.7-flash` e outros modelos problemáticos entram na lista `_BROKEN_CLOUDFLARE_MODELS` e são substituídos automaticamente.
- Parser de resposta Cloudflare ampliado: tenta `response`, `text`, `output`, `generated_text`, `content` (string ou lista).

## Timeouts e NVIDIA (v3.0.30c)

- Timeout padrão de provedor: 16s → 22s (reduz falha falsa em OpenRouter/Gemini).
- Timeout de teste de modelo: 12s → 18s.
- Filtro NVIDIA ampliado (fuyu, jamba, adept, kosmos, granite, gemma-2/3, etc.).
- NVIDIA tenta até 6 candidatos e ignora 404 para seguir ao próximo modelo.
