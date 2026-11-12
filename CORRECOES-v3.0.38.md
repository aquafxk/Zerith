# RANDOM • HELLSING v3.0.38

## Alterações
- Adicionado `cogs.profile_rotation`: rotação persistente de avatar e atividade em ciclos de 3 dias.
- Adicionado `profile_rotation.json` e pasta `assets/profile/`.
- Registrado o novo cog no carregamento principal.
- Corrigida a sincronização de overwrites privados em categorias e canais existentes no `/montar_servidor`; tópicos de canais existentes também são atualizados.
- Adicionado `/contrato`, recompensa adicional de Souls com cooldown persistido de 6 horas.
- Adicionado `/nuke`, que recria somente o canal atual depois de confirmação explícita. O histórico antigo não é copiado.
- Adicionada personalização dos textos do menu por JSON em `/config painel_json` e restauração por `/config painel_json_reset`.

## Limitações conhecidas
- Bots não podem editar o campo "Sobre mim" pela API oficial do Discord. A rotação usa atividade/status.
- Nenhuma imagem de avatar é incluída por padrão. O administrador precisa colocar imagens em `assets/profile/` e listá-las em `profile_rotation.json`.
- `/montar_servidor` não apaga automaticamente todos os canais antigos. Faz reconciliação dos itens previstos e sincroniza permissões privadas; limpeza global exigiria uma etapa adicional de confirmação destrutiva com inventário e salvaguardas.
- `/nuke` é limitado ao canal de texto em que foi executado.
- Não foi possível validar comportamento em um servidor Discord real nesta execução.
