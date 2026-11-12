# RANDOM • HELLSING — v3.0.55

## Ajustes complementares da migração aiosqlite

Esta versão complementa a v3.0.54; não substitui as correções funcionais anteriores.

- Preservada integralmente a allowlist `USER_UPDATE_FIELDS`: `souls`, `xp`, `level`, `streak`, `last_daily`, `last_work`, `last_quiz`, `last_xp`, `roll_window`, `rolls_used`, `roll_day`, `rolls_today`, `last_ai`, `last_image`, `duels_played`, `duels_won`, `last_contract`.
- Corrigido um problema importante da migração: `from core import db` copiava o valor `None` durante a importação dos cogs. Agora os cogs usam `get_db()`, que consulta a conexão global ativa depois de `setup_hook()`.
- `cogs/painel.py`: `_page_embed()` permanece assíncrona e seu único ponto de chamada nesta versão agora usa `await`. Os outros caminhos do menu já usam `build_menu_view()` assíncrona.
- `cogs/musica.py` mantém acesso dinâmico por `core_module.db`; não foi alterado o `AutoPlayMode.partial`, que não acessa o banco.
- `main.py`: `setup_hook()` registra explicitamente a configuração aiosqlite/WAL/busy_timeout/Row. `close()` chama `close_db()` primeiro (checkpoint e fechamento do SQLite) e `super().close()` em `finally`.
- `requirements.txt`: aiosqlite fixado na faixa `>=0.20.0,<0.21`.
- Adicionados `pyrightconfig.json` e `requirements-dev.txt` para detectar corrotinas não aguardadas (`reportUnusedCoroutine`).
- `get_user()` mantém o comportamento de criar o registro se não existir e fecha o cursor de INSERT com `async with`.

## Validações realizadas

- `python -m compileall -q .`: aprovado.
- Auditoria AST de chamadas a `get_user`, `update_user`, `get_config`, `set_config` e `add_case`: nenhuma chamada sem `await` encontrada.
- Auditoria de imports: nenhum cog importa mais `db` diretamente do `core`.
- Auditoria de acessos: nenhum acesso `db.` estático restante nos cogs; o acesso dinâmico em `cogs/musica.py` continua protegido por verificação de conexão.
- Allowlist `USER_UPDATE_FIELDS`: conferida integralmente.
- Integridade do ZIP: validada após empacotamento.

## Limitações

O ambiente de geração não possui `aiosqlite` nem `pyright` instalados. Portanto, não foi possível executar teste de integração SQLite com a dependência real nem a análise Pyright. O bot também não foi conectado ao Discord/Lavalink. Instale `requirements.txt` no ambiente de hospedagem e execute `pip install -r requirements-dev.txt && pyright` antes do deploy.
