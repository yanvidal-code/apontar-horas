---
name: apontar-horas
description: Preenche e confere a planilha de horas do ClickUp a partir das transcrições de sessão. Use quando o usuário pedir para apontar horas, preencher time tracking, ver quanto falta num dia, ou descobrir em que task trabalhou em determinada data. Cobre leitura, sugestão determinística a partir das conversas, prévia e escrita confirmada.
---

# Apontar horas no ClickUp

## Entrada por um comando só

```bash
apontar                      # semana corrente
apontar ontem
apontar "semana passada"
```

Abre o Claude Code interativo com `/apontar` como prompt inicial (veja
`commands/apontar.md`, nesta pasta): o agente lê, resolve o que dá, sobe o front em
segundo plano, informa a URL e **continua no terminal** para a conversa seguir.
Na primeira vez, antes disso, configura a digital (veja "Configuração do zero").
`./clickup-time.sh front --parar` encerra o servidor depois.

Os scripts desta pasta fazem o que é verificável por regra. **Você faz o que exige
leitura.** A fronteira é o ponto inteiro da skill — não a atravesse em silêncio.

| Quem | Faz |
|---|---|
| script | horário, âncora explícita, faixas livres, grade de 15min, sobreposição, duplicata |
| você (LLM) | resolver os `???`, consolidar fatias, mapear PR→task, propor |
| o usuário | aprovar antes de gravar |

## Configuração do zero

O token **nunca** passa pelo chat nem pelo seu contexto. Se a leitura do token
falhar, **pare e peça ao usuário para rodar, num terminal dele fora do Claude
Code, o comando que a mensagem de erro mostra** (o `apontar`) — não
tente contornar, não peça o token colado, não grave você mesmo. O `digital`
recusa rodar sem terminal justamente para isso.

**1. O `apontar` configura na primeira vez.** Antes de abrir o Claude Code ele
roda `./clickup-time.sh digital --conferir`, que não pede nada. Se faltar algo,
configura ali mesmo, no terminal:

- instala o `clickup-token` que vem pronto em `bin/` (universal: Apple Silicon e
  Intel) em `~/Library/Application Support/clickup-time/`. Não compila nada: quem
  usa a skill não precisa de Xcode nem das Command Line Tools;
- pede o token do ClickUp sem eco — avatar → *Settings* → *Apps* → *API Token*,
  começa com `pk_`;
- apaga o item anterior do Keychain e grava um novo que só o `clickup-token` lê.

Daí em diante, cada leitura pede a digital (tampa fechada ou teclado sem Touch
ID: o mesmo diálogo aceita a senha do Mac). Para trocar o token, por exemplo
depois de regenerar no ClickUp: `./clickup-time.sh digital`.

É o único jeito de guardar o token. Até 29/09/2026 havia também o item do
`security` com `-T ""` e a variável `CLICKUP_TOKEN`; os dois saíram — o diálogo
do `security` só aceitava a senha do chaveiro, e a variável ia para o histórico.

**2. Logar o `gh`** (fonte GitHub, opcional). Sem ele o `apontar` avisa, o
`sugerir` mostra `github  não instalado` e segue com as outras fontes.

```bash
brew install gh
gh auth login            # GitHub.com, HTTPS, login pelo navegador
gh auth status           # escopos: precisa de repo e read:org
gh api user/orgs --jq '.[].login'   # tem que listar irrahgroup
```

O que o `--conferir` e o `clickup-token` dizem quando falta algo:

| mensagem | o que fazer |
|---|---|
| `o clickup-token não está instalado` | `./apontar` ou `./clickup-time.sh digital` |
| `a skill trouxe um clickup-token novo` | o mesmo: instala o novo e pede o token de novo |
| `o clickup-token não veio com a skill` | quem mantém a skill roda `digital --compilar` |
| `o token não está no Keychain` (saída 44) | o mesmo |
| `o token está num item antigo` (saída 45) | o mesmo: é um item do `security`, de antes |
| `digital recusada ou cancelada` (saída 51) | rodar de novo e confirmar |

## Os comandos

