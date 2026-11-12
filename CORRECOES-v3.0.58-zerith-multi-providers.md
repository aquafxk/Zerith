# RANDOM • HELLSING — v3.0.58

## Zerith
- Substituída a identidade anterior por Zerith, personagem original de anime com traços fofos, tsundere leve, energética, caótica e sarcástica.
- Menções, `/ia` e `;ia` ajustam o tom conforme a mensagem atual e a tendência aprendida por usuário.
- Histórico de menções isolado por servidor/usuário/canal e mantido somente em RAM por até cinco minutos.
- SQLite guarda apenas contagens de estilo; `/zerith_esquecer` e `;zerith_esquecer` removem o perfil e o histórico temporário do autor.

## Música
- Corrigido o reconhecimento de links do YouTube para o fallback via oEmbed.
- `/tocar` e `;tocar` compartilham a busca e a fila; busca padrão em YouTube Music, fallback SoundCloud configurável.
- Adicionados seletores e links para YouTube, YouTube Music, SoundCloud, Spotify, Apple Music, Deezer, Yandex, VK Music, Tidal, Qobuz e JioSaavn.
- Adicionado `/fontes_musica` e `;fontes`.
- Configuração do servidor Lavalink v4 adicionada em `lavalink/application.yml.example`, com YouTube Source 1.18.2 e LavaSrc 4.8.3.

## Validação
- Compilação estática de todos os arquivos Python.
- Parse YAML do exemplo do Lavalink.
- Testes unitários isolados do roteamento das consultas e reconhecimento de URLs.
- Não foi possível validar reprodução real sem conexão com o Lavalink configurado e um servidor Discord ativo.
