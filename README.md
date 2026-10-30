# apontar-horas

Aponta suas horas no ClickUp a partir do que você fez no dia: as conversas com o
Claude Code (e com Codex, Grok e OpenCode, se você usa), seus pushes e PRs no
GitHub e seus comentários no ClickUp. Você confere numa tela e grava.

**Nada vai para o ClickUp sem você confirmar.**

## Instalação

Você precisa de:

- Mac com macOS 12 ou mais novo
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) instalado
- Conta no workspace **Irrah Tech** do ClickUp

### 1. Instale a skill

Copie e cole no Terminal:

```bash
git clone "https://github.com/yanvidal-code/apontar-horas.git" ~/.claude/skills/apontar-horas
mkdir -p ~/.claude/commands
ln -sf ~/.claude/skills/apontar-horas/commands/apontar.md ~/.claude/commands/apontar.md
echo "alias apontar='$HOME/.claude/skills/apontar-horas/apontar'" >> ~/.zshrc
source ~/.zshrc
```

Se o Mac pedir para instalar as *ferramentas de desenvolvedor de linha de
comando*, aceite, espere terminar e cole o bloco de novo.

### 2. Copie seu token do ClickUp

1. No ClickUp, clique na sua foto (canto superior direito) → **Settings**.
2. No menu da esquerda, clique em **Apps**.
3. Em **API Token**, clique em **Generate**. Se já tiver um, clique em **Copy**.

O token começa com `pk_`. Você vai colar no Terminal, no próximo passo. Não
cole em nenhum outro lugar: nem no chat do Claude, nem no Slack, nem num
arquivo.

### 3. Rode pela primeira vez

```bash
apontar ontem
```

Na primeira vez, antes de abrir o Claude Code, o Terminal pede o token:

```text
digital do ClickUp: o clickup-token não está instalado. Configurando agora.
Token em: ClickUp → avatar → Settings → Apps → API Token (começa com pk_).
clickup-token instalado.
Token do ClickUp (não aparece ao digitar):
```

Cole o token (⌘V) e tecle Enter. Não aparece nada enquanto você cola, e isso é
normal. Ele responde `gravado em clickup-irrah-tech` e abre o Claude Code.

No Claude Code:

- Ele pergunta se você confia na pasta. Responda que sim.
- Ele pede permissão para rodar o `./clickup-time.sh`. Aprove. As leituras não
  mudam nada no ClickUp, e a gravação só acontece quando você mandar.
- O Mac pede a digital (Touch ID) para ler o token. Sem Touch ID, pede a senha
  do Mac.

Pronto. A partir daí é só rodar `apontar`.

### 4. Ligue o GitHub (opcional, recomendado)

Com o GitHub ligado, a skill também usa seus pushes, PRs, reviews e comentários
nos repos da `irrahgroup` e da `hubmessage-oficial` para saber em que task você
estava. Sem ele funciona só com as conversas e o ClickUp, e o `apontar` avisa
disso toda vez.