```bash
./clickup-time.sh read    --from 2026-09-01 --to 2026-09-04 [--json] [--html]
./clickup-time.sh sugerir --from 2026-09-01 --to 2026-09-04 [--json]
./clickup-time.sh tarefas HM-423 HM-386 [--json] [--max-chars 1500]
./clickup-time.sh write   --date 2026-09-02 --entry "09:00 45m HM-204" [--html X]
./clickup-time.sh write   --date 2026-09-02 --entry "..." --confirm
./clickup-time.sh digital            # grava o token; só num terminal do usuário
./clickup-time.sh digital --conferir # diz o que falta, sem pedir nada
./clickup-time.sh digital --compilar # quem mantém: gera bin/clickup-token (exige o Xcode)
```

`read`, `sugerir` e `tarefas` só leem. `write` **sem** `--confirm` é prévia e não
faz POST. Cada execução pede a digital uma vez.

`tarefas` devolve nome, status, lista, link e a descrição (texto puro, cortada)
de cada task. É a fonte do `requisito` que vai no resumo do plano.

### A agenda vem do pedido, não de config

Os padrões são `08:00–18:00`, almoço `12:00–13:30`, blocos de 15min e meta de
510min — e batem com o que a planilha do ClickUp já mostra por dia. O almoço era
`12:30–14:00` até 29/09/2026: para reapontar dias de antes, passe
`--lunch-start 12:30 --lunch-end 14:00`, senão lançamento de 12:00–12:30 sai como
"no almoço" e 13:30–14:00 aparece como buraco. **Não existe
arquivo de configuração, de propósito**: ele seria uma terceira fonte de verdade
brigando com o padrão do código e com o que o usuário pede na hora.

Quando o usuário mencionar um dia diferente, passe as flags — todos os quatro
comandos aceitam:

```bash
--work-start 09:00  --work-end 20:00      # "entrei 9h e virei ate 20h"
--lunch-start 13:00 --lunch-end 14:00     # "almocei 13h"
--target-minutes 630                      # a meta acompanha o expediente
--block-minutes 30                        # blocos maiores
```

A agenda é validada antes de qualquer chamada de rede: exige
`work-start < lunch-start < lunch-end < work-end`, e a meta não pode passar do
líquido disponível. Se o usuário esticar o expediente sem ajustar a meta, o dia
vai sobrar — avise em vez de deixar passar.

## O fluxo

1. **`sugerir --json`** — devolve, por dia: minutos já apontados, faixas livres, e
   blocos com `task` preenchida (âncora encontrada) ou `task: null` com
   `reason: sem_ancora | sem_atividade`.

2. **Resolva os `null`.** Aí entra leitura: abra a sessão daquele horário nas
   transcrições e veja do que se tratava. **Declare que é inferência sua** — nunca
   apresente leitura como se fosse âncora.

3. **Feche o dia com a task mais próxima.** O que sobrar depois da leitura não
   fica em aberto: preencha com a vizinha, `origem: "proximidade"`. As regras,
   abaixo. **Isso é padrão desde 11/09/2026** — o usuário pediu assim.

4. **Consolide.** O script devolve fatias de 15min; sessões paralelas produzem
   blocos alternando entre duas tasks de 15 em 15. Junte antes de propor.

   **A grade de 15min é só a unidade das marcações**, não o jeito de apresentar.
   Nada que o usuário vê — tela ou terminal — sai de 15 em 15, nem repete a mesma
   task em linhas seguidas: trechos encostados da mesma task são **um lançamento
   só**, e só se dividem quando há algo entre eles (um evento já marcado, o
   almoço, um buraco sem proposta). No plano, mantenha um item por trecho de
   origem distinta, cada um com a sua `nota`; o front junta os encostados numa
   linha e mostra a composição por origem dentro dela. `fundir_contiguos()` faz a
   mesma fusão na escrita, então terminal, tela e planilha dão a mesma resposta.

5. **Resuma cada task do dia.** Rode `tarefas` com as tasks do plano e escreva,
   por dia e por task, o `requisito` (o que a task pede, em uma ou duas frases,
   a partir da descrição) e o `feito` (o que foi feito nela **naquele dia**, a
   partir das transcrições, PRs e comentários). É o que a tela mostra no fim da
   Lista. Resuma com as suas palavras: a descrição da task já trouxe credencial
   viva, então nunca copie valor literal dela.

6. **`write` sem `--confirm`** — mostra a prévia, o total que o dia ficaria, e
   gera `<arquivo>-preview.html`. Passe o caminho ao usuário.

7. **Espere aprovação explícita na conversa.** "pode executar", "pode gravar".
   Aprovação de um dia não vale para o próximo.

