---
description: Apontar horas no ClickUp a partir das transcrições, com front local para conferir e gravar
argument-hint: [período, ex "ontem", "semana passada", "2026-09-01 a 2026-09-04"]
---

Carregue a skill `apontar-horas` e execute o fluxo completo para: **$ARGUMENTS**

Se o período acima estiver vazio, use a semana corrente (domingo até hoje).

Faça, em ordem, sem pedir confirmação entre os passos de leitura:

1. **Resolva o período** para datas ISO. Interprete "ontem", "semana passada",
   "essa semana" no fuso `America/Fortaleza`. Diga qual intervalo entendeu.

2. **`./clickup-time.sh sugerir --from X --to Y --json`**. Isso só lê. Pede a
   digital uma vez. Se falhar no token, pare e peça ao usuário para rodar, num
   terminal dele fora do Claude Code, o comando que a mensagem de erro mostra (o
   `apontar`, que configura a digital antes de abrir o Claude Code) — o token
   nunca passa por você.

3. **Relate as fontes varridas** antes de qualquer proposta: os agentes, o
   `github` (push, PR, review) e o `clickup` (comentários do usuário). Se alguma
   aparecer como `sem adaptador`, `não instalado` ou `falhou`, ou com `aviso`
   (o feed do GitHub só alcança 300 eventos), e o dia estiver cheio de `???`,
   diga isso — pode ser fonte faltando, não dia sem trabalho.

4. **Resolva os `???`** lendo as transcrições daquele horário. Consolide as
   fatias de 15min de sessões paralelas. Leia também os blocos com
   `other_evidence`: ação do usuário (GitHub, comentário no ClickUp) em outra
   task, que perdeu a votação para a sessão do trecho. Se for trabalho paralelo,
   decida se o trecho se divide e cite a ação na `nota`. Para cada bloco que você resolver por
   leitura, marque `"origem": "inferencia"` e escreva a `nota` com a evidência
   concreta — a frase da conversa, o PR, o arquivo. Sem nota, não proponha.
   Os 15min são a unidade da marcação, não da apresentação: não relate nem
   pense em voz alta de 15 em 15.

5. **Feche o dia com a task mais próxima.** O que a leitura não resolveu recebe
   a vizinha — a anterior na mesma janela livre, ou a seguinte quando o buraco
   abre o dia — com `"origem": "proximidade"` e `nota` dizendo de quem herdou e
   o que havia no horário. Sem nenhuma âncora no dia inteiro, não há vizinha:
   aí deixe em aberto e pergunte. O almoço não é buraco.

6. **Resuma cada task.** `./clickup-time.sh tarefas <tasks do plano> --json`
   (só lê; pede a digital). Para cada dia e task, escreva o `requisito` — o que
   a task pede, em uma ou duas frases, a partir da descrição — e o `feito` — o
   que foi feito nela naquele dia, a partir das transcrições e PRs. Com as suas
   palavras: nunca copie valor literal da descrição.

7. **Escreva o plano** em `/tmp/apontar-<data>.json`, no formato:
   `{"AAAA-MM-DD": {"blocos": [{"start","minutes","task","origem","nota"}],
   "resumo": {"HM-123": {"requisito","feito"}}}}`. Um bloco por trecho de origem
   distinta; o front junta os encostados da mesma task numa linha só.

8. **Suba o front em segundo plano**, passando as mesmas flags de agenda do
   `sugerir` (almoço, expediente):
   `./clickup-time.sh front --plano /tmp/apontar-<data>.json --fundo [--lunch-start ...]`
   Se ele recusar o plano, corrija o que a lista apontar e suba de novo.

9. **Informe a URL ao usuário** e resuma no terminal, por dia e **por
   lançamento** (trechos encostados da mesma task numa linha, com a composição
   por origem): quanto já estava apontado, quanto você propôs, quais propostas
   são inferência sua em vez de âncora do script, e **quanto foi preenchido por
   proximidade, com qual task**. Diga que essa última parte não tem evidência
   nenhuma e peça que ele relate se foi diferente — para essas horas ele é a
   única fonte. Se o preenchimento for a maior parte do dia, diga isso em vez de
   entregar um 8h30 de aparência sólida.

Depois disso **fique no terminal** e continue a conversa. O usuário decide se
confere na tela ou segue por aqui. A tela tem três abas — Lista (tabela com
intervalo, duração, tarefa e o que foi encontrado; o resumo das tasks no fim,
com "Baixar TXT" da daily), Gravar e Resultados (uma aba por dia gravado). Ele
pode editar início, fim e duração na tela; a alteração que quebrar o horário
ganha aviso e "desfazer" e trava a gravação. "Restaurar proposta" volta ao que
você sugeriu.

**Não grave.** Nem por `write --confirm`, nem pelo front. A gravação é do
usuário — pela tela, ou pedindo explicitamente aqui. Se ele pedir por aqui,
rode `write` sem `--confirm` primeiro e espere o "pode gravar".

Ao terminar, lembre que `./clickup-time.sh front --parar` encerra o servidor.
