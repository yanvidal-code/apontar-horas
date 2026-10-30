# apontar-horas

Skill do Claude Code que preenche a planilha de horas do ClickUp a partir do que
você fez no dia: as conversas com agentes (Claude Code, Codex, Grok, OpenCode),
os pushes, PRs e reviews no GitHub, e os seus comentários no ClickUp.

```bash
apontar                      # semana corrente
apontar ontem
apontar "semana passada"
apontar 2026-09-01 a 2026-09-04
```

O agente lê tudo, propõe os lançamentos de cada dia com a justificativa de cada
trecho, e abre uma tela local para você conferir, ajustar e gravar. **Nada é
gravado no ClickUp sem a sua confirmação.**

O token do ClickUp fica no Keychain do macOS e só sai de lá com a sua digital.
Ele nunca passa pelo chat nem pelo agente.

## Requisitos

- macOS 12 ou mais novo (Apple Silicon ou Intel)
- [Homebrew](https://brew.sh): traz junto as Command Line Tools e, com elas, o
  `python3` (3.9 ou mais novo, só a biblioteca padrão)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) instalado, com o
  `claude` no PATH
- Conta no workspace **Irrah Tech** do ClickUp
- Acesso à org `irrahgroup` no GitHub

Não precisa de Xcode: o programa que lê o token com a digital vem pronto em `bin/`.

## Instalação

### 1. GitHub CLI

O `gh` serve para clonar este repositório e é a fonte GitHub da skill: pushes,
PRs, reviews e comentários seus nos repos da `irrahgroup` e da
`hubmessage-oficial`.

```bash
brew install gh
gh auth login
```

No `gh auth login`, responda: **GitHub.com** → **HTTPS** → **Login with a web
browser**. Ele mostra um código, abre o navegador e você cola o código lá.

Confira:

```bash
gh auth status                       # escopos: precisa ter repo e read:org
gh api user/orgs --jq '.[].login'    # tem que listar irrahgroup
```

Se `irrahgroup` não aparecer, peça acesso à org antes de seguir.

### 2. A skill

```bash
gh repo clone yanvidal-code/apontar-horas ~/.claude/skills/apontar-horas

mkdir -p ~/.claude/commands
ln -s ~/.claude/skills/apontar-horas/commands/apontar.md ~/.claude/commands/apontar.md

echo "alias apontar='$HOME/.claude/skills/apontar-horas/apontar'" >> ~/.zshrc
source ~/.zshrc
```

- `~/.claude/skills/apontar-horas` deixa a skill disponível em qualquer sessão
  do Claude Code.
- O link em `~/.claude/commands` cria o comando `/apontar`, que conduz o fluxo
  completo.
- O alias cria o comando `apontar` no terminal.

### 3. Token do ClickUp

1. No ClickUp, clique no seu avatar (canto superior direito) → **Settings**.
2. No menu lateral, **Apps**.
3. Em **API Token**, clique em **Generate**. Se já existir um, **Copy**.
4. O token começa com `pk_`. **Não cole em lugar nenhum além do terminal no
   passo 4**: nem no chat do agente, nem no Slack, nem num arquivo.

O token é pessoal: os lançamentos ficam no seu nome, e a skill lê só os seus
lançamentos e os seus comentários.

### 4. Primeira execução: o token vai para a digital

```bash
apontar ontem
```

Na primeira vez, antes de abrir o Claude Code, o `apontar` percebe que falta a
configuração e faz ali mesmo:

```text
digital do ClickUp: o clickup-token não está instalado. Configurando agora.
Token em: ClickUp → avatar → Settings → Apps → API Token (começa com pk_).
clickup-token instalado.
Token do ClickUp (não aparece ao digitar):
gravado em `clickup-irrah-tech`. A próxima leitura pede a digital.
```

Cole o token quando ele pedir (não aparece nada enquanto você cola) e tecle
Enter. Em seguida o Claude Code abre, e a primeira leitura do ClickUp pede a
digital.

Na primeira vez, o Claude Code também pergunta se você confia na pasta
`~/.claude/skills/apontar-horas`: responda que sim. Ele pede permissão para
rodar o `./clickup-time.sh`. As leituras (`sugerir`, `read`, `tarefas`, `front`)
podem ser liberadas. A gravação passa sempre por você.

## Como o token fica guardado

```text
apontar
  └─ clickup-time.sh digital --conferir      só confere, não pede nada
       ├─ falta algo → instala bin/clickup-token em
       │                ~/Library/Application Support/clickup-time/
       │              → clickup-token gravar  (pede o token sem eco)
       └─ tudo certo → segue

cada leitura do ClickUp
  └─ clickup-token ler  → digital (Touch ID) → token só no header da requisição
```

- **`clickup-token`** é um programa pequeno em Swift (`clickup_token.swift`).
  Ele existe porque o `security` do macOS não chama o Touch ID: o diálogo dele
  só aceita a senha do chaveiro.
- **Gravar** apaga o item anterior e cria um item `clickup-irrah-tech` no
  Keychain que confia só no `clickup-token`. Qualquer outro programa, inclusive
  o `security`, cai no diálogo de senha do macOS.
- **Ler** pede a digital antes de tocar no item. Sem sensor (tampa fechada,
  teclado sem Touch ID), o mesmo diálogo aceita a senha do Mac.
- **O token não passa por arquivo, variável de ambiente nem pelo agente.** O
  `digital` recusa rodar sem um terminal de verdade. Se o agente disser que não
  conseguiu ler o token, rode `apontar` você mesmo, num terminal seu.