8. **`write --confirm`** — grava, relê e gera o HTML final (sem o sufixo).

9. **Mande o usuário conferir a planilha.** O link sai no fim do comando. A
   releitura por API é cega para defeito de gravação — foi assim que 15 entradas
   ficaram com "Data inválida" na coluna Hora Final sem nada acusar.

## Preenchimento por proximidade

Depois da leitura, o que sobrar da janela de expediente **não fica em aberto**.
Preencha com a task vizinha e marque `origem: "proximidade"`. A tela dá selo
próprio a esses blocos e soma, por dia, quantos minutos são preenchimento.

Qual é a "mais próxima", em ordem:

1. **A task imediatamente anterior**, na mesma janela livre. Você estava naquilo
   e continuou — é a leitura mais natural de um silêncio.
2. **A seguinte**, quando o buraco abre o dia e não há anterior.
3. **Nenhuma**: se o dia inteiro não tem uma única âncora, não há vizinha. Aí
   sim deixe em aberto e pergunte — preencher seria inventar o dia.

O almoço não é buraco **e não é marcado** — nem na planilha, nem como linha na
lista da tela, nem em resumo no terminal. Buraco que atravessa o almoço se
resolve dentro da própria janela: o da manhã herda a task da manhã, o da tarde a
da tarde. Em 24/09/2026 a lista nova ganhou uma linha "12:00–13:30 · 1h30 ·
almoço" no formato de lançamento, e ela se lia como marcação; foi removida.

**Declare sempre, nos dois lugares.** No terminal, diga quantos minutos foram
preenchidos, com qual task e por quê — e convide o usuário a corrigir: ele é a
única fonte para essas horas. Na tela, o aviso já sai pronto por dia. Um
preenchimento que o usuário não percebeu é um chute, mesmo com o campo certo no
JSON.

Quando o preenchimento for a maior parte do dia, diga isso com todas as letras
em vez de entregar um 8h30 de aparência sólida.

## Front local opcional

```bash
./clickup-time.sh front                      # abre o navegador e fica preso ao terminal
./clickup-time.sh front --plano p.json --fundo   # sobe, imprime a URL, devolve o terminal
./clickup-time.sh front --somente-leitura    # desliga o endpoint de escrita
./clickup-time.sh front --parar              # encerra o que está em segundo plano
```

**Use `--fundo` quando estiver conduzindo pelo chat** — sem ele o servidor prende
o terminal e você não consegue continuar a conversa.

**O front não tem LLM dentro. Você é quem preenche.** A divisão é:

```
agente  ->  roda `sugerir --json`, lê as transcrições, resolve os ???,
            lê as tasks com `tarefas`, escreve o plano e sobe o front com --plano
front   ->  mostra a proposta com a justificativa de cada trecho,
            deixa ajustar, e grava o que o usuário confirmar
usuário ->  confirma
```

O plano é a sua superfície de entrega. Formato:

```json
{"2026-09-02": {
  "blocos": [
    {"start": "08:15", "minutes": 75, "task": "HM-305",
     "origem": "inferencia", "nota": "a sessão discute a correção da 305"}
  ],
  "resumo": {
    "HM-305": {"requisito": "o que a task pede, em uma ou duas frases",
               "feito": "o que foi feito nela neste dia"}
  }
}}
```

A forma antiga, `{"2026-09-02": [blocos]}`, continua aceita — só não tem resumo.

**O plano é validado na subida**, antes de pedir a digital. Bloco sem `nota`,
`origem` desconhecida, duração fora da grade, fora do expediente, cruzando o
almoço ou sobreposto a outro bloco do próprio plano: o front recusa e lista
todos os problemas. Task do plano sem resumo sai como aviso, não recusa.

`origem`, do mais forte para o mais fraco:

| valor | significa | quem sustenta |
|---|---|---|
| `usuario` | ele disse na conversa o que era aquele horário | ele mesmo |
| `ancora` | o script achou a referência | a transcrição |
| `inferencia` | você leu a sessão e deduziu | a transcrição, lida por você |
| `proximidade` | não havia nada ali; fechou com a vizinha | só a memória do usuário |

`usuario` é o caso da daily e das reuniões: não deixam rastro em transcrição
nenhuma, e é ele quem sabe. Vale mais que âncora — não rebaixe para
`inferencia` o que ele afirmou.

