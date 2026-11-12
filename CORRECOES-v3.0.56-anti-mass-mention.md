# RANDOM • HELLSING — v3.0.56 — Anti-Mass-Mention

## Alterações
- Mantida a migração aiosqlite da v3.0.55 e as correções anteriores.
- `cogs/events.py`: deduplicação explícita de menções por ID de usuário.
- Dispara quando há mais de 5 usuários distintos mencionados ou `@everyone`/`@here` sem permissão `mention_everyone`/`manage_messages`.
- Exclui a mensagem antes de executar as demais ações de moderação e preserva o conteúdo para auditoria.
- Aplica timeout de 1 hora, respeitando hierarquia e permissões do bot; registra no alerta quando a ação não pode ser aplicada.
- Envia alerta detalhado ao canal configurado em `log_channel`, sem permitir que menções no embed notifiquem usuários.
- Cada infração gera alerta; não há supressão de auditoria por cooldown.

## Limitações operacionais
- O bot precisa de `Manage Messages` para excluir mensagens e `Moderate Members` para timeout.
- O cargo mais alto do bot deve estar acima do cargo do infrator.
- O canal `log_channel` precisa existir e permitir `View Channel`, `Send Messages` e `Embed Links`.
- O conteúdo do log é truncado para respeitar limites de embed; anexos são registrados por URL.
- A validação executada nesta entrega é estática/compilação; o teste de integração requer executar o bot em uma guild de teste.
