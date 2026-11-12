# Correções v3.0.32

- Corrigida a formatação de nomes em `/montar_servidor`: os valores recebidos do plano são normalizados para texto e o limite é convertido/validado antes do fatiamento, evitando `TypeError` por índice não inteiro.
- Melhorado o visual dos lembretes e da confirmação de configuração do `/bump`, mantendo o bump manual e o fluxo de confirmação existente.
- O catálogo do Gacha passou de 12 para 18 personagens, incluindo Zorin Blitz, Tubalcain Alhambra, O Capitão, Enrico Maxwell, Heinkel Wolfe e Yumie Takagi.
- `card_embed` agora aceita `images` como lista de URLs HTTPS e escolhe uma imagem aleatória por exibição; o campo `image` antigo continua compatível.

## Limitações conhecidas

- Os seis personagens novos foram cadastrados sem GIF próprio porque não havia URLs verificadas para eles no pacote-base. O sistema não associa GIF aleatório genérico a um personagem específico.
- As APIs nekos.best, nekos.life, otakugifs.xyz e kawaii.red são fontes de GIFs por categoria para comandos de ações; elas não garantem mídia do personagem específico sorteado no Gacha.
- A remoção integral do provedor OpenAI e a revisão completa do diagnóstico de modelos ainda exigem uma auditoria específica dos caminhos de IA e das escolhas de comandos; não declarar como concluídas nesta versão.
