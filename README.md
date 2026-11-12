# RANDOM • HELLSING — Bot Supremo v3.1.0

Bot Discord em Python com `discord.py`, comandos de barra e prefixo, menu Components V2, economia, coleção de cartas, tickets, cargos, sorteios, moderação, assistente de estrutura e integrações de IA.

## Requisitos

- Python 3.10 ou superior; a versão foi preparada para o Python 3.14 da Bot-Hosting.
- Bot criado no Discord Developer Portal.
- `DISCORD_TOKEN` cadastrado nas variáveis secretas da hospedagem.
- Intents `Message Content` e `Server Members` habilitados no Developer Portal.

## Instalação na Bot-Hosting

1. Pare o processo do bot.
2. Faça backup do banco `hellsing.db`.
3. Extraia o ZIP diretamente em `/home/container`, sem manter uma pasta extra por fora.
4. Confirme que `main.py`, `core.py` e `requirements.txt` estão na raiz.
5. Atualize os arquivos de código no GitHub, mas **não envie `.env`, tokens ou o banco SQLite**.
6. Cadastre as variáveis no painel de Ambiente.
7. Use `main.py` como arquivo de inicialização e reinicie.

Comando de instalação compatível com o prefixo local da hospedagem:

```bash
cd /home/container && if [ -f requirements.txt ]; then python3 -m pip install --disable-pip-version-check --prefix .local -r requirements.txt || exit 1; fi && exec python3 -u "${STARTUP_FILE:-main.py}"
```

O `main.py` acrescenta `.local/lib/pythonX.Y/site-packages` ao `sys.path`, portanto as bibliotecas instaladas com `--prefix .local` ficam acessíveis ao bot.

## Prefixos

O padrão é `;` e `!` fica habilitado por compatibilidade. A variável `ALLOW_BANG_PREFIX=0` desativa `!`. O log de inicialização deve mostrar `Prefixos ativos: ;, !`.

Comandos de prefixo adicionados/confirmados:

- `;menu`, `;painel`, `;ajuda`, `;ping`
- `;daily`, `;work`, `;saldo`, `;pagar @membro quantidade`, `;perfil`, `;rank level|souls`
- `;roll`, `;inventario`, `;carta nome`, `;duelo @membro`, `;desafio`
- `/forjar carta` (consome duas cópias no mesmo nível e evolui até Nv. 5)
- `;ia pergunta`, `;ia_status`, `;ia_testar all|openrouter|gemini|nvidia`, `;ia_modelos`, `;gerar_imagem descrição`
- `;montarservidor descrição` (gera prévia personalizada)
- `;personagens` (catálogo com GIFs)

Os recursos administrativos que não aparecem aqui continuam disponíveis como comandos `/`.

Se um comando slash novo não aparecer imediatamente, aguarde a propagação global do Discord ou configure `DEV_GUILD_ID` temporariamente para sincronizar os comandos na guilda de teste. Se nenhum comando de prefixo responder, confirme no Developer Portal: **Bot → Privileged Gateway Intents → Message Content Intent**. Ativar somente no código não basta. Reinicie o bot depois de alterar o intent.

## Menu Components V2

`/menu`, `;menu` e `;ajuda` abrem um menu com `LayoutView`, `Container`, `TextDisplay`, `Separator`, `ActionRow` e seletor. O seletor fica em uma `ActionRow` dentro do `Container`; mensagens antigas com `View` clássico continuam registradas para compatibilidade. Components V2 é um layout de componentes do Discord, não um Embed tradicional.

## Assistente de estrutura do servidor

Comandos: `/montar_servidor` ou `;montarservidor`.

O assistente cria uma estrutura inicial **no servidor em que o bot já está instalado**. A API de bot não cria uma nova guilda na conta do usuário. O fluxo exige confirmação e permissões de Gerenciar Servidor, Gerenciar Canais e Gerenciar Cargos.

`/montar_servidor` abre um formulário para descrever a comunidade e escolher o separador visual após os emojis. A IA cria um plano JSON de categorias, canais (texto/voz) e cargos; o bot valida o plano, mostra uma prévia e só executa após confirmação. Se o provedor principal falhar, o serviço tenta os demais provedores configurados. A versão por prefixo aceita `;montarservidor descrição` e usa o separador padrão `・`. O cargo de equipe é dedicado e persistido no banco; a IA não escolhe nem atribui permissões administrativas.