A tela dá selo próprio a cada um — **inferência nunca se disfarça de âncora, e
preenchimento nunca se disfarça de leitura**. É por isso que o campo existe.
Bloco sem `nota` é entregar pela metade, em todos os casos: em `proximidade` a
nota diz de quem ele herdou a task e o que havia (ou não havia) no horário.

Com `--plano`, o front **abre já carregado**: o período sai das chaves do plano,
o seletor de data some e a leitura dispara sozinha. Quem já pesquisou não deve
ser obrigado a informar de novo o que pesquisou. O botão vira **Recarregar**,
para buscar o estado atual do ClickUp sem recomeçar.

### Três abas

- **Lista** — o dia inteiro em ordem, numa **tabela**: o que já está no
  ClickUp, as propostas e os buracos. **O almoço não aparece como linha**: a
  lista é de marcações, e almoço não é marcado. No fim, **o que foi feito, por
  dia**: para cada task, nome, status e link (lidos do ClickUp pelo front), horas
  no dia, e o `requisito` e o `feito` do seu resumo — com **Baixar TXT**, que
  salva `daily-DD-MM-AAAA.txt` com task, nome, o que foi feito e o que ela é.
  O nome leva a data do dia resumido, não a de hoje: numa semana, cada dia sai
  com arquivo próprio.
- **Gravar** — um cartão por dia: os lançamentos que vão entrar, prévia, botão
  de gravar e o comando equivalente para o terminal (já com as flags de agenda
  que diferem do padrão, senão o comando copiado de um dia com almoço 13:00–13:30
  rodaria com 12:00–13:30 e seria bloqueado).
- **Resultados** — uma sub-aba com o nome de cada dia gravado nesta sessão do
  front, com a releitura do dia depois da gravação.

No canto superior direito há o botão de **tema claro/escuro**. Sem escolha, a
tela segue o sistema; a escolha vai num cookie (a porta do front muda a cada
subida, e o `localStorage` é por porta), e voltar ao tema do sistema apaga a
escolha. A prévia e o resultado, dentro de iframe, recebem o mesmo tema.

### A lista é por lançamento, em tabela

Colunas: **intervalo, duração, tarefa e o que foi encontrado** — cada coisa no
seu lugar. Até 25/09/2026 era uma grade com as notas penduradas embaixo da
linha, e o usuário achou confuso ler hora editável, task e justificativa
misturadas. Em tela estreita a tabela vira um cartão por linha.

Trechos encostados da mesma task são **uma linha**. Na coluna "o que foi
encontrado" fica a nota de cada trecho, com o selo de origem e o horário, então
juntar não esconde de onde veio cada minuto. A linha só se divide quando há algo
entre os trechos: um lançamento já marcado, o almoço ou um buraco sem proposta.
Até 24/09/2026 a lista era por trecho, e 23/09 aparecia como 11 linhas, três
delas seguidas de HM-423, para 8 lançamentos.

### O que a tela deixa mexer, e o que não

A **task é somente leitura**. O usuário não digita task ali, e isso é decisão de
desenho, não falta: escolher task exige ler transcrição, que é trabalho seu. Se
ele digitasse, você nunca saberia, e o plano e a tela divergiriam em silêncio.

Por linha ele controla:

- **incluir ou não** — caixa de seleção
- **início, fim e duração** — múltiplos de 15min, em todo o expediente, não só
  na janela livre. Início mexe só no início, fim só no fim, duração mexe no fim.
  Encurtar tira minutos da composição; esticar além do que você propôs aparece
  como `ajuste na tela`, sem nota, porque a justificativa é dele.

**Quebrar é permitido, e aponta a culpada.** Se uma alteração faz a linha
invadir o almoço, sobrepor um lançamento do ClickUp ou outra linha marcada, o
aviso aparece **logo abaixo da linha cuja alteração quebrou**, dizendo o que ela
mudou e o que quebrou, com **Desfazer esta alteração**. A gravação do dia trava
(botão, prévia e comando do terminal somem ou ficam inativos) até ajustar ou
desfazer. A culpa é fixada no momento em que a quebra aparece: mexer depois em
outra linha envolvida não rouba a culpa. Desfazer volta a linha para antes da
alteração que quebrou, e leva junto os ajustes feitos nela depois.

**Quem garante é o Python, não a tela.** A conta do navegador só espelha
`validar_candidatos()` para apontar a culpada na hora; o servidor refaz tudo pelo
caminho do `write --confirm` e recusa o dia inteiro se uma entrada quebrar —
expediente, almoço, grade de duração **e de início**, sobreposição com o que já
existe e entre as entradas. A grade do início só passou a ser conferida em
25/09/2026: antes, `08:10 45m` passava.

