# RANDOM • HELLSING — Novidades v3.1.0

São 9 comandos de barra novos no total (81 de 100 permitidos pelo Discord). As funções novas usam subcomandos para economizar esse limite.

## Boas-vindas e autorole — `/boasvindas`
| Comando | O que faz |
|---|---|
| `canal` | Canal das boas-vindas (o mesmo de `/config boasvindas`) |
| `mensagem` | Texto personalizado; `padrao` restaura o original |
| `imagem` | Cartão com o avatar, o nome e o número do membro (requer Pillow) |
| `dm` | Mensagem privada para quem entra |
| `saida` | Canal e mensagem de despedida |
| `autorole` / `autorole_bot` | Até 10 cargos automáticos para membros e para bots |
| `ver` / `testar` | Mostra a configuração e envia uma prévia |

Variáveis: `{membro}` `{nome}` `{usuario}` `{servidor}` `{contador}` `{regras}`.
- **Triagem de membros:** com a triagem ativa, o cargo só é dado depois que o membro aceita as regras.
- **Validação de cargos:** cargos perigosos ou acima do bot são recusados.

## Loja — `/loja` e `;loja` / `;comprar`
- **Staff:** `adicionar` (nome, preço, cargo opcional, estoque opcional, descrição), `editar` e `remover`.
- **Membros:** `ver`, `comprar` (com autocompletar) e `itens`.
- **Compra segura:** a compra é atômica (saldo, estoque e inventário juntos). Se o cargo não puder ser entregue, as Souls são devolvidas.

## Cassino — `/cassino`
| Jogo | Pagamento | Retorno médio |
|---|---|---|
| `moeda` · `;moeda` | 1,9x | 95% |
| `slots` · `;slots` | par 1,3x · trio 3x a 75x | ≈92% |
| `dados` | 5,5x | ≈92% |
| `roleta` | cor/par/ímpar 2x · número 36x | ≈97% |
| `blackjack` | 2x · blackjack 2,5x · dobrar | — |
| `roubar` · `;roubar` | 40% de chance de levar de 10% a 25% da vítima (máx. 5.000). Se falhar, paga multa à vítima | cooldown 2h |

- **Configuração (`config`):** liga e desliga o cassino e o roubo, e define a aposta máxima (padrão 50.000). A aposta mínima é 10.
- **Saldo protegido:** cada aposta é liquidada em um único comando no banco, então cliques simultâneos não geram saldo negativo. Testado com 20 apostas simultâneas: só as que cabiam no saldo foram aceitas.
- **Logs:** prêmios líquidos acima de 10.000 aparecem no log como aviso.

## Automod — `/automod`
- **`filtro`:** maiúsculas em excesso, 10+ emojis, mensagem repetida 3x em 20s, 15+ linhas e links fora da lista liberada.
- **`palavra` / `palavras`:** filtro de palavras inteiras. Ignora acentos, maiúsculas, letras repetidas, trocas como `1d10t4` e letras separadas (`p.a.l.a.v.r.a`), sem falso positivo em palavras maiores.
- **`punicao`:** timeout automático após X infrações em 10 minutos.
- **`antiraid`:** `off`, `alerta` ou `expulsar` (expulsa quem entrar durante o bloqueio). Também há `raid_encerrar`.
- **`idade_minima`:** expulsa contas mais novas que X dias.
- **`isentar` e `link_permitido`:** isenção por cargo ou canal e domínios liberados. A staff com Gerenciar Mensagens é sempre isenta.
- **Logs e bloqueio:** toda ação vai para o canal de logs. Uma mensagem bloqueada não gera XP, não chama a Zerith e não executa comando de prefixo.

## Social
- **`/lembrete criar | listar | cancelar` e `;lembrar 10m texto`:** o aviso vai por DM ou no canal. Aceita `10m`, `2h30m`, `3 dias` e `1 semana`, com até 25 lembretes por pessoa e prazo de até 365 dias.
- **`/enquete`:** enquete nativa do Discord, com 2 a 10 opções, de 1 a 768 horas, e voto múltiplo opcional.
- **`/sugestao enviar | responder | canal`:** a sugestão sai com votação ✅/❌ e tópico de discussão. A staff marca como aprovada, recusada, em análise ou implementada, e o autor recebe aviso por DM.
- **`/aniversario definir | remover | ver | proximos | config`:** anúncio à meia-noite (fuso `BOT_TZ`), cargo do dia removido no dia seguinte e idade opcional. Quem faz aniversário em 29/02 é lembrado em 28/02 nos anos não bissextos.
- **`/afk` e `;afk`:** avisa quem te mencionar, coloca `[AFK]` no apelido e tira tudo quando você volta a falar.

## Instalação
- Rode `pip install -r requirements.txt` (agora inclui o Pillow para o cartão de imagem; sem ele, a boas-vindas sai só em embed).
- As tabelas novas são criadas sozinhas na primeira inicialização, e os dados existentes são mantidos.
- A boas-vindas e o alerta de raid antigos de `events.py` foram migrados para os módulos novos. Quem já tinha `/config boasvindas` continua funcionando sem mexer em nada.
- O menu `/menu` ganhou as páginas **Loja e cassino** e **Comunidade**, e a página de moderação lista o automod.

## Limitações conhecidas
- O bloqueio anti-raid e as infrações do automod ficam na memória e zeram se o bot reiniciar.
- Uma partida de blackjack em andamento durante um reinício perde a aposta.