- **A tela local** lê o token uma vez quando sobe e o mantém só na memória dela:
  uma digital por sessão da tela, em vez de uma por leitura. Encerre com
  `~/.claude/skills/apontar-horas/clickup-time.sh front --parar` quando terminar.

Para trocar o token, por exemplo depois de regenerar no ClickUp:

```bash
~/.claude/skills/apontar-horas/clickup-time.sh digital
```

Para ver o que falta, sem pedir nada:

```bash
~/.claude/skills/apontar-horas/clickup-time.sh digital --conferir
```

| mensagem | o que fazer |
|---|---|
| `o clickup-token não está instalado` | `apontar` (ou `clickup-time.sh digital`) |
| `a skill trouxe um clickup-token novo` | o mesmo: depois de um `git pull` que trocou o binário, o item antigo deixa de confiar nele e o token precisa ser regravado |
| `o token não está no Keychain` | o mesmo |
| `o token está num item antigo` | o mesmo |
| `digital recusada ou cancelada` | rodar de novo e confirmar a digital |
| `o clickup-token não veio com a skill` | falta `bin/clickup-token` no clone: avise quem mantém a skill |

## Uso

`apontar` abre o Claude Code com o `/apontar`, que:

1. resolve o período pedido;
2. lê as transcrições, o GitHub e o ClickUp, e diz quais fontes encontrou;
3. propõe os lançamentos de cada dia, marcando de onde veio cada trecho:

   | origem | significa |
   |---|---|
   | `usuario` | você disse na conversa |
   | `ancora` | o script achou a referência (link ou `HM-###` numa fala sua, troca de branch, push, PR, comentário) |
   | `inferencia` | o agente leu a conversa e deduziu |
   | `proximidade` | não havia nada no horário; ele repetiu a task vizinha |

4. abre a tela local e te passa a URL. Ela tem três abas: **Lista** (o dia
   inteiro, com o resumo do que foi feito em cada task e o botão "Baixar TXT"
   para a daily), **Gravar** e **Resultados**.

Na tela você inclui ou tira lançamentos e ajusta início, fim e duração. Se
quiser outra task, peça ao agente no terminal: a escolha da task depende de ler
as conversas, que é trabalho dele. Também dá para gravar pelo terminal: peça, ele
mostra a prévia e só grava depois do seu "pode gravar".

Depois de gravar, **abra a planilha de horas no ClickUp e confira a coluna Hora
Final**. Um defeito de gravação nessa coluna já passou sem a API acusar, e só a
tela do ClickUp mostra.

### O seu dia não é o padrão

O padrão é expediente 08:00–18:00, almoço 12:00–13:30, blocos de 15 minutos e
meta de 8h30. Não há arquivo de configuração: diga ao agente na hora, por
exemplo "almocei 13h–14h", "entrei 9h e fiquei até 19h".

Reunião não deixa rastro em conversa nenhuma. Diga ao agente: "reunião
14h–15h na HM-123". O que você afirma vale mais que qualquer âncora.

### Limites que vale saber

- **O Claude Code apaga as transcrições com mais de 30 dias.** Aponte dentro do
  mês, ou aumente o prazo em `~/.claude/settings.json`:
  `"cleanupPeriodDays": 90`.
- **O feed do GitHub guarda só os últimos 300 eventos.** Num mês movimentado,
  isso dá umas seis semanas. Quando o período começa antes disso, a skill avisa.
- **Comentário no ClickUp em task de outra pessoa** só entra se a task aparecer
  em outra fonte do mesmo período.
- **Preenchimento por proximidade não tem evidência.** O agente diz quanto do dia
  foi preenchido assim. Corrija se não foi isso.

## Atualizar

```bash
git -C ~/.claude/skills/apontar-horas pull
```

Se a atualização trouxe um `clickup-token` novo, o próximo `apontar` reinstala e
pede o token outra vez.

## Desinstalar

```bash
security delete-generic-password -s clickup-irrah-tech
rm -rf "$HOME/Library/Application Support/clickup-time"
rm ~/.claude/commands/apontar.md
rm -rf ~/.claude/skills/apontar-horas
```

E apague a linha do `alias apontar` no `~/.zshrc`.

## Para quem mantém a skill

- O procedimento que o agente segue está no [`SKILL.md`](SKILL.md) e no
  [`commands/apontar.md`](commands/apontar.md). A explicação visual, com os
  fluxos, está em [`docs/como-funciona.html`](docs/como-funciona.html), que abre
  offline.
- Valores fixos no código: workspace Irrah Tech (`WORKSPACE_ID` em
  `clickup_time.py`), fuso `America/Fortaleza` (a flag `--timezone` troca), orgs
  do GitHub (`GITHUB_DONOS` em `clickup_time_transcricao.py`).
- **Mudar o `clickup_token.swift` obriga todo mundo a regravar o token.** O
  binário novo tem outro hash, e o item do Keychain confia no hash. Gere com:

  ```bash
  ./clickup-time.sh digital --compilar   # exige o Xcode; as Command Line Tools não ligam a fatia Intel
  ```

  Isso regrava `bin/clickup-token` (universal) e `bin/clickup-token.json`, com os
  hashes da fonte e do binário e a versão do compilador.
- **Qualquer pessoa pode conferir o binário.** A compilação é reproduzível: com
  a mesma fonte e o mesmo Xcode da ficha (`compilador` em
  `bin/clickup-token.json`), o `--compilar` gera o mesmo binário, e o
  `git status bin/clickup-token` não acusa mudança.