Buraco sem task aparece como **pendente**, sem caixa de seleção, com o texto
"peça ao agente no terminal". É o caminho certo: resolver `???` volta para você,
não vira digitação na tela.

Cada dia tem **Restaurar proposta**, que devolve tudo ao que você propôs —
inclusão, início e fim. Então o usuário mexe à vontade sem perder o seu trabalho.

### Depois de gravar

O botão do dia **não some**: fica inativo, `✓ Gravado — quarta-feira, 23/09 (8)`,
com a hora da execução e o comando executado logo abaixo, também inativo. As
linhas gravadas passam a aparecer como `gravado agora` na Lista. O que sobrou da
proposta — o que ele desmarcou ou cortou antes de gravar — volta **desmarcado**,
com aviso, para o botão não reaparecer oferecendo justamente o que ele tirou.
Esse registro vive na memória do processo (`/api/gravados`): sobrevive a
recarregar a página, não a reiniciar o front.

O front grava, com dupla confirmação na tela e revalidação no servidor pelo mesmo
caminho do `write --confirm`. Escuta só em `127.0.0.1`, porta efêmera, segredo
aleatório exigido em toda requisição, `Origin` estranha recusada, e `GET` nunca
muta. `--somente-leitura` reduz o front a montar o comando.

Uma troca a declarar ao usuário: o token é lido do Keychain **uma vez na subida**
e fica na memória do processo. Isso troca "uma digital por leitura" por "uma
digital por sessão do front". Suba quando for usar, Ctrl-C ao terminar. O
"Recarregar" relê as fontes, inclusive `gh` e os comentários do ClickUp.

O uso por terminal não muda em nada — o front chama os mesmos módulos.

## Âncoras: como o `sugerir` decide

Três camadas, da mais forte para a mais fraca. Vale da âncora até a próxima
**da mesma sessão, no mesmo dia**:

- `url` — link do ClickUp numa **fala do usuário**
- `fala` — `HM-###` solto numa **fala do usuário**
- `branch` — branch para a qual ele **mudou** (`checkout`, `switch`, `worktree add`)

E duas âncoras de fora das transcrições, que valem **só para o próprio
instante** — não há sessão para herdar, então cada uma decide no máximo o trecho
de 15min em que caiu, e pesa como uma fala do usuário:

- `github` — push, PR (abrir, fechar, mergear), review ou comentário do usuário
  num repo do `irrahgroup` ou do `hubmessage-oficial`. A task sai da branch
  (`HM-445-desliga-canal`, `release/HM-392`) ou do título do PR. Push para
  `main`, `develop` ou `ominizapi` não tem task: conta como atividade, sem âncora.
- `clickup` — comentário ou resposta do usuário numa task. O texto do comentário
  **não** vem junto, de propósito: comentário já trouxe credencial viva.

O horário é o da ação, não o do trabalho: um push às 17:34 diz que ele estava na
HM-445 naquele trecho, não quanto tempo ficou nela antes. Para o resto da janela
vale a mesma leitura e o mesmo preenchimento de sempre.

**Evidência que perdeu a votação não some.** Uma ação só não vence uma sessão
inteira de outra task no mesmo trecho, então o bloco fica com a task da sessão e
leva a ação em `other_evidence` (`at`, `task`, `type`, `excerpt`); no terminal,
uma linha `também:` embaixo. Em 29/09/2026, sete comentários do usuário no
ClickUp caíram todos em trechos já decididos por sessão, e um deles, às 13:53 na
HM-253, era a única menção a essa task no dia. Ao montar o plano, leia esses
casos: se a sessão e a ação forem trabalho paralelo, decida se o trecho se
divide, como `inferencia` e com a ação citada na nota. Não descarte em silêncio.

Texto do assistente e saída de ferramenta não viram âncora: a branch do mind
aparece em todo system-reminder e o `git status` lista dezenas de
`raws/tasks/HM-###/`. Contar isso dá 2289 menções a HM-206 numa sessão sobre
subir a stack.

O campo `age_minutes` diz quanto a âncora é velha. Acima de ~2h, desconfie e
confirme lendo.

## As fontes: todos os agentes instalados