Proteções:

- Não exclui, renomeia nem altera permissões de canais/cargos já existentes.
- Reutiliza itens com o mesmo nome.
- Cria cargos sem permissão Administrador.
- A área privada usa um cargo exclusivo salvo no SQLite. Quem confirma a montagem recebe esse cargo e deve atribuí-lo aos demais membros da equipe. `@everyone` fica sem acesso aos canais privados; permissões de itens preexistentes não são alteradas.
- A prévia tem páginas **Anterior/Próxima**, para revisar categorias grandes antes de confirmar.
- A execução pode terminar parcialmente se o bot não tiver permissão ou atingir limites da API; o relatório final informa as ocorrências.

## Cartas

- `/roll` e `;roll`: invocação com custo, limites por hora/dia e reivindicação por botão.
- `/inventario` e `;inventario`: coleção com paginação.
- `/carta` e `;carta`: consulta de personagem.
- `/duelo` e `;duelo @membro`: disputa recreativa de atributos, **sem apostas e sem movimentar Souls**.
- `/vender` e `/trocar`: venda e proposta de troca.

ATK, DEF e HP são apenas atributos internos do minijogo. As imagens das cartas usam URLs remotas configuradas no catálogo. A disponibilidade depende do host externo e das regras de hotlink; se alguma imagem não carregar, substitua o campo `image` do personagem por uma URL HTTPS de imagem que você tenha direito de usar.

O gacha cria as colunas `roll_day` e `rolls_today` se ainda não existirem. Isso é feito por migração idempotente e preserva os registros existentes.

## APIs de IA e imagem

Cadastre as chaves no painel de Ambiente, sem colar valores nos arquivos do projeto:

