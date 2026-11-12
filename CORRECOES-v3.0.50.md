# Correções v3.0.50 — Transcrição HTML de tickets

- Mantida a transcrição HTML com CSS embutido no tema escuro do Discord.
- Mensagens exibem nome de perfil e tag/username separadamente.
- Conteúdo, nomes, títulos e URLs usados no HTML continuam escapados/validados.
- Anexos de imagem são miniaturas clicáveis; outros anexos são links com tamanho formatado.
- O cabeçalho inclui autor, staff, datas UTC/local, contagem de mensagens/anexos e aviso de truncamento.
- Fallback TXT agora possui tratamento próprio de exceções, limite de 5.000 mensagens e limite de tamanho abaixo do teto de upload.
- Se a coleta do fallback também falhar, o TXT de emergência ainda é enviado com o erro registrado; o ticket não é marcado como fechado nem excluído se o envio ao canal de auditoria falhar.
- O ticket só é marcado como fechado e removido depois que o envio do anexo ao `ticket_log` retorna sucesso.

Validação: compilação sintática de `cogs/tickets.py` e integridade do ZIP. Não foi realizado teste integrado com Discord real.