O `sugerir` varre o registro em `clickup_time_transcricao.py:FONTES` e **sempre
reporta o que varreu**, porque "agente não instalado" e "agente sem trabalho
nesse horário" produzem o mesmo zero:

```
fontes varridas
  claude-code    30 arquivos, 2738 eventos      resolução: evento
  codex          46 arquivos, 210 eventos       resolução: evento
  grok           sem atividade no período       resolução: sessão
  opencode       sem atividade no período       resolução: evento
  copilot        sem adaptador                  resolução: —
```

- **resolução `evento`** — cada mensagem tem timestamp próprio; dá para atribuir
  slot a slot.
- **resolução `sessão`** — só há início e fim da sessão. É o caso do Grok, cujo
  `chat_history.jsonl` não carimba mensagem; o adaptador emite um marcador por
  slot, com peso 1, para nunca vencer evidência de nível de evento.
- **`sem adaptador`** — o agente está instalado e não é lido. Se aparecer nessa
  linha e o dia estiver cheio de `???`, é candidato a ser a fonte que falta;
  avise o usuário em vez de concluir que ele não trabalhou.

Além dos agentes, duas fontes de ação do usuário:

```
  github        100 eventos do feed, 28 eventos   resolução: evento
  clickup       9 tasks lidas, 3 eventos          resolução: evento
```

- **`github`** lê `gh api users/<login>/events`, que o GitHub corta em **300
  eventos** (em 29/09/2026, cerca de seis semanas). Quando o período começa antes
  do mais antigo, a linha ganha o aviso `o feed só alcança DD/MM HH:MM` — para
  dias antes disso, falta de evento é falta de dado.
- **`clickup`** não tem um feed de "o que você fez": a API só lista comentários
  por task. As candidatas são as tasks citadas nas outras fontes e nos
  lançamentos do período, mais as atribuídas ao usuário que mudaram desde o
  início dele. **Comentário em task de outra pessoa que nenhuma outra fonte cita
  fica de fora.** Mudança de status não entra: a API não diz quem mudou.
  Estourar o limite de requisições para a leitura e deixa o aviso na linha.

Adicionar um agente = um adaptador `_eventos_<nome>` que devolve
`(eventos, unidades)` (ou `(eventos, unidades, aviso)`) + uma linha em `FONTES`.
Fonte sem pasta para conferir usa `"raiz": None` e `"disponivel"`. Fonte que
quebra é reportada como `falhou: <motivo>` e não derruba as outras.

## Nunca faça

- **`write --confirm` sem aprovação explícita** na conversa, naquela execução.
- **Editar ou apagar lançamento existente.** Toda entrada já na planilha é
  âncora imutável, tenha vindo da UI ou de uma execução anterior. O `PUT` de
  11/09/2026 foi reparo pontual de defeito, não rotina.
- **Preencher `???` sem avisar** que é leitura sua, não âncora.
- **Preencher por proximidade sem dizer**, no terminal e na tela, quanto foi
  preenchido e de onde a task veio. Rotulado e visível é proposta; silencioso é
  chute. Até 10/09/2026 a regra aqui era deixar em aberto; o que mudou foi isso,
  não a proibição de esconder.
- **Inventar task que não apareceu no dia.** A vizinha do buraco, sim; uma task
  que nenhuma sessão daquele dia menciona, nunca.
- Escrever descrição, tag ou billable. O lançamento só associa task, início e
  duração — a explicação fica na conversa.

## Armadilhas conhecidas

- **O POST não grava a Hora Final, nem com `end`.** O `escrever()` faz POST e
  logo em seguida um `PUT` reenviando os mesmos valores (`selar_fim`). Sem isso a
  planilha mostra "Data inválida" naquela coluna. Não remova a segunda chamada
  achando que é redundante: em 11/09/2026 isso quebrou duas vezes, e a segunda
  foi exatamente por eu ter concluído que bastava mandar `end` no POST.
- **A releitura por API não detecta esse defeito.** O `GET` deriva `end` de
  start+duration, então diz "tudo certo" nos dois casos. **Só a tela acusa** —
  por isso o passo 7 do fluxo existe e não é opcional.
- **Task inexistente devolve 401, não 404.** Não é token inválido.
- **Toda task tem custom id**, inclusive as que a UI não mostra: `Daily` é
  `ENGTECH-863`, `Deploy Arkansas` é `HM-379`. Não precisa de link.
