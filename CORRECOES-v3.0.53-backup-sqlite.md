# v3.0.53 — Backup SQLite seguro

## Alterações
- `cogs/app_servidor.py` agora executa backup automático ao iniciar (após o bot ficar pronto) e repete a cada 24 horas.
- O snapshot é criado com `sqlite3.Connection.backup()` em thread separada, compatível com o banco em modo WAL e com a conexão `aiosqlite` já aberta pelo bot.
- Os arquivos diários são gravados em `backups/hellsing_backup_YYYYMMDD.bak`.
- O backup temporário é validado com `PRAGMA quick_check` e publicado por substituição atômica.
- A limpeza mantém os cinco arquivos diários mais recentes por data de modificação.
- Novo comando `/dono backup`, restrito aos IDs de `OWNER_ID`/`OWNER_IDS`, gera uma cópia, compacta se necessário e envia o anexo em resposta efêmera.
- O arquivo temporário do comando manual é removido após o envio ou falha.
- A task é cancelada em `cog_unload`; falhas ficam registradas no log sem derrubar o bot.
- A pasta `backups/` e os arquivos `.bak` são ignorados pelo Git.

## Observações
- O loop solicitado é `@tasks.loop(hours=24)`: a primeira execução ocorre depois que o bot fica pronto; as seguintes ocorrem 24 horas após cada execução. Não é um horário fixo de relógio.
- O comando manual respeita o limite de upload informado pelo Discord para a interação; tenta gzip quando o `.bak` excede esse limite.
- O backup diário mantém no máximo cinco arquivos. A cópia manual enviada por `/dono backup` é temporária e não entra na retenção diária.
- Validação estática e testes locais não substituem um teste no host real com o banco em uso.
