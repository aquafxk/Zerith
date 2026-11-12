# RANDOM • HELLSING v3.0.37

- Removido completamente o módulo Spotify, seus comandos, carregamento, credenciais de ambiente e referências na ajuda/documentação.
- Corrigida a sanitização dos nomes gerados por IA no `/montar_servidor`: remove prefixos internos `cogs.setup`, `setup_` e variações com delimitadores antes da prévia e da criação.
- Mantida a validação numérica do limite de caracteres dos nomes.
- Nenhuma exclusão de canais/categorias é feita automaticamente; o fluxo continua sem apagar a estrutura existente.
