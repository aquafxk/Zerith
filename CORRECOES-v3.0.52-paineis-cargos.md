# v3.0.52 — Painéis interativos de cargos

## Implementado
- Adicionados `/painel_cargos_botoes` e `/painel_cargos_menu`, com título, descrição e até cinco pares cargo/label/emoji.
- Botões alternam entre adicionar e remover o cargo; o estilo e o rótulo do botão são atualizados após o clique.
- O menu permite selecionar uma ou mais opções; cada opção selecionada alterna o cargo correspondente.
- Criação restrita a membros com `Gerenciar Cargos`, em servidores, e exige `Gerenciar Cargos` no bot.
- Validação de todos os cargos antes da publicação; se um cargo falhar, o painel inteiro é bloqueado.
- `role_problem` valida hierarquia do bot e do criador, permissões administrativas, `@everyone`, cargos gerenciados e cargos de impulsionador.
- Hierarquia e permissões são revalidadas em cada interação; erros `Forbidden` e `HTTPException` recebem tratamento.
- Views persistentes registradas por `custom_id` e restauradas no `on_ready` após reinicializações.
- Nova tabela SQLite `role_panels` armazena mensagem, servidor, canal, tipo e opções do painel.
- Registros de painéis cujo canal não existe mais são removidos na restauração.
- O comando legado `/painel_cargos` por reações foi mantido para compatibilidade.

## Validação
- `py_compile` passou para `cogs/roles.py` e `core.py`.
- AST validada e schema SQLite executado em banco temporário.
- Confirmadas as 17 opções de cada comando (abaixo do limite de 25 opções do Discord).
- Teste real de interação no Discord não executado; o ambiente desta execução não tinha `discord.py` instalado e não permitiu baixar dependências.
