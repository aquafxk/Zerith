# v3.0.48 — Transcrição HTML e memória contextual do Alucard

## `cogs/tickets.py`
- Transcrição HTML com CSS embutido em tema escuro inspirado no Discord.
- Cabeçalho com nome do ticket, autor, abertura/encerramento em UTC e horário local, staff responsável, quantidade de mensagens e anexos.
- Mensagens em ordem cronológica com avatar, nome/tag, horário, conteúdo escapado e anexos HTTPS como links/miniaturas clicáveis.
- Limite de 5.000 mensagens e limite preventivo de tamanho; indica quando o histórico foi truncado.
- CSP restritiva, sem JavaScript, escape HTML e validação de esquema HTTPS para URLs externas.
- Envia o anexo ao `ticket_log` antes de fechar/remover o canal. Fallback TXT em falha de geração; falha de envio mantém o ticket aberto.

## `cogs/ia.py` e `cogs/events.py`
- Memória RAM com `deque(maxlen=6)` por canal, sem compartilhamento de contexto entre canais.
- Histórico `system/user/assistant` enviado no payload de chat completion; Gemini recebe o histórico convertido para `contents`.
- Expiração por inatividade de 300 segundos, limpeza oportunista, lock por canal e limite de 1.200 caracteres por entrada do usuário.
- Só grava a troca depois de uma resposta válida; erros ativam cooldown de 30 segundos e não contaminam a memória.
- Mensagens de bots continuam filtradas para evitar loops. Reinício do bot limpa a memória RAM.

## Validação
- `py_compile` nos três cogs alterados e `compileall` do projeto.
- Integridade do arquivo ZIP verificada.
- Não foi possível realizar teste integrado contra Discord/Lavalink/provedores de IA sem credenciais e serviços ativos.
