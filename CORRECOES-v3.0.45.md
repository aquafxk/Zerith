# v3.0.45 — Música (Lavalink)

## Novo cog `cogs/musica.py`
Comandos slash:
- `/tocar` — nome ou link
- `/pausar` `/continuar` `/pular` `/parar`
- `/fila` `/volume` `/sair_voz`
- `/musica_status`

Prefixo: `;tocar` `;play` `;p`

## Configuração Bot-Hosting
1. Ative o **Lavalink** no painel (1 clique)
2. Copie host, porta e senha
3. No `.env` do bot:
```
LAVALINK_URI=http://HOST:PORTA
LAVALINK_PASSWORD=senha_do_painel
```
4. Intent **Voice States** já habilitada no código; confira no Developer Portal
5. `pip install -r requirements.txt` (inclui `wavelink`)

## requirements
- `wavelink>=3.4.0,<4.0`