Precisa do [Homebrew](https://brew.sh). Se ainda não tem, instale pelo comando
da página dele. Depois:

```bash
brew install gh
gh auth login
```

No `gh auth login`, escolha **GitHub.com** → **HTTPS** → **Login with a web
browser**. Nas outras perguntas, tecle Enter. Copie o código que aparece e cole
na página que abre no navegador.

Para conferir, rode o comando abaixo. Ele tem que listar `irrahgroup`:

```bash
gh api user/orgs --jq '.[].login'
```

## Uso

```bash
apontar                          # semana corrente
apontar ontem
apontar "semana passada"
apontar 2026-10-27 a 2026-10-29
```

O que acontece:

1. O agente lê o período e diz quais fontes encontrou.
2. Propõe os lançamentos de cada dia e diz de onde veio cada trecho: você
   disse, ele achou uma referência (link ou `HM-###` na conversa, branch, PR),
   ele deduziu lendo a conversa, ou ele repetiu a task vizinha porque não havia
   nada no horário.
3. Abre uma tela no navegador e te passa o link. A tela tem três abas:
   - **Lista**: o dia inteiro, com o resumo do que foi feito em cada task e um
     botão **Baixar TXT** para a daily;
   - **Gravar**: confere e grava, um dia de cada vez;
   - **Resultados**: como o dia ficou depois de gravar.
4. Na tela, você ajusta início, fim e duração, tira o que não quer e grava. Para
   trocar a task de um trecho, peça ao agente no terminal.

Dicas:

- **Seu dia foi diferente do padrão?** O padrão é 08:00–18:00, com almoço de
  12:00 a 13:30. Diga ao agente: "almocei 13h–14h", "entrei 9h".
- **Reunião não deixa rastro.** Diga ao agente: "reunião 14h–15h na HM-123".
- **Dá para gravar sem a tela.** Peça no terminal: ele mostra a prévia e só
  grava depois do seu "pode gravar".
- **Depois de gravar**, abra a planilha de horas do ClickUp e confira a coluna
  **Hora Final**.
- **Aponte dentro do mês.** O Claude Code apaga as conversas com mais de 30
  dias. Para guardar mais tempo, ponha `"cleanupPeriodDays": 90` no
  `~/.claude/settings.json`.
- **A tela continua rodando** depois que você termina. Para fechar:
  `~/.claude/skills/apontar-horas/clickup-time.sh front --parar`

## Se algo der errado

| o que aparece | o que fazer |
|---|---|
| `command not found: apontar` | abra um Terminal novo, ou rode `source ~/.zshrc` |
| o agente diz que não conseguiu ler o token | saia do Claude Code e rode `apontar` no Terminal |
| `digital recusada ou cancelada` | rode de novo e confirme a digital |
| `a skill trouxe um clickup-token novo` | normal depois de atualizar: rode `apontar` e cole o token de novo |
| `aviso: sem o gh` ou `o gh está sem login` | o GitHub está desligado; veja o passo 4 |
| você gerou um token novo no ClickUp | `~/.claude/skills/apontar-horas/clickup-time.sh digital` e cole o novo |

## Atualizar

```bash
git -C ~/.claude/skills/apontar-horas pull
```

## Desinstalar

```bash
security delete-generic-password -s clickup-irrah-tech
rm -rf "$HOME/Library/Application Support/clickup-time"
rm ~/.claude/commands/apontar.md
rm -rf ~/.claude/skills/apontar-horas
```

Depois, apague a linha `alias apontar=...` do `~/.zshrc`.

## Como o token fica guardado

O token fica no Keychain do Mac e só sai de lá com a sua digital. Ele não passa
por arquivo, variável de ambiente nem pelo agente.

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

- **O `clickup-token`** é um programa pequeno em Swift
  ([`clickup_token.swift`](clickup_token.swift)), que vem pronto em `bin/`. Ele
  existe porque o `security` do macOS não chama o Touch ID: o diálogo dele só
  aceita a senha do chaveiro.
- **Ao gravar**, ele apaga o item anterior e cria o item `clickup-irrah-tech`,
  que só ele consegue ler. Qualquer outro programa, inclusive o `security`, cai
  no diálogo de senha do macOS.
- **Ao ler**, ele pede a digital antes de tocar no item.
- **A gravação do token só roda num Terminal de verdade.** Ela recusa pipe e
  recusa o `!` de dentro do Claude Code, e é por isso que o token nunca chega ao
  agente.
- **A tela** lê o token uma vez quando abre e o mantém só na memória dela. Isso
  dá uma digital por sessão da tela, em vez de uma por leitura.

## Para quem mantém a skill

- O procedimento que o agente segue está no [`SKILL.md`](SKILL.md) e no
  [`commands/apontar.md`](commands/apontar.md). A explicação visual, com os
  fluxos, está em [`docs/como-funciona.html`](docs/como-funciona.html), que abre
  offline.
- Valores fixos no código:
  - o workspace Irrah Tech (`WORKSPACE_ID` em `clickup_time.py`);
  - o fuso `America/Fortaleza` (a flag `--timezone` troca);
  - as orgs do GitHub (`GITHUB_DONOS` em `clickup_time_transcricao.py`).
- **Mudar o `clickup_token.swift` obriga todo mundo a gravar o token de novo.** O
  binário novo tem outro hash, e o item do Keychain confia no hash. Gere com:

  ```bash
  ./clickup-time.sh digital --compilar   # exige o Xcode; as Command Line Tools não geram a versão Intel
  ```

  Isso regrava `bin/clickup-token` (universal) e `bin/clickup-token.json`, que
  guarda os hashes da fonte e do binário e a versão do compilador.
- **Qualquer pessoa pode conferir o binário.** A compilação é reproduzível: com
  a mesma fonte e o mesmo Xcode da ficha (`compilador` em
  `bin/clickup-token.json`), o `--compilar` gera o mesmo binário, e o
  `git status bin/clickup-token` não acusa mudança.
