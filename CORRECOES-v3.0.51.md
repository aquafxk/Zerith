# Correções v3.0.51 — Anti-Mass-Mention

- Adicionada proteção no início do listener `Events.on_message`, antes de comandos, XP e IA.
- Isenta membros com `mention_everyone` ou `manage_messages` e ignora mensagens de bots, DMs e autores que não sejam `discord.Member`.
- Detecta mais de 5 usuários distintos mencionados ou uso de `@everyone`/`@here` sem permissão.
- Exclui a mensagem, tenta aplicar timeout de 1 hora e registra motivo, conteúdo truncado, destinatários, anexos e resultado das ações em `log_channel`.
- Trata separadamente falhas de exclusão, hierarquia/permissões do timeout e falhas de envio do log.
- Cache de 2 minutos evita repetir punições e inundar o canal de auditoria durante rajadas; mensagens adicionais continuam sendo removidas.

Requer permissões do bot: Manage Messages, Moderate Members e acesso de envio/embeds ao canal configurado em `log_channel`.
