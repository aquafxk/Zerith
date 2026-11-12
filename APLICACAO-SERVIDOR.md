# Aplicação do servidor — Hellsing

## 1. Criar a Application no Discord

1. Abra https://discord.com/developers/applications
2. **New Application** → nome do bot
3. **Bot** → Reset Token → copie para `DISCORD_TOKEN` no `.env`
4. Ative intents necessários (Message Content, Server Members, Presence se usar)
5. **OAuth2 → URL Generator**: scopes `bot` + `applications.commands`
6. Permissões mínimas: Manage Channels, Manage Roles, Send Messages, Embed Links, Attach Files, Read History, Connect/Speak (só se for usar voz no futuro)
7. Abra a URL gerada e adicione o bot no servidor

## 2. Dono do bot

No `.env`:

```
OWNER_ID=SEU_USER_ID
```

User ID: Discord → Configurações → Avançado → Modo desenvolvedor → clique direito no seu nome → Copiar ID.

Comandos: `/dono status` · `/dono guilds`

## 3. Ativar a aplicação **neste** servidor

1. `/app_servidor` — vê o checklist
2. `/montar_servidor` — estrutura de canais (opcional, usa IA)
3. `/config boasvindas` · `/config logs`
4. `/config ticket_categoria` · `/config ticket_staff` · `/painel_ticket`
5. `/config cargo_nivel` — recompensas por nível
6. `/bump_lembrete` — se usar divulgação

## 4. O que já vem no bot

| Módulo | Comandos |
|--------|----------|
| Tickets | `/painel_ticket`, `/ticket`, `/ticket_fechar` |
| Níveis/XP | `/perfil`, `/rank`, daily/work dão XP |
| Economia | `/daily`, `/work`, `/missao`, `/saldo` |
| Gacha | `/roll`, `/inventario` |
| IA | `/ia`, `/ia_status` |