- **A Daily é 08:45–09:00, 15min, e o `sugerir` não sabe disso.** Reunião não
  deixa rastro em transcrição nenhuma, então um bloco que comece 08:00 e siga
  adiante passa por cima dela sem avisar. Reserve o horário (`origem: "usuario"`)
  em vez de esperar o usuário reclamar — foi o que aconteceu em 01 e 02/09/2026.
  O horário sai da própria planilha: `read` de alguns dias mostra o padrão.
- **Tela, terminal e planilha falam de lançamento, não de fatia.** Encostados da
  mesma task viram uma linha na tela e um lançamento na planilha. Até 11/09/2026
  não havia fusão nenhuma depois que o agente resolvia os `???`: 02/09 ia como 12
  lançamentos onde 4 bastam. Até 24/09/2026 a planilha já recebia o fundido, mas
  a tela seguia uma linha por trecho — o usuário via HM-423 três vezes seguidas.
  No resumo do terminal, fale igual: `HM-423 09:00–10:45 (âncora 30min,
  proximidade 1h15)`, nunca três linhas.
- **`--fundo` com a saída num pipe perdia a URL.** O pai saía com `os._exit`
  sem esvaziar o buffer. Corrigido em 24/09/2026 com `flush` antes do `fork`; se
  voltar a acontecer, a URL está em `~/.cache/clickup-time/front.url`.
- **A fusão só amplia intervalo, nunca cria buraco**, então todo guard reprova
  mais, nunca menos. O almoço quebra a contiguidade sozinho. E ela é
  determinística, então reexecutar reconhece o que já existe em vez de duplicar.
- **Na segunda o Weekly (1h30) ocupa o lugar da Daily**, não os dois.
- **A meta de 8h30 é conferência, não trava.** Dia parcial grava normalmente.
- **Transcrição some em 30 dias.** Para dias antigos, o `sugerir` pode vir vazio
  por falta de fonte, não por falta de trabalho. O feed do GitHub é ainda mais
  curto quando o mês é movimentado: 300 eventos.
- **O diálogo do `-T ""` não aceitava digital.** Até 29/09/2026 esta skill dizia
  que "toda leitura exige digital"; na prática sempre pediu a senha do chaveiro.
  A digital vem do LocalAuthentication, que o `security` não chama — por isso
  existe o `clickup-token`, e o caminho antigo saiu.
- **Mexer no `clickup_token.swift` obriga todo mundo a redigitar o token.** O
  item confia no hash do binário. Quem mantém a skill roda `digital --compilar`
  (exige o Xcode; as Command Line Tools 27 não ligam a fatia Intel), que regrava
  `bin/clickup-token` e a ficha `.json`; cada usuário instala o novo e regrava o
  token no próximo `./apontar`. A compilação é reproduzível: mesma fonte e mesmo
  Xcode dão o mesmo binário, então dá para conferir o `bin/` recompilando e
  comparando com o `binario_sha256` da ficha. O arquivo de saída precisa se
  chamar `clickup-token`, porque o nome entra na assinatura.

## Arquivos

| Arquivo | Papel |
|---|---|
| `clickup-time.sh` | entrada; resolve symlink e chama o Python |
| `clickup_time.py` | CLI, cliente HTTP, agenda, guardrails, escrita, `tarefas`, comentários do ClickUp |
| `clickup_time_transcricao.py` | extração determinística das transcrições e do feed do GitHub |
| `clickup_time_html.py` | preview HTML autocontido, abre offline |
| `clickup_time_front.py` | front local: validação do plano, as três abas, gravação |
| `clickup_token.swift` | fonte do `clickup-token`: grava e lê o token do Keychain pedindo a digital |
| `bin/clickup-token` | o binário pronto, universal; `bin/clickup-token.json` tem os hashes da fonte e dele |
| `docs/como-funciona.html` | explicação visual da skill, com os fluxos; abre offline |
| `apontar` | entrada: configura a digital se faltar e abre o Claude Code com `/apontar` |
| `commands/apontar.md` | o `/apontar`: o fluxo que o `apontar` dispara; o `.claude/commands` do mind aponta para cá |
| `README.md` | instalação para o time: `gh`, token do ClickUp, digital |

Desenho original: `docs/superpowers/specs/2026-08-31-clickup-time-tracking-design.md`
— com quatro decisões já superadas pelo uso, anotadas no cabeçalho do
`clickup_time.py`.
