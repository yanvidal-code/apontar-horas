#!/usr/bin/env python3
"""clickup_time_transcricao.py — sugere blocos a partir das transcrições.

Determinístico: mesmas transcrições + mesmo estado do ClickUp produzem a mesma
saída, byte a byte. Sem modelo no meio, sem heurística que dependa de leitura
de linguagem. O que não dá para decidir por regra sai como `???`, não como
chute — a atribuição errada num apontamento de hora é dado errado em sistema
de RH, não bug de script.

Fontes: as transcrições dos agentes (`FONTES`) e o feed de atividade do GitHub.
Os comentários do ClickUp entram por `clickup_time.py`, que tem o token.

Âncora é o que diz "a partir daqui o trabalho é da task X", em três níveis de
confiança, nesta ordem:

  1. URL do ClickUp numa fala do usuário      → `url`     (a mais forte)
  2. `HM-123`/`ENGTECH-45` solto numa fala     → `fala`
  3. nome de branch em contexto git            → `branch`  (checkout, origin/, --head)

Fora das transcrições, dois tipos de evento externo já chegam com a task, e cada
um vale só para o próprio instante (não há sessão para herdar):

  - push, PR, review ou comentário seu no GitHub → `github`
  - comentário seu numa task do ClickUp          → `clickup`

Texto do assistente e saída de ferramenta crua NÃO viram âncora: o nome da
branch do mind aparece em todo system-reminder e `git status` lista dezenas de
`raws/tasks/HM-###/`. Contar isso dá 2289 menções a HM-206 numa sessão sobre
subir a stack.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from datetime import date as Date
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TASK_REF = r"[A-Z]{2,10}-\d{2,5}"

# Âncoras, da mais forte para a mais fraca.
RE_URL = re.compile(rf"clickup\.com/t/\d+/({TASK_REF})", re.I)
RE_FALA = re.compile(rf"\b({TASK_REF})\b(?!-)", re.I)
# Só a branch para a qual você MUDOU, nunca listagem. Um `git branch -r` despeja
# dezenas de branches de outras pessoas: a primeira versão desta regra sugeriu
# `DA-5708` e `DA-5816`, do Conway, que nunca foram trabalho seu.
RE_BRANCH = re.compile(
    r"(?:"
    r"Switched to (?:a new )?branch '|"
    r"git (?:-C \S+ )?(?:checkout|switch) (?:-b )?|"
    r"worktree add \S+ |"
    r'"head_ref"\s*:\s*"|'
    r"--head "
    rf")({TASK_REF})"
)

# Blocos de texto que não são fala do usuário, mesmo vindo no papel de user.
RUIDO = re.compile(
    r"<(command-name|command-message|local-command-stdout|system-reminder|"
    r"local-command-caveat|command-args|environment_context|task-notification)>"
)

# `externo` é ação sua fora do agente (GitHub, ClickUp): pesa como uma fala sua.
# Um evento só não vence uma sessão inteira de outra task no mesmo trecho, mas
# decide o trecho em que nenhum agente estava aberto.
PESO = {"user": 12, "externo": 12, "assistant": 3, "tool": 2, "out": 1, "sessao": 1}


class FonteIndisponivel(Exception):
    """A fonte existe mas não pôde ser lida; a mensagem vai para o relatório."""


# ------------------------------------------------------------------- leitura


def _texto(conteudo) -> str:
    if isinstance(conteudo, str):
        return conteudo
    if not isinstance(conteudo, list):
        return ""
    partes = []
    for b in conteudo:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t in ("text", "input_text", "output_text"):
            partes.append(b.get("text", ""))
        elif t == "tool_use":
            partes.append(json.dumps(b.get("input", {}), ensure_ascii=False)[:1500])
        elif t == "tool_result":
            c = b.get("content")
            if isinstance(c, str):
                partes.append(c[:1500])
            elif isinstance(c, list):
                partes.append(" ".join(x.get("text", "") for x in c if isinstance(x, dict))[:1500])
    return " ".join(partes)


def _local(ts, tz):
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz)
    except ValueError:
        return None


def _eventos_claude(inicio: Date, fim: Date, tz: ZoneInfo) -> tuple[list, int]:
    eventos, arquivos = [], 0
    for caminho in sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))):
        arquivos += 1
        try:
            fh = open(caminho, errors="ignore")
        except OSError:
            continue
        with fh:
            for linha in fh:
                if '"timestamp"' not in linha:
                    continue
                try:
                    d = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                dt = _local(d.get("timestamp"), tz)
                if not dt or not (inicio <= dt.date() <= fim):
                    continue
                if d.get("type") not in ("user", "assistant"):
                    continue
                txt = _texto((d.get("message") or {}).get("content"))
                if not txt:
                    continue
                if d["type"] == "user":
                    kind = "out" if '"tool_use_id"' in linha else "user"
                    if kind == "user" and RUIDO.search(txt):
                        continue
                else:
                    kind = "tool" if '"tool_use"' in linha else "assistant"
                eventos.append({"dt": dt, "sessao": os.path.basename(caminho),
                                "kind": kind, "txt": txt[:1500], "fonte": "claude-code"})
    return eventos, arquivos


def _eventos_codex(inicio: Date, fim: Date, tz: ZoneInfo) -> tuple[list, int]:
    eventos, arquivos = [], 0
    for caminho in sorted(glob.glob(os.path.expanduser("~/.codex/sessions/**/*.jsonl"),
                                    recursive=True)):
        if "/.tmp/" in caminho or "session_index" in caminho or caminho.endswith("history.jsonl"):
            continue
        arquivos += 1
        try:
            fh = open(caminho, errors="ignore")
        except OSError:
            continue
        with fh:
            for linha in fh:
                try:
                    d = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                dt = _local(d.get("timestamp"), tz)
                if not dt or not (inicio <= dt.date() <= fim):
                    continue
                pl = d.get("payload") or {}
                papel, ptipo = pl.get("role"), pl.get("type")
                if papel in ("user", "assistant"):
                    txt, kind = _texto(pl.get("content")), papel
                    if kind == "user" and (RUIDO.search(txt or "") or txt.strip().startswith("<")):
                        continue
                elif ptipo == "function_call":
                    txt, kind = str(pl.get("arguments", ""))[:1500], "tool"
                elif ptipo == "function_call_output":
                    txt, kind = str(pl.get("output", ""))[:1500], "out"
                else:
                    continue
                if not txt:
                    continue
                eventos.append({"dt": dt, "sessao": os.path.basename(caminho),
                                "kind": kind, "txt": txt[:1500], "fonte": "codex"})
    return eventos, arquivos


def _eventos_grok(inicio: Date, fim: Date, tz: ZoneInfo) -> tuple[list, int]:
    """Resolução de SESSÃO, não de evento.

    O `chat_history.jsonl` do Grok não tem timestamp por mensagem — só o
    `summary.json` tem `created_at`/`updated_at` da sessão inteira. Então o que
    dá para afirmar é "esta sessão esteve aberta neste intervalo", e é isso que
    vira evento: um marcador por slot, com peso baixo, para nunca vencer
    evidência de nível de evento.
    """
    eventos, sessoes = [], 0
    for pasta in sorted(glob.glob(os.path.expanduser("~/.grok/sessions/*/*/"))):
        resumo = os.path.join(pasta, "summary.json")
        historico = os.path.join(pasta, "chat_history.jsonl")
        if not (os.path.exists(resumo) and os.path.exists(historico)):
            continue
        try:
            with open(resumo) as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        abriu = _local(meta.get("created_at"), tz)
        fechou = _local(meta.get("updated_at"), tz) or abriu
        if not abriu or not (inicio <= abriu.date() <= fim):
            continue
        sessoes += 1

        falas = []
        try:
            with open(historico, errors="ignore") as fh:
                for linha in fh:
                    try:
                        d = json.loads(linha)
                    except json.JSONDecodeError:
                        continue
                    if d.get("type") == "user":
                        falas.append(_texto(d.get("content")))
        except OSError:
            pass

        nome = os.path.basename(pasta.rstrip("/"))
        t, primeiro = abriu, True
        while t <= fechou:
            eventos.append({
                "dt": t, "sessao": f"grok:{nome}",
                "kind": "user" if primeiro else "sessao",
                "txt": (" ".join(falas)[:1500] if primeiro else ""),
                "fonte": "grok",
            })
            primeiro = False
            t += timedelta(minutes=15)
    return eventos, sessoes


def _eventos_opencode(inicio: Date, fim: Date, tz: ZoneInfo) -> tuple[list, int]:
    """opencode guarda em SQLite, não em JSONL. Abre somente-leitura."""
    banco = os.path.expanduser("~/.local/share/opencode/opencode.db")
    if not os.path.exists(banco):
        return [], 0
    import sqlite3

    eventos = []
    try:
        con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return [], 0
    try:
        linhas = con.execute(
            "select session_id, time_created, data from message order by time_created"
        ).fetchall()
    except sqlite3.Error:
        return [], 0
    finally:
        con.close()

    for sessao, criado, dados in linhas:
        if not criado:
            continue
        dt = datetime.fromtimestamp(int(criado) / 1000, tz)
        if not (inicio <= dt.date() <= fim):
            continue
        try:
            d = json.loads(dados) if isinstance(dados, str) else {}
        except json.JSONDecodeError:
            d = {}
        papel = d.get("role")
        kind = {"user": "user", "assistant": "assistant"}.get(papel)
        if not kind:
            continue
        eventos.append({"dt": dt, "sessao": f"opencode:{sessao}", "kind": kind,
                        "txt": _texto(d.get("parts") or d.get("content"))[:1500],
                        "fonte": "opencode"})
    return eventos, len(linhas)


# -------------------------------------------------------------------- GitHub

# Donos cujos repositórios contam como trabalho. Push em repo pessoal não é hora
# da Irrah, e evento sem task conta como atividade: sem o filtro, ele trocaria
# `sem_atividade` por `sem_ancora` num horário que não era de trabalho.
GITHUB_DONOS = ("irrahgroup", "hubmessage-oficial")

# Task no nome da branch: `HM-445-desliga-canal`, `release/HM-392`. Aqui o `-`
# depois do número é o esperado; o `(?!-)` do RE_FALA existe justamente para que
# nome de branch citado na conversa não vire fala.
RE_TASK_BRANCH = re.compile(rf"(?:^|/)({TASK_REF})(?![0-9])", re.I)
RE_TASK_TITULO = re.compile(rf"\b({TASK_REF})\b", re.I)

ACAO_PR = {"opened": "abriu", "closed": "fechou", "merged": "mergeou", "reopened": "reabriu"}


def _gh(caminho: str) -> object:
    try:
        r = subprocess.run(["gh", "api", caminho], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise FonteIndisponivel("gh não respondeu em 30s") from None
    if r.returncode != 0:
        detalhe = (r.stderr or "").strip().splitlines()
        raise FonteIndisponivel("gh falhou" + (f": {detalhe[0][:120]}" if detalhe else ""))
    return json.loads(r.stdout)


def _descrever_github(ev: dict) -> tuple[str, str | None] | None:
    """(o que foi feito, task) de um evento do feed; None para o que não é trabalho."""
    tipo, p = ev.get("type"), ev.get("payload") or {}
    repo = (ev.get("repo") or {}).get("name", "").split("/", 1)[-1]
    pr = p.get("pull_request") or {}
    ramo = (pr.get("head") or {}).get("ref") or ""
    numero = p.get("number") or pr.get("number") or (p.get("issue") or {}).get("number")

    if tipo == "PushEvent":
        ramo = (p.get("ref") or "").removeprefix("refs/heads/")
        texto = f"push em {repo} ({ramo})"
    elif tipo == "CreateEvent":
        ramo = p.get("ref") or ""
        texto = f"criou {p.get('ref_type') or 'ref'} {ramo} em {repo}"
    elif tipo == "PullRequestEvent":
        acao = ACAO_PR.get(p.get("action"), p.get("action") or "mexeu no")
        texto = f"{acao} o PR #{numero} de {repo} ({ramo})"
    elif tipo == "PullRequestReviewEvent":
        texto = f"review no PR #{numero} de {repo} ({ramo})"
    elif tipo == "PullRequestReviewCommentEvent":
        texto = f"comentário de review no PR #{numero} de {repo} ({ramo})"
    elif tipo == "IssueCommentEvent":
        issue = p.get("issue") or {}
        ramo = ""
        onde = "PR" if "pull_request" in issue else "issue"
        texto = f"comentário no {onde} #{numero} de {repo}: {(issue.get('title') or '')[:60]}"
        m = RE_TASK_TITULO.search(issue.get("title") or "")
        return texto, (m.group(1).upper() if m else None)
    else:
        return None  # WatchEvent, DeleteEvent e afins não dizem em que você trabalhou

    m = RE_TASK_BRANCH.search(ramo) or RE_TASK_TITULO.search(pr.get("title") or "")
    return texto, (m.group(1).upper() if m else None)


def _eventos_github(inicio: Date, fim: Date, tz: ZoneInfo) -> tuple[list, int, str | None]:
    """Feed de atividade do seu usuário: push, PR, review, comentário.

    O `gh` usa o próprio login (keyring), então nenhum token passa por aqui. O
    feed guarda no máximo 300 eventos; quando o período começa antes do mais
    antigo, o relatório diz até onde ele alcança, para a falta de evento não ser
    lida como falta de trabalho.
    """
    login = _gh("user").get("login")
    if not login:
        raise FonteIndisponivel("gh sem usuário: rode `gh auth login`")

    lidos, eventos, mais_antigo = 0, [], None
    for pagina in (1, 2, 3):  # a API recusa além de 300 eventos
        lote = _gh(f"users/{login}/events?per_page=100&page={pagina}")
        if not isinstance(lote, list):
            break
        lidos += len(lote)
        for ev in lote:
            dt = _local(ev.get("created_at"), tz)
            if not dt:
                continue
            mais_antigo = dt if mais_antigo is None or dt < mais_antigo else mais_antigo
            dono = (ev.get("repo") or {}).get("name", "").split("/", 1)[0]
            if dono not in GITHUB_DONOS or not (inicio <= dt.date() <= fim):
                continue
            achado = _descrever_github(ev)
            if not achado:
                continue
            texto, task = achado
            eventos.append({"dt": dt, "sessao": f"github:{ev.get('id')}", "kind": "externo",
                            "txt": texto, "fonte": "github",
                            "ancora": (task, "github") if task else None})
        if len(lote) < 100 or (mais_antigo and mais_antigo.date() < inicio):
            break

    aviso = None
    if lidos >= 300 and mais_antigo and mais_antigo.date() > inicio:
        aviso = f"o feed só alcança {mais_antigo:%d/%m %H:%M}; antes disso não há dado"
    return eventos, lidos, aviso


# Registro de fontes. Adicionar agente = uma linha aqui + um adaptador acima.
# `raiz` serve para distinguir "não instalado" de "instalado e sem trabalho no
# período" — silenciar essa diferença faz ausência de dado parecer ausência de
# trabalho.
FONTES = [
    {"nome": "claude-code", "raiz": "~/.claude/projects", "resolucao": "evento",
     "ler": _eventos_claude, "unidade": "arquivos"},
    {"nome": "codex", "raiz": "~/.codex/sessions", "resolucao": "evento",
     "ler": _eventos_codex, "unidade": "arquivos"},
    {"nome": "grok", "raiz": "~/.grok/sessions", "resolucao": "sessão",
     "ler": _eventos_grok, "unidade": "sessões"},
    {"nome": "opencode", "raiz": "~/.local/share/opencode/opencode.db", "resolucao": "evento",
     "ler": _eventos_opencode, "unidade": "mensagens"},
    # Sem pasta para conferir: "instalado" é ter o `gh` no PATH.
    {"nome": "github", "raiz": None, "disponivel": lambda: shutil.which("gh"),
     "resolucao": "evento", "ler": _eventos_github, "unidade": "eventos do feed"},
]

# Agentes conhecidos sem adaptador escrito. Aparecem no relatório como lacuna,
# em vez de sumirem. Vários candidatos por agente porque o local varia com a
# versão e com o instalador.
#
# Antigravity: em 11/09/2026 só existia `~/.cache/antigravity/staging`, vazio.
# Sem material para inspecionar, um adaptador seria schema chutado — e schema
# chutado foi o que produziu sugestões de branches de outras pessoas.
SEM_ADAPTADOR = [
    {"nome": "antigravity", "raizes": [
        "~/.antigravity",
        "~/Library/Application Support/Antigravity",
        "~/Library/Application Support/Google/Antigravity",
        "~/.config/antigravity",
        "~/.cache/antigravity",
    ]},
    {"nome": "copilot", "raizes": ["~/.copilot"]},
    {"nome": "gemini-cli", "raizes": ["~/.gemini"]},
    {"nome": "cursor", "raizes": ["~/Library/Application Support/Cursor"]},
    {"nome": "windsurf", "raizes": ["~/Library/Application Support/Windsurf",
                                    "~/.codeium/windsurf"]},
    {"nome": "zed", "raizes": ["~/Library/Application Support/Zed"]},
    {"nome": "aider", "raizes": ["~/.aider.chat.history.md"]},
]


def _tem_conteudo(caminho: str) -> bool:
    """Diretório vazio não conta como agente instalado — o Antigravity deixou um
    `~/.cache/antigravity/staging` vazio que faria o relatório mentir."""
    if os.path.isfile(caminho):
        return os.path.getsize(caminho) > 0
    for _, _, arquivos in os.walk(caminho):
        if arquivos:
            return True
    return False


def entrada_relatorio(fonte: dict, achados: list, unidades: int,
                      aviso: str | None = None) -> dict:
    entrada = {
        "nome": fonte["nome"],
        "estado": "ok" if achados else "sem atividade no período",
        "eventos": len(achados), "unidades": unidades,
        "unidade": fonte["unidade"], "resolucao": fonte["resolucao"],
    }
    if aviso:
        entrada["aviso"] = aviso
    return entrada


def carregar_eventos(inicio: Date, fim: Date, tz: ZoneInfo,
                     relatorio: list | None = None) -> list[dict]:
    """Eventos de todos os agentes instalados, no intervalo local inclusivo."""
    eventos = []
    for fonte in FONTES:
        if fonte["raiz"] is None:
            instalado = bool(fonte["disponivel"]())
        else:
            instalado = os.path.exists(os.path.expanduser(fonte["raiz"]))
        if not instalado:
            if relatorio is not None:
                relatorio.append({"nome": fonte["nome"], "estado": "não instalado",
                                  "eventos": 0, "unidades": 0,
                                  "resolucao": fonte["resolucao"]})
            continue
        try:
            achados, unidades, *resto = fonte["ler"](inicio, fim, tz)
        except Exception as exc:  # um agente quebrado não derruba os outros
            if relatorio is not None:
                motivo = str(exc) if isinstance(exc, FonteIndisponivel) else exc.__class__.__name__
                relatorio.append({"nome": fonte["nome"],
                                  "estado": f"falhou: {motivo}",
                                  "eventos": 0, "unidades": 0,
                                  "resolucao": fonte["resolucao"]})
            continue
        eventos.extend(achados)
        if relatorio is not None:
            relatorio.append(entrada_relatorio(fonte, achados, unidades,
                                               resto[0] if resto else None))

    if relatorio is not None:
        for fonte in SEM_ADAPTADOR:
            achados = [os.path.expanduser(r) for r in fonte["raizes"]]
            achados = [r for r in achados if os.path.exists(r)]
            if not achados:
                continue
            com_dado = [r for r in achados if _tem_conteudo(r)]
            relatorio.append({
                "nome": fonte["nome"],
                "estado": "sem adaptador" if com_dado else "instalado? diretório vazio",
                "eventos": 0, "unidades": 0, "resolucao": "—",
                "caminhos": com_dado or achados,
            })

    eventos.sort(key=lambda e: (e["dt"], e["sessao"]))
    return eventos


# ------------------------------------------------------------------- âncoras


def extrair_ancoras(eventos: list[dict]) -> dict[str, list[tuple]]:
    """Por sessão: [(hora, task, tipo, trecho)], ordenado."""
    por_sessao = defaultdict(list)
    for e in eventos:
        achado = None
        if e["kind"] == "externo":
            achado = e.get("ancora")
        elif e["kind"] == "user":
            m = RE_URL.search(e["txt"])
            if m:
                achado = (m.group(1).upper(), "url")
            else:
                m = RE_FALA.search(e["txt"])
                if m:
                    achado = (m.group(1).upper(), "fala")
        elif e["kind"] in ("tool", "out"):
            m = RE_BRANCH.search(e["txt"])
            if m:
                achado = (m.group(1).upper(), "branch")
        if achado:
            trecho = " ".join(e["txt"].split())[:90]
            por_sessao[e["sessao"]].append((e["dt"], achado[0], achado[1], trecho))
    for s in por_sessao:
        por_sessao[s].sort(key=lambda a: a[0])
    return por_sessao


def atribuir(eventos: list[dict], ancoras: dict) -> None:
    """Cada evento herda a âncora vigente da própria sessão. Sem âncora, None.

    A âncora **expira na virada do dia**. Sessão retomada dias depois recomeça
    sem âncora: em 11/09/2026 uma sessão do dia 01 foi retomada no dia 03 e
    arrastou a task de terça para quinta, coisa que só apareceu porque a hora
    exibida (18:30) era maior que a do bloco (17:30).
    """
    for e in eventos:
        vigente = None
        for hora, task, tipo, trecho in ancoras.get(e["sessao"], ()):
            if hora.date() != e["dt"].date():
                continue
            if hora <= e["dt"] + timedelta(minutes=2):
                vigente = (task, tipo, trecho, hora)
            else:
                break
        e["task"] = vigente


# -------------------------------------------------------------------- blocos


def sugerir(dia: Date, eventos: list[dict], livres: list[tuple], agenda, tz) -> list[dict]:
    """Blocos propostos dentro das faixas livres. `task=None` significa `???`."""
    slot = timedelta(minutes=agenda.block_minutes)
    fatias = []

    for jini, jfim in livres:
        t = jini
        while t < jfim:
            b = min(t + slot, jfim)
            dentro = [e for e in eventos if t <= e["dt"] < b]
            votos, evidencia = Counter(), {}
            for e in dentro:
                if not e.get("task"):
                    continue
                task, tipo, trecho, hora = e["task"]
                votos[task] += PESO.get(e["kind"], 0)
                # Desempate estável: a evidência mais antiga vence.
                if task not in evidencia or hora < evidencia[task][3]:
                    evidencia[task] = e["task"]
            if votos:
                # Empate resolve pelo nome da task — determinístico, não pela
                # ordem em que o dicionário foi montado.
                topo = max(sorted(votos), key=lambda k: votos[k])
                # Ação sua em outra task, no mesmo trecho, que perdeu na votação
                # para uma sessão inteira. Não decide o trecho, mas o agente
                # precisa ver: em 29/09/2026 um comentário na HM-253, que nenhuma
                # outra fonte citava, sumia debaixo de uma sessão da HM-370.
                outras = [(e["dt"], e["ancora"][0], e["ancora"][1], e["txt"]) for e in dentro
                          if e["kind"] == "externo" and e.get("ancora") and e["ancora"][0] != topo]
                fatias.append({"ini": t, "fim": b, "task": topo,
                               "evid": evidencia[topo], "n": len(dentro), "outras": outras})
            else:
                fatias.append({"ini": t, "fim": b, "task": None,
                               "evid": None, "n": len(dentro), "outras": []})
            t = b

    blocos = []
    for f in fatias:
        if blocos and blocos[-1]["task"] == f["task"] and blocos[-1]["fim"] == f["ini"]:
            blocos[-1]["fim"] = f["fim"]
            blocos[-1]["n"] += f["n"]
            blocos[-1]["outras"] = blocos[-1]["outras"] + f["outras"]
        else:
            blocos.append(dict(f))
    return blocos
