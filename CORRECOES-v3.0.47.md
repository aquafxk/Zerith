# v3.0.47 — Painel de música com controles persistentes

## `cogs/musica.py`
- Unificada a rotina usada por `/tocar` e `;tocar`; ambos registram solicitante e canal original na faixa/fallback local.
- O evento `on_wavelink_track_start` publica embed com título, duração formatada, thumbnail quando disponível, solicitante, fonte e volume.
- Criada `MusicPlayerView` com cinco botões: pausar/continuar, pular, parar, volume -10 e volume +10.
- Cada callback valida player/node ativos, painel vigente, cooldown e presença do membro na mesma sala de voz do bot.
- Botões persistentes com `timeout=None` e `custom_id` fixos; `bot.add_view()` registra o painel-base e uma View específica por mensagem durante `cog_load`. O ID do painel atual é persistido no SQLite para restauração após reinício.
- O botão de pausa alterna rótulo, emoji e estilo conforme `player.paused`.
- Volume dos botões limitado a 0–150 para manter compatibilidade com o comando `/volume` existente.
- Painel antigo é desativado quando uma nova faixa começa; painel final é desativado ao terminar a fila.
- `/parar` e o botão Parar limpam a fila; o bot sai da voz após 30 segundos sem nova faixa.
- Validação das permissões Ver canal/Conectar/Falar antes de entrar na sala.
- Fallback visual para Lavalink/player offline; o evento de fechamento do node desativa os painéis ativos. Painéis desatualizados são desativados sem afetar a View global de outras guildas. Views aposentadas são removidas do dispatcher.

## Compatibilidade e validação
- Implementação direcionada a `wavelink>=3.4.0,<4.0` e `discord.py>=2.6.4,<3.0`, conforme `requirements.txt`.
- A API Wavelink 3.x usa `Playable.artwork`, duração em milissegundos e `Player.pause()`, `Player.skip()` e `Player.set_volume()`.
- Validação desta entrega: compilação Python e verificações estáticas locais. Não houve teste com credenciais reais, node Lavalink ativo ou servidor Discord.
