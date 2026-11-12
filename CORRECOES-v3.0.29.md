# Correções — RANDOM • HELLSING v3.0.29

## Cloudflare Workers AI

- A geração de texto não consulta mais `/ai/models/search` antes de cada inferência. O bot chama diretamente `/ai/run/{modelo}` com o token Bearer configurado.
- O comando de teste de provedores testa o modelo Cloudflare configurado diretamente; uma falha no catálogo não impede o teste de inferência.
- A consulta de catálogo permanece disponível para o recurso de listagem de modelos, separada da geração.
- O modelo padrão foi atualizado para `@cf/zai-org/glm-4.7-flash`, recomendado pela Cloudflare como substituto moderno. O modelo antigo `@cf/meta/llama-3.1-8b-instruct` foi descontinuado em 30/05/2026.
- Se `CLOUDFLARE_MODEL` estiver definido com um dos IDs antigos conhecidos como descontinuados, o código passa a usar o padrão atual. Modelos personalizados não listados nessa relação continuam sendo respeitados.

## Segurança e configuração

- Nenhum token, Account ID ou outra credencial foi adicionado ao pacote.
- A variável `CLOUDFLARE_API_TOKEN` continua sendo enviada como `Authorization: Bearer ...` pelo próprio código; não inclua o prefixo `Bearer ` no valor da variável.
- `CLOUDFLARE_ACCOUNT_ID` e `CLOUDFLARE_API_TOKEN` continuam obrigatórios.

## Validação

- Compilação sintática (`py_compile`) de todos os arquivos Python do pacote.
- Verificação de que `call_cloudflare()` não depende de `_cloudflare_models()`.
- Verificação de integridade CRC do ZIP gerado.
- Não foi realizado teste de inferência real: isso exige credenciais ativas no ambiente da hospedagem. Se `/ai/run` também responder HTTP 403, o bloqueio restante será de autorização/conta/token no endpoint de execução, não mais da listagem de modelos.