| Variável | Provedor | Uso |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI | Geração de texto |
| `GROQ_API_KEY` | Groq | Geração de texto |
| `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | Cloudflare Workers AI | Geração de texto |
| `OPENROUTER_API_KEY` | OpenRouter | Geração de texto |
| `GEMINI_API_KEY` | Gemini | Geração de texto |
| `NVIDIA_API_KEY` | NVIDIA NIM | Geração de texto |
| `POLLINATIONS_KEY` | Pollinations | Geração de imagem |
| `DEFAULT_CARD_IMAGE` | — | URL HTTPS opcional de imagem alternativa para cartas |
| `YTDLP_COOKIES_INSTAGRAM` | Instagram | Caminho local opcional para cookies Netscape; não publique o arquivo |
| `YTDLP_COOKIES_TIKTOK` | TikTok | Caminho local opcional para cookies Netscape; não publique o arquivo |
| `YTDLP_COOKIES_TWITTER` | X/Twitter | Caminho local opcional para cookies Netscape; não publique o arquivo |
| `STABLE_DIFFUSION_KEY` | Stability AI | Geração de imagem |

Modelos padrão podem ser substituídos por `OPENAI_MODEL`, `GROQ_MODEL`, `CLOUDFLARE_MODEL` (padrão atual: `@cf/zai-org/glm-4.7-flash`; modelos antigos descontinuados são substituídos automaticamente), `OPENROUTER_MODEL`, `GEMINI_MODEL`, `NVIDIA_MODEL` e `POLLINATIONS_IMAGE_MODEL`. Os modelos e as cotas dos provedores podem mudar; uma chave presente não significa que a API está funcionando.

- `/ia_status` e `;ia_status` mostram chave configurada e o último resultado conhecido. Eles não fazem uma chamada de cobrança.
- `/ia_testar` e `;ia_testar` fazem uma chamada real de geração para o provedor selecionado. Requer Gerenciar Servidor e pode consumir cota.
- `/ia_modelos` e `;ia_modelos` consultam os catálogos e testam modelos individuais; o limite padrão é 50 modelos por provedor (ajustável entre 1 e 50) pela variável `AI_MODEL_PROBE_LIMIT`. O teste usa chamadas reais e pode consumir cota. Para Cloudflare, o teste usa diretamente o modelo configurado, sem depender da listagem do catálogo. Para OpenRouter, são testadas somente variantes `:free` e o roteador `openrouter/free`.
- `/ia` e `;ia` tentam o provedor selecionado ou usam fallback automático. Os provedores com seleção dinâmica consultam seus catálogos quando aplicável; Cloudflare executa diretamente `CLOUDFLARE_MODEL`, mantendo a consulta de catálogo separada para listagem. Os catálogos ficam em cache por uma hora e o último modelo que respondeu é priorizado em memória.
- Chamadas REST de texto limitam a concorrência a 4 requisições simultâneas por processo, usam timeout configurável (`AI_PROVIDER_TIMEOUT_SEC`, padrão 120s, máx. 300s; o fallback inteiro respeita `AI_TOTAL_TIMEOUT_SEC`, padrão 720s) e fazem retentativas curtas para HTTP 429/5xx quando o tempo indicado pelo provedor permite; o fallback continua ativo se o limite persistir.
- `/gerar_imagem` e `;gerar_imagem` geram e anexam o arquivo ao Discord, em vez de depender de URL autenticada no proxy de imagem.

A integração Gemini usa o endpoint REST `generateContent` e seleciona modelos que declaram suporte a esse método no catálogo. OpenRouter consulta `/api/v1/models` e limita o fallback a modelos explicitamente gratuitos (`:free`). Gemini e OpenRouter mantêm cache de uma hora. A NVIDIA consulta `/v1/models`, mantém cache de uma hora e tenta os modelos listados pelo catálogo NIM. `/ia_modelos` força atualização dos catálogos e testa os modelos encontrados; isso consome chamadas/cota dos provedores. Pollinations e Stability AI usam autenticação Bearer nas requisições de imagem.

## Banco de dados e segredos

- O arquivo padrão é `hellsing.db` (ajustável por `DB_PATH`).
- Mantenha o banco em armazenamento persistente da hospedagem.
- Nunca publique `.env`, `DISCORD_TOKEN`, chaves de API, cookies, `hellsing.db`, `hellsing.db-wal` ou `hellsing.db-shm` no GitHub.
- Não apague arquivos `-wal` ou `-shm` enquanto o bot estiver em execução.
- Faça backup do SQLite com o processo parado antes de atualizar.

## Verificação

- Mensagens de comando não recebem XP; continuam passando pelos filtros anti-link/anti-spam.
- Menções diretas ao Alucard obtêm o cog `IA` pelo bot e chamam `ask_ai`; a resposta é em embed. Não existe nesta versão um `cogs/ia_chat.py` para respostas espontâneas em canais ativados.
- Paginação do inventário e menu interativo desativam controles quando expiram.
- O saldo diário já é lido do banco após a atualização, sem somar a recompensa novamente.
- O modelo Gemini padrão configurado nesta versão é `gemini-3.8-flash`, atualmente listado como estável na documentação oficial; confirme os modelos habilitados para sua chave com `/ia_modelos`.
- Todos os arquivos Python passaram em compilação sintática (`compileall`).

A conexão real com o Gateway, as respostas das APIs e as interações precisam ser validadas na hospedagem, pois exigem token, chaves e cotas próprios. Neste ambiente não foi possível instalar `discord.py` para executar testes de integração; portanto, não se afirma que houve conexão real com Discord ou provedores.


### Alterações v3.0.17
- Índices SQLite para rankings, tickets ativos e fila de lembretes de bump.
- Cartas exibem barras visuais de atributos; valores são limitados para evitar formatação inválida.
- Lembretes de bump consultam apenas configurações vencidas.
- Janelas de anti-spam/raid e cooldowns do downloader expiram entradas antigas e limitam crescimento de memória.
- Concorrência de IA aumentada de 2 para 4 chamadas simultâneas por processo.
- Rerolls acumulam todos os vencedores anteriores e não repetem vencedores.
- Tickets geram transcrição `.txt` no canal de auditoria antes de apagar o canal; se o envio falhar, o ticket é preservado.
- Moderação ganhou ban por usuário fora do servidor, `/unban`, `/unmute`, `/aviso_remover` (com registro de auditoria) e lockdown de threads.
- `/perfil` e `;perfil` mostram partidas e vitórias em duelos, com persistência SQLite.
- `/ticket_fechar` só remove o canal depois que a transcrição for entregue ao canal de auditoria; o arquivo cobre até 1000 mensagens e registra URLs de anexos.

### Alterações v3.0.15
- Limite de diagnóstico de IA ampliado para até 50 modelos por provedor.
- Chat prioriza provedor que respondeu recentemente e usa timeout menor/configurável para acionar fallback mais cedo.
- NVIDIA reduz a tentativa normal a três modelos por chamada, priorizando o último modelo funcional.
- Downloader corrige a escada de qualidade quando o primeiro formato excede o tamanho, adiciona retentativas e suporte opcional a impersonação HTTP.
- Novo `/baixar status` identifica yt-dlp, gallery-dl, ffmpeg, curl-cffi e configuração de cookies sem exibir segredos. O downloader combina yt-dlp (vídeos) e gallery-dl (fotos/slideshows) para Instagram e TikTok. O X/Twitter permanece somente para vídeos; a disponibilidade depende do tipo de publicação e do suporte do extrator instalado.

### Alterações v3.0.14
- `/montar_servidor` recebe descrição em formulário e separador personalizado; gera prévia com emojis, canais e cargos antes de criar.
- Fallback entre OpenAI, Groq, Cloudflare Workers AI, OpenRouter, Gemini e NVIDIA NIM para chat e geração de estrutura.
- `/ia_modelos` consulta catálogos e testa modelos reais; limite padrão ampliado para 20 por provedor.
- Groq removido do fluxo ativo.
- Lembretes de bump manual adicionados; sem automação proibida pelo serviço de divulgação.
- Menu revisado para distinguir comandos slash e comandos com prefixo.
- `/personagens` e `;personagens` usam a mesma ficha visual.

### Histórico v3.0.13
- Removido somente o suporte a downloads do YouTube; Instagram, TikTok e X/Twitter continuam disponíveis.
- Mistral foi removido e Groq foi adicionado naquela versão; Groq foi posteriormente retirado na v3.0.14.
- NVIDIA ganhou descoberta dinâmica do catálogo, ainda sem teste de conectividade real no ambiente de desenvolvimento.
- Os 12 GIFs fornecidos foram associados às cartas do catálogo.


### Alterações v3.0.18
- Descoberta dinâmica de modelos Gemini e OpenRouter com cache de uma hora e atualização forçada no diagnóstico `/ia_modelos`.
- Fallback ampliado para até cinco modelos alternativos no Gemini/OpenRouter quando o modelo configurado não existe ou não está disponível.
- Catálogo NVIDIA integrado ao mesmo mecanismo de cache.
- Mensagem específica quando o Instagram informa que a publicação não contém vídeo.


## Provedores de IA de texto

O módulo `cogs/ia.py` aceita OpenAI, Groq, Cloudflare Workers AI, OpenRouter, Gemini e NVIDIA NIM. O modo automático tenta os provedores configurados e usa fallback quando um deles falha.

Configure as variáveis no painel de ambiente da hospedagem (não coloque chaves no código nem no GitHub):

- `OPENAI_API_KEY` e, opcionalmente, `OPENAI_MODEL`
- `GROQ_API_KEY` e, opcionalmente, `GROQ_MODEL`
- `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` e, opcionalmente, `CLOUDFLARE_MODEL`

Para Cloudflare Workers AI, o token precisa ter permissões de Workers AI Read e Workers AI Run/Write compatíveis com a conta. O Account ID é obrigatório. O catálogo de modelos é consultado pela API e armazenado em cache por uma hora; os modelos disponíveis dependem das permissões e da conta.

Comandos de diagnóstico: `/ia_status`, `/ia_testar` e `/ia_modelos`. Os testes de modelos fazem chamadas reais e podem consumir cota.


### Alterações v3.0.24 — auditoria e endurecimento
- Inicialização agora aborta com log claro se qualquer Cog não carregar; evita operar com comandos parcialmente registrados.
- Comandos de configuração, moderação, painel de verificação e painel de tickets receberam verificações de permissão no código, além das permissões padrão do Discord.
- Cargos legados de nível também são revalidados antes da atribuição; cargos gerenciados, acima do bot ou com permissões privilegiadas são bloqueados.
- Cargos de verificação e de nível são validados contra hierarquia, cargos gerenciados e permissões privilegiadas antes de serem configurados.
- SQLite configurado com WAL, `synchronous=NORMAL` e `busy_timeout`; helpers validam nomes de campos antes de montar SQL dinâmico.
- Downloader lê limites de ambiente com fallback seguro, respeita o limite efetivo informado pela interação e mostra se o arquivo de cookies realmente existe.
- A duração máxima é validada para todos os itens de um post/carrossel, não apenas o primeiro.
- Diagnóstico de modelo Cloudflare não deixa uma tentativa malsucedida substituir o modelo funcional anterior.
- `.env.example` agora documenta `DEFAULT_CARD_IMAGE` e `YTDLP_COOKIES_INSTAGRAM`.
- Não foi adicionado `cogs/ia_chat.py`; esta versão responde a menções, mas não inicia conversas espontâneas nos canais.

## Downloader v3.0.28

- `/baixar tiktok` oferece `Automático`, `Somente fotos/slideshow` e `Somente vídeos`. O yt-dlp trata vídeos; o gallery-dl tenta fotos/slideshows públicos quando disponíveis.
- Instagram mantém a funcionalidade multimídia que já existia na versão anterior; esta alteração nova de modos foi direcionada somente ao TikTok.
- X/Twitter voltou a oferecer somente download de vídeos, sem opções novas de fotos/GIFs.
- O processamento multimídia mantém o limite de até 4 itens por publicação e respeita o limite efetivo de upload do Discord.
- O downloader não exige chave de API do TikTok. yt-dlp e gallery-dl são ferramentas de extração; podem precisar de atualização quando a plataforma muda e continuam sujeitos a indisponibilidade, limites e regras do TikTok.
- Não coloque cookies, tokens ou chaves no GitHub. Cookies são credenciais de sessão e devem ficar apenas no armazenamento privado da hospedagem.

## Correções v3.0.29 — Cloudflare Workers AI

A geração Cloudflare não depende mais do endpoint de busca de modelos. O padrão foi atualizado para `@cf/zai-org/glm-4.7-flash`; IDs antigos conhecidos como descontinuados são substituídos pelo padrão atual. Consulte `CORRECOES-v3.0.29.md`.



## v3.0.39 — perfil fixo, setup e personalização

- Avatar permanece fixo: a rotina automática de troca de foto foi removida.
- Presença fixa: status online e atividade "Jogando use /ajuda para começar".
- A bio/descrição do perfil deve ser configurada manualmente na interface disponível para a aplicação; a API oficial de bots não oferece edição desse campo.
- `/missao` concede uma recompensa extra de Souls com cooldown persistido de 6 horas.
- `/nuke` recria somente o canal de texto atual após confirmação; o histórico antigo não é copiado.
- `/config painel_json` aceita um objeto JSON com textos para páginas do menu (`inicio`, `economia`, `gacha`, `acoes`, `moderacao`, `config`, `tickets`, `ia`, `extras`). Cada texto tem limite de 1.800 caracteres. Exemplo em `painel_personalizacao.exemplo.json`. `/config painel_json_reset` restaura os textos padrão.
- `/montar_servidor` agora sincroniza overwrites privados e tópicos em categorias/canais já existentes quando esses dados constam no plano. Não apaga em massa canais antigos: exclusão automática global é deliberadamente evitada para impedir perda acidental de dados.

### Limites de validação

A validação desta entrega cobre sintaxe, integridade do ZIP e testes estáticos. Não equivale a teste de execução em um servidor Discord real. A presença fixa é configurada no código; alterações futuras exigem editar a atividade padrão em `main.py`.


Versão do pacote: **3.1.0**.


## Correção v3.0.41

- O comando `/contrato` foi renomeado para `/missao`.
- Mantidos a recompensa aleatória de 180–380 Souls e o cooldown persistido de 6 horas.



## Tickets e memória contextual da IA — v3.0.48

- `/ticket_fechar` gera transcrição HTML com CSS embutido, tema escuro inspirado no Discord, cabeçalho de auditoria, horários UTC/locais, avatar, autor, mensagens e anexos clicáveis.
- Conteúdo textual, nomes e atributos HTML são escapados; URLs externas só são aceitas via HTTPS e o documento inclui Content-Security-Policy.
- O arquivo é enviado ao canal `ticket_log` antes de marcar o ticket como fechado ou apagar o canal. Se a geração HTML falhar, há fallback TXT; se o envio falhar, o ticket permanece aberto.
- Menções à Zerith mantêm até 6 mensagens recentes em RAM por servidor, usuário e canal, com expiração após 5 minutos. Os perfis individuais armazenam apenas contagens de preferência de estilo, não o texto das mensagens.
- O histórico contextual é enviado como mensagens `system/user/assistant` aos provedores OpenAI-compatible e adaptado ao formato de conteúdo do Gemini. Falhas não são armazenadas e ativam cooldown de 30 segundos por usuário/canal.
- A memória é volátil: reiniciar o processo limpa os contextos, por projeto.


## Forja de cartas

Use `/forjar carta` para combinar duas cópias da mesma carta e do mesmo nível. A operação consome as duas cópias e cria uma única carta no nível seguinte, até Nv. 5. Cada nível acima do Nv. 1 concede +5% de ATK e DEF; o HP não é alterado. O inventário exibe níveis separados e o `/duelo` considera os atributos evoluídos.


## Zerith (v3.0.58)
Veja `ZERITH-v3.0.58.md` para a personalidade contextual da IA.

## Funções novas (v3.1.0)

**Boas-vindas e autorole** (`/boasvindas`): mensagem personalizável com variáveis (`{membro}`, `{nome}`, `{usuario}`, `{servidor}`, `{contador}`, `{regras}`), cartão de imagem gerado com o avatar (requer Pillow), DM de entrada, mensagem de despedida, cargos automáticos para membros e para bots (respeita a triagem de membros do Discord) e `/boasvindas testar` para prévia.

**Loja** (`/loja`): a staff cria itens com preço, estoque opcional e cargo opcional; membros compram com Souls. A compra é atômica e, se o cargo não puder ser entregue, as Souls são devolvidas.

**Cassino** (`/cassino`): moeda (1,9x), caça-níquel (até 75x), dados (5,5x), roleta europeia (2x/36x), blackjack com botões (pedir, parar, dobrar) e roubo com cooldown de 2h. Aposta mínima 10, máxima configurável em `/cassino config`. Todos os jogos têm leve vantagem da casa para não inflar a economia.

**Automod** (`/automod`): filtro de palavras (ignora acentos, maiúsculas, letras repetidas, trocas como `4`→`a` e letras separadas), filtros de maiúsculas, emojis, repetição, flood de linhas e links com lista de domínios liberados, punição progressiva (timeout após X infrações em 10 min), anti-raid com modo alerta ou expulsão automática, idade mínima de conta e isenção por cargo ou canal. Tudo é registrado no canal de logs. Mensagens bloqueadas não geram XP nem executam comandos.

**Social**: `/lembrete` (DM ou canal; aceita `10m`, `2h30m`, `3 dias`, `1 semana`), `/enquete` (enquete nativa do Discord), `/sugestao` (canal com votação, tópico de discussão e resposta da staff com aviso por DM), `/aniversario` (anúncio automático à meia-noite, cargo do dia, idade opcional) e `/afk` (avisa quem te mencionar e adiciona `[AFK]` ao apelido). O fuso dos aniversários vem de `BOT_TZ` (padrão `America/Sao_Paulo`).

## Logs (v3.0.59)

**Console e arquivo:** formato `data | nível | módulo | mensagem`, nível configurável por `LOG_LEVEL`, arquivos rotativos em `logs/hellsing.log` (tudo) e `logs/erros.log` (só erros). Cada comando usado gera uma linha em `hellsing.comandos` com servidor e usuário; erros trazem o comando, o contexto e o traceback. Exceções de tarefas assíncronas soltas também vão para o log.

**Canal do servidor:** `/config logs canal:#logs` define o canal; `/config logs_eventos ativo:true/false` liga ou desliga o registro de eventos. São registrados: mensagens apagadas/editadas, limpezas em massa, entradas (com alerta de conta nova) e saídas, expulsões, banimentos e desbanimentos, timeouts, apelidos, cargos de membros, entrada/saída/troca de call, canais e cargos criados/apagados. Com a permissão **Ver registro de auditoria**, o log mostra quem fez a ação e o motivo. Ações do próprio bot (comandos de moderação, cargos de nível, tickets) não são duplicadas.

## Remoção da música (v3.0.59)
O módulo de música (Lavalink/wavelink) foi removido por completo: comandos `/tocar`, `/fila`, `/pular` etc., dependência `wavelink`, variáveis `LAVALINK_*` e a tabela `music_player_panels` (apagada automaticamente no boot).
