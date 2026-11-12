# Dominio economia (item 10 — sem fusao fisica)

Os cogs `economia.py`, `loja.py`, `cassino.py` e `gacha.py` compartilham `users.souls`.
A unificacao em pacote unico foi adiada de proposito: alto risco de regressao em
slash commands ja sincronizados. Anti-abuso e `economy_log` ja cruzam os modulos.
