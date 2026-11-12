# RANDOM • HELLSING v3.0.57 — Forja/Evolução de cartas

## Implementação

- Adicionada a coluna `cards.level INTEGER NOT NULL DEFAULT 1` no schema para novas instalações.
- Migração idempotente em `Gacha.cog_load()` adiciona `level` a bancos existentes sem apagar nem recriar cartas.
- Índice `idx_cards_forge(guild_id, user_id, card_key, level)` para localizar pares rapidamente.
- Novo comando slash `/forjar carta`, com autocomplete limitado às cartas que possuem pelo menos duas cópias no mesmo nível.
- A forja exige duas cópias da mesma carta e do mesmo nível; consome as duas e cria uma carta no nível seguinte. Operação protegida por `BEGIN IMMEDIATE`, lock local, validação de `rowcount`, `commit` e `rollback`.
- Nível máximo Nv. 5. Não permite combinar cartas de níveis diferentes nem evoluir acima do limite.
- ATK e DEF recebem +5% por nível acima do Nv. 1: Nv. 1 = base; Nv. 2 = +5%; Nv. 3 = +10%; Nv. 4 = +15%; Nv. 5 = +20%. HP permanece inalterado.
- `/duelo` escolhe uma instância real da coleção e aplica o nível dela ao ATK/DEF antes de calcular o poder. O resultado informa nível e atributos calculados.
- Inventário passou a separar quantidades por nível e exibir ATK/DEF já ajustados.
- Reivindicação, troca e venda de cartas compartilham o lock de mutação da coleção; troca e venda confirmam transações e preservam o nível individual da carta.

## Compatibilidade

- Cartas antigas recebem `level=1` automaticamente na migração.
- Não há necessidade de apagar, exportar ou recriar `hellsing.db`.
- A implementação usa a conexão `aiosqlite` já existente no projeto.

## Validação executada

- Compilação sintática dos arquivos Python do projeto.
- Teste SQLite isolado da migração sobre tabela antiga, combinação de duas cópias, preservação de uma carta evoluída, níveis sequenciais até Nv. 5 e rejeição de forja sem par.
- Verificação de integridade do ZIP.

## Limitações da validação

O ambiente não possui `discord.py` nem `aiosqlite` instalados. Portanto, não foi possível carregar o Cog, validar o registro real do comando slash no Discord nem executar integração com gateway. O teste SQLite usa a biblioteca padrão e reproduz as instruções SQL da operação.
