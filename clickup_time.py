#!/usr/bin/env python3
"""clickup_time.py — leitura do time tracking do ClickUp (determinístico, sem curl).

Camada de lógica do `clickup-time.sh`. Só stdlib.

Comandos: `read`, `sugerir` e `tarefas` (leitura) e `write` (criação, exige
--confirm). O único ponto de mutação do módulo é o `api_post`, alcançável só
pelo `write --confirm`: os de leitura e o `write` em prévia não passam por lá.

O token nunca aparece em saída, log ou exceção — só no header da requisição.

Desenho: docs/superpowers/specs/2026-08-31-clickup-time-tracking-design.md
Correções sobre o desenho, apuradas contra a API e a UI em 11/09/2026:
  - a meta de 8h30 é do próprio ClickUp, e é conferência, não trava de escrita:
    o dia pode fechar parcial e a releitura depois da escrita mostra o resultado;
  - duração negativa = timer rodando (a API devolve assim);
  - toda task tem custom id — a UI é que não mostra (`Daily` é `ENGTECH-863`);
  - task inexistente devolve 401, não 404, e isso não é token inválido.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

WORKSPACE_ID = "90131214647"  # Irrah Tech
API2 = "https://api.clickup.com/api/v2"
KEYCHAIN_SERVICE = "clickup-irrah-tech"
TIMEZONE_PADRAO = "America/Fortaleza"

# Agenda padrão. Bate com o que a planilha do ClickUp já mostra ("X / 8h 30m").
WORK_START, WORK_END = time(8, 0), time(18, 0)
LUNCH_START, LUNCH_END = time(12, 0), time(13, 30)
BLOCK_MINUTES = 15
TARGET_MINUTES = 510  # 8h30 = expediente líquido


class Erro(Exception):
    """Falha esperada: vira mensagem limpa no stderr, sem traceback."""


# ---------------------------------------------------------------- credencial


# O clickup-token (fonte: clickup_token.swift) vem pronto com a skill, em bin/:
# quem usa não compila nada, nem precisa de Xcode ou Command Line Tools. Quem
# mantém a skill gera o binário com `digital --compilar`, que exige o Xcode. A
# cópia instalada fica fora do repo porque o Keychain confia nela pelo hash, e o
# repo pode mudar de lugar.
PASTA_SKILL = os.path.dirname(os.path.abspath(__file__))
FONTE_DIGITAL = os.path.join(PASTA_SKILL, "clickup_token.swift")
EMBARCADO = os.path.join(PASTA_SKILL, "bin", "clickup-token")
FICHA_EMBARCADO = EMBARCADO + ".json"
DIGITAL = os.path.expanduser("~/Library/Application Support/clickup-time/clickup-token")
# Universal: Apple Silicon e Intel. macOS 12 é o piso do LocalAuthentication usado.
ALVOS = ("arm64-apple-macos12", "x86_64-apple-macos12")
# O que o clickup-token grava no comentário do item (ver clickup_token.swift).
MARCA_DIGITAL = "gravado por clickup-token"

# Caminho real da skill, com `~`: quem instalou pelo README não tem `./apontar` na
# pasta em que está, e no mind o atalho fica na raiz do repo.
_CASA = os.path.expanduser("~")
_PASTA_EXIBIDA = ("~" + PASTA_SKILL[len(_CASA):]
                  if PASTA_SKILL.startswith(_CASA + os.sep) else PASTA_SKILL)
COMO_CONFIGURAR = (
    "Configure num terminal seu, fora do Claude Code (o token não passa pelo chat):\n\n"
    f"  {_PASTA_EXIBIDA}/apontar                   # configura e segue para o apontamento\n"
    f"  {_PASTA_EXIBIDA}/clickup-time.sh digital   # só grava (ou troca) o token\n\n"
    "O token é pedido sem eco pelo clickup-token, e cada leitura pede a digital."
)


def _sha256(caminho: str) -> str | None:
    import hashlib

    try:
        with open(caminho, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def estado_digital() -> str | None:
    """O que falta para ler o token pela digital, ou None se está pronto.

    Não pede digital: compara hashes e lê os atributos do item, que não são
    segredo (o `security` sem `-w` lê só atributos e não abre diálogo).
    """
    if not os.path.exists(EMBARCADO):
        return "o clickup-token não veio com a skill (falta bin/clickup-token)"
    if not os.access(DIGITAL, os.X_OK):
        return "o clickup-token não está instalado"
    if _sha256(DIGITAL) != _sha256(EMBARCADO):
        return "a skill trouxe um clickup-token novo: é preciso instalar e regravar o token"
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE],
                       capture_output=True, text=True, timeout=30)
    if r.returncode == 44:
        return "o token não está no Keychain"
    if f'"icmt"<blob>="{MARCA_DIGITAL}"' not in r.stdout:
        return "o token está num item antigo, que não foi gravado pelo clickup-token"
    return None


def obter_token() -> str:
    """Token do ClickUp, lido pelo `clickup-token` depois da digital.

    É o único caminho: sem variável de ambiente, sem `security -w`. O item antigo,
    criado com `-T ""`, abria o diálogo do Keychain, que só aceita a senha do
    chaveiro; a digital vem do LocalAuthentication, que só o `clickup-token`
    chama. O valor não é logado nem devolvido em erro.
    """
    if not os.access(DIGITAL, os.X_OK):
        raise Erro(f"a digital não está configurada.\n{COMO_CONFIGURAR}")
    try:
        r = subprocess.run([DIGITAL, "ler"], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise Erro("a digital não foi confirmada em 120s. Rode de novo.") from None
    except OSError as exc:
        raise Erro(f"não consegui executar o clickup-token: {exc.__class__.__name__}") from None

    if r.returncode == 0 and r.stdout.strip():
        return conferir_formato(r.stdout.strip())
    # Confundir "não existe" com "você cancelou" manda a pessoa regravar um item
    # que está perfeitamente no lugar.
    if r.returncode == 44:
        raise Erro(f"o token não está no Keychain.\n{COMO_CONFIGURAR}")
    if r.returncode == 45:
        raise Erro(f"o token está num item antigo, gravado pelo `security`.\n{COMO_CONFIGURAR}")
    if r.returncode == 51:
        raise Erro("digital recusada ou cancelada. Rode de novo.")
    detalhe = (r.stderr or "").strip().splitlines()
    raise Erro(f"o clickup-token saiu com código {r.returncode}"
               + (f": {detalhe[0][:160]}" if detalhe else "")
               + f"\n{COMO_CONFIGURAR}")


# `pk_` + id numérico do usuário + sufixo alfanumérico maiúsculo.
FORMATO_TOKEN = re.compile(r"pk_\d{6,}_[0-9A-Z]{20,}")


def comando_digital(conferir: bool = False, compilar: bool = False) -> int:
    """Instala o `clickup-token` que vem com a skill e grava o token por ele.

    O token é pedido pelo próprio programa, sem eco, direto do terminal. Sem
    terminal, recusa: é assim que o token não passa por agente nem por chat.
    `conferir` só diz o que falta, sem pedir nada — é o que o `apontar` usa para
    decidir se configura antes de abrir o Claude Code. `compilar` é para quem
    mantém a skill: gera o bin/clickup-token a partir do .swift.
    """
    import shutil

    if conferir:
        falta = estado_digital()
        print(falta or "digital configurada")
        return 1 if falta else 0
    if compilar:
        return _compilar_embarcado()

    if sys.platform != "darwin":
        raise Erro("a digital depende do Keychain e do LocalAuthentication do macOS.")
    if not sys.stdin.isatty():
        raise Erro("rode num terminal seu: o token é pedido sem eco e não pode vir por pipe "
                   "nem pelo chat.")
    if not os.path.exists(EMBARCADO):
        raise Erro("o clickup-token não veio com a skill (falta bin/clickup-token).\n"
                   "Quem mantém a skill gera com `./clickup-time.sh digital --compilar` "
                   "(exige o Xcode).")

    if _sha256(DIGITAL) != _sha256(EMBARCADO):
        os.makedirs(os.path.dirname(DIGITAL), exist_ok=True)
        novo = DIGITAL + ".novo"
        shutil.copyfile(EMBARCADO, novo)
        os.chmod(novo, 0o755)
        os.replace(novo, DIGITAL)
        print("clickup-token instalado.", file=sys.stderr)

    # Binário novo tem outro hash, e o item antigo deixa de confiar nele: por isso
    # gravar vem sempre logo depois da instalação, nunca como passo separado.
    r = subprocess.run([DIGITAL, "gravar"])
    return r.returncode


def _compilar_embarcado() -> int:
    """Gera bin/clickup-token (universal) e a ficha com os hashes. Exige o Xcode.

    Mesma fonte e mesmo Xcode dão o mesmo binário, byte a byte (provado em
    30/09/2026), desde que o arquivo de saída se chame `clickup-token`: o nome
    vira o identificador da assinatura ad hoc. Então dá para conferir o binário
    da skill recompilando. As Command Line Tools sozinhas não servem: as 27 não
    trazem as bibliotecas x86_64 e a fatia Intel não liga.
    """
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        fatias = []
        for alvo in ALVOS:
            saida = os.path.join(tmp, alvo, "clickup-token")
            os.makedirs(os.path.dirname(saida))
            r = subprocess.run(["xcrun", "swiftc", "-O", "-target", alvo, "-o", saida, FONTE_DIGITAL],
                               capture_output=True, text=True)
            if r.returncode != 0:
                erros = "\n".join(l for l in r.stderr.splitlines() if "error" in l)[:800]
                raise Erro(f"a compilação para {alvo} falhou:\n{erros}\n"
                           "Precisa do Xcode selecionado: sudo xcode-select -s /Applications/Xcode.app")
            fatias.append(saida)
        universal = os.path.join(tmp, "clickup-token")
        r = subprocess.run(["lipo", "-create", "-output", universal, *fatias],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise Erro(f"o lipo falhou: {r.stderr.strip()[:300]}")
        os.makedirs(os.path.dirname(EMBARCADO), exist_ok=True)
        shutil.copyfile(universal, EMBARCADO)
        os.chmod(EMBARCADO, 0o755)

    versao = subprocess.run(["xcrun", "swiftc", "--version"], capture_output=True,
                            text=True).stdout.splitlines()
    ficha = {
        "fonte": os.path.basename(FONTE_DIGITAL),
        "fonte_sha256": _sha256(FONTE_DIGITAL),
        "binario_sha256": _sha256(EMBARCADO),
        "alvos": list(ALVOS),
        "compilador": next((l for l in versao if "Swift version" in l), ""),
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    with open(FICHA_EMBARCADO, "w") as fh:
        json.dump(ficha, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"gerado bin/clickup-token ({', '.join(a.split('-')[0] for a in ALVOS)}).\n"
          "Quem já usa a skill vai regravar o token no próximo ./apontar: o hash mudou.",
          file=sys.stderr)
    return 0


def conferir_formato(token: str) -> str:
    """Recusa valor que não tem cara de token antes de gastar uma chamada na API.

    Em 11/09/2026 o Keychain guardou a string `-U` por causa da ordem dos
    argumentos do `security`, e o sintoma chegou como 401 — erro caro e que
    aponta para o lugar errado.
    """
    if not FORMATO_TOKEN.fullmatch(token):
        raise Erro(
            f"o valor no Keychain não tem formato de token do ClickUp "
            f"({len(token)} caractere(s), esperado `pk_<id>_<ALNUM>`).\n{COMO_CONFIGURAR}"
        )
    return token


# ------------------------------------------------------------------ HTTP GET


def api_get(caminho: str, params: dict, token: str) -> dict:
    """GET autenticado. Única porta de saída HTTP do módulo."""
    url = f"{API2}{caminho}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        corpo = exc.read().decode("utf-8", "replace")[:400]
        if exc.code == 401:
            raise Erro("401 do ClickUp: token inválido ou revogado.") from None
        if exc.code == 429:
            reset = exc.headers.get("X-RateLimit-Reset", "?")
            raise Erro(f"429: limite de requisições estourado (reset em {reset}).") from None
        raise Erro(f"HTTP {exc.code} em {caminho}: {corpo}") from None
    except urllib.error.URLError as exc:
        raise Erro(f"falha de rede em {caminho}: {exc.reason}") from None


def api_post(caminho: str, corpo: dict, token: str) -> dict:
    """POST autenticado. Só o `write --confirm` chega aqui — nada mais no módulo
    monta método de mutação."""
    dados = json.dumps(corpo).encode("utf-8")
    req = urllib.request.Request(f"{API2}{caminho}", data=dados, method="POST")
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        corpo_erro = exc.read().decode("utf-8", "replace")[:400]
        raise Erro(f"HTTP {exc.code} ao criar lançamento: {corpo_erro}") from None
    except urllib.error.URLError as exc:
        raise Erro(f"falha de rede ao criar lançamento: {exc.reason}") from None


def api_put(caminho: str, corpo: dict, token: str) -> dict:
    """PUT autenticado. Usado só para reafirmar valores de um lançamento que este
    script acabou de criar — nunca para editar lançamento de origem `clickup`."""
    dados = json.dumps(corpo).encode("utf-8")
    req = urllib.request.Request(f"{API2}{caminho}", data=dados, method="PUT")
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        corpo_erro = exc.read().decode("utf-8", "replace")[:400]
        raise Erro(f"HTTP {exc.code} ao selar o fim do lançamento: {corpo_erro}") from None
    except urllib.error.URLError as exc:
        raise Erro(f"falha de rede ao selar o fim: {exc.reason}") from None


# ------------------------------------------------------------------- modelo


@dataclass
class Lancamento:
    """Entrada já existente. Âncora imutável — nada aqui edita ou apaga."""

    id: str
    task_id: str | None
    task_ref: str | None  # custom id (HM-304) quando existe
    task_nome: str | None
    inicio: datetime
    fim: datetime | None
    duracao_min: int
    rodando: bool
    descricao: str

    def como_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "task_ref": self.task_ref,
            "task_nome": self.task_nome,
            "start": self.inicio.isoformat(),
            "end": self.fim.isoformat() if self.fim else None,
            "duration_minutes": self.duracao_min,
            "running": self.rodando,
            "description": self.descricao,
            "existing": True,
        }


@dataclass
class Agenda:
    work_start: time = WORK_START
    work_end: time = WORK_END
    lunch_start: time = LUNCH_START
    lunch_end: time = LUNCH_END
    block_minutes: int = BLOCK_MINUTES
    target_minutes: int = TARGET_MINUTES

    def validar(self) -> None:
        if not (self.work_start < self.lunch_start < self.lunch_end < self.work_end):
            raise Erro(
                "agenda inválida: exige work-start < lunch-start < lunch-end < work-end"
            )
        if self.block_minutes <= 0:
            raise Erro("--block-minutes precisa ser positivo")
        if self.liquido_min() < self.target_minutes:
            raise Erro(
                f"meta ({self.target_minutes}min) excede o líquido da agenda "
                f"({self.liquido_min()}min)"
            )

    def liquido_min(self) -> int:
        def m(t: time) -> int:
            return t.hour * 60 + t.minute

        return (m(self.work_end) - m(self.work_start)) - (
            m(self.lunch_end) - m(self.lunch_start)
        )

    def janelas(self, dia: Date, tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
        """As duas faixas úteis do dia, em horário local."""

        def dt(t: time) -> datetime:
            return datetime.combine(dia, t, tzinfo=tz)

        return [
            (dt(self.work_start), dt(self.lunch_start)),
            (dt(self.lunch_end), dt(self.work_end)),
        ]


@dataclass
class Dia:
    data: Date
    lancamentos: list[Lancamento] = field(default_factory=list)
    problemas: list[dict] = field(default_factory=list)

    def total_min(self) -> int:
        return sum(l.duracao_min for l in self.lancamentos if not l.rodando)


# -------------------------------------------------------------- normalização


def ms_para_local(ms: str | int, tz: ZoneInfo) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=tz)


def normalizar(bruto: dict, tz: ZoneInfo) -> Lancamento:
    task = bruto.get("task") or {}
    duracao_ms = int(bruto.get("duration") or 0)
    rodando = duracao_ms < 0  # contrato da API: negativo = timer aberto

    inicio = ms_para_local(bruto["start"], tz)
    fim_bruto = bruto.get("end")
    fim = ms_para_local(fim_bruto, tz) if fim_bruto and int(fim_bruto) > 0 else None

    return Lancamento(
        id=str(bruto.get("id", "")),
        task_id=task.get("id"),
        task_ref=task.get("custom_id"),
        task_nome=task.get("name"),
        inicio=inicio,
        fim=fim,
        duracao_min=0 if rodando else round(duracao_ms / 60000),
        rodando=rodando,
        descricao=bruto.get("description") or "",
    )


# ---------------------------------------------------------------- conferência


def conferir(dia: Dia, agenda: Agenda, tz: ZoneInfo) -> None:
    """Marca divergências. Só reporta — nunca conserta, nunca edita âncora."""
    janelas = agenda.janelas(dia.data, tz)
    almoco_ini = datetime.combine(dia.data, agenda.lunch_start, tzinfo=tz)
    almoco_fim = datetime.combine(dia.data, agenda.lunch_end, tzinfo=tz)
    expediente_ini, expediente_fim = janelas[0][0], janelas[1][1]

    for l in dia.lancamentos:
        if l.rodando:
            dia.problemas.append(
                {"tipo": "TIMER_RODANDO", "entry": l.id, "detalhe": f"aberto desde {l.inicio:%H:%M}"}
            )
            continue
        fim = l.fim or l.inicio
        if l.inicio < almoco_fim and fim > almoco_ini:
            dia.problemas.append(
                {"tipo": "NO_ALMOCO", "entry": l.id, "detalhe": f"{l.inicio:%H:%M}–{fim:%H:%M}"}
            )
        if l.inicio < expediente_ini or fim > expediente_fim:
            dia.problemas.append(
                {"tipo": "FORA_EXPEDIENTE", "entry": l.id, "detalhe": f"{l.inicio:%H:%M}–{fim:%H:%M}"}
            )
        if l.duracao_min % agenda.block_minutes:
            dia.problemas.append(
                {"tipo": "FORA_DA_GRADE", "entry": l.id, "detalhe": f"{l.duracao_min}min"}
            )

    ordenados = sorted((l for l in dia.lancamentos if not l.rodando), key=lambda l: l.inicio)
    for a, b in zip(ordenados, ordenados[1:]):
        if (a.fim or a.inicio) > b.inicio:
            dia.problemas.append(
                {
                    "tipo": "SOBREPOSICAO",
                    "entry": f"{a.id}+{b.id}",
                    "detalhe": f"{a.inicio:%H:%M}–{(a.fim or a.inicio):%H:%M} vs {b.inicio:%H:%M}",
                }
            )


def livres(dia: Dia, agenda: Agenda, tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
    """Faixas ainda disponíveis, já descontados almoço e âncoras."""
    ocupados = sorted(
        ((l.inicio, l.fim or l.inicio) for l in dia.lancamentos if not l.rodando),
        key=lambda p: p[0],
    )
    resultado = []
    for jini, jfim in agenda.janelas(dia.data, tz):
        cursor = jini
        for oini, ofim in ocupados:
            if ofim <= jini or oini >= jfim:
                continue
            if oini > cursor:
                resultado.append((cursor, min(oini, jfim)))
            cursor = max(cursor, ofim)
        if cursor < jfim:
            resultado.append((cursor, jfim))
    return [(a, b) for a, b in resultado if (b - a) >= timedelta(minutes=agenda.block_minutes)]


# ------------------------------------------------------------------- leitura


def ler(inicio: Date, fim: Date, tz: ZoneInfo, agenda: Agenda, token: str) -> list[Dia]:
    """Lançamentos do intervalo inclusivo, em dias do calendário local."""
    de = datetime.combine(inicio, time(0, 0), tzinfo=tz)
    ate = datetime.combine(fim + timedelta(days=1), time(0, 0), tzinfo=tz)

    resp = api_get(
        f"/team/{WORKSPACE_ID}/time_entries",
        {
            "start_date": int(de.timestamp() * 1000),
            "end_date": int(ate.timestamp() * 1000),
        },
        token,
    )

    por_dia: dict[Date, Dia] = {}
    d = inicio
    while d <= fim:
        por_dia[d] = Dia(data=d)
        d += timedelta(days=1)

    for bruto in resp.get("data") or []:
        l = normalizar(bruto, tz)
        alvo = por_dia.get(l.inicio.date())
        if alvo is not None:  # a API pode devolver borda fora do intervalo local
            alvo.lancamentos.append(l)

    for dia in por_dia.values():
        dia.lancamentos.sort(key=lambda l: l.inicio)
        conferir(dia, agenda, tz)
    return [por_dia[k] for k in sorted(por_dia)]


# -------------------------------------------------------------------- saída


DIAS_PT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def hm(minutos: int) -> str:
    h, m = divmod(abs(minutos), 60)
    s = "-" if minutos < 0 else ""
    return f"{s}{h}h{m:02d}" if h else f"{s}{m}min"


def imprimir(dias: list[Dia], agenda: Agenda, tz: ZoneInfo) -> None:
    for dia in dias:
        total = dia.total_min()
        falta = agenda.target_minutes - total
        cab = f"{DIAS_PT[dia.data.weekday()]}, {dia.data:%d/%m}"
        estado = "completo" if falta == 0 else (f"falta {hm(falta)}" if falta > 0 else f"excede {hm(-falta)}")
        print(f"\n\033[1m{cab}\033[0m  {hm(total)} / {hm(agenda.target_minutes)}  ({estado})")

        if not dia.lancamentos:
            print("  (sem lançamentos)")
        for l in dia.lancamentos:
            ref = l.task_ref or (l.task_nome or "—")[:38]
            fim = f"{l.fim:%H:%M}" if l.fim else "  …  "
            marca = " ⟳" if l.rodando else ""
            nome = f"  {l.task_nome[:44]}" if l.task_ref and l.task_nome else ""
            print(f"  {l.inicio:%H:%M}–{fim}  {hm(l.duracao_min):>6}  {ref}{nome}{marca}")

        vagas = livres(dia, agenda, tz)
        if vagas:
            faixas = ", ".join(f"{a:%H:%M}–{b:%H:%M}" for a, b in vagas)
            print(f"  \033[2mlivre:\033[0m {faixas}")
        for p in dia.problemas:
            print(f"  \033[33m⚠ {p['tipo']}\033[0m {p['detalhe']}")

    print()
    total_geral = sum(d.total_min() for d in dias)
    meta_geral = agenda.target_minutes * len(dias)
    print(f"\033[1mperíodo:\033[0m {hm(total_geral)} de {hm(meta_geral)} em {len(dias)} dia(s)")

    vocab: dict[str, str] = {}
    for dia in dias:
        for l in dia.lancamentos:
            if l.task_id:
                vocab[l.task_id] = f"{l.task_ref or '—'}  {l.task_nome or ''}"
    if vocab:
        print("\n\033[1mtasks usadas no período\033[0m (vocabulário para o plano):")
        for tid, rotulo in sorted(vocab.items(), key=lambda kv: kv[1]):
            print(f"  {tid}  {rotulo}")


def como_json(dias: list[Dia], agenda: Agenda, tz: ZoneInfo) -> dict:
    return {
        "timezone": str(tz),
        "schedule": {
            "work_start": agenda.work_start.strftime("%H:%M"),
            "work_end": agenda.work_end.strftime("%H:%M"),
            "lunch_start": agenda.lunch_start.strftime("%H:%M"),
            "lunch_end": agenda.lunch_end.strftime("%H:%M"),
            "block_minutes": agenda.block_minutes,
            "target_minutes": agenda.target_minutes,
        },
        "days": [
            {
                "date": d.data.isoformat(),
                "weekday": DIAS_PT[d.data.weekday()],
                "existing_minutes": d.total_min(),
                "target_minutes": agenda.target_minutes,
                "missing_minutes": agenda.target_minutes - d.total_min(),
                "entries": [l.como_dict() for l in d.lancamentos],
                "free_windows": [
                    {"start": a.isoformat(), "end": b.isoformat(),
                     "minutes": int((b - a).total_seconds() // 60)}
                    for a, b in livres(d, agenda, tz)
                ],
                "issues": d.problemas,
            }
            for d in dias
        ],
    }


# -------------------------------------------------------------------- escrita


CUSTOM_ID = re.compile(r"[A-Za-z]+-\d+")
DURACAO = re.compile(r"(?:(\d+)h)?(?:(\d+)m(?:in)?|(\d+))?$")

_cache_task: dict[str, tuple[str, str | None, str]] = {}


def parse_duracao(s: str) -> int:
    """`45m`, `45min`, `1h`, `1h15`, `2h30`, `90` → minutos.

    `min` entra porque e assim que o proprio sistema imprime duracao em toda
    parte: recusar de volta o que ele mesmo escreve so produz erro obscuro.
    """
    m = DURACAO.fullmatch(s.strip().lower())
    if not m or not any(m.groups()):
        raise Erro(f"duração inválida: {s!r} (use 45m, 1h, 1h15, 2h30)")
    horas = int(m.group(1) or 0)
    minutos = int(m.group(2) or m.group(3) or 0)
    total = horas * 60 + minutos
    if total <= 0:
        raise Erro(f"duração precisa ser positiva: {s!r}")
    return total


def parse_entrada(s: str) -> tuple[time, int, str]:
    """`"08:30 45m HM-240"` → (08:30, 45, "HM-240")."""
    partes = s.split()
    if len(partes) != 3:
        raise Erro(
            f"entrada inválida: {s!r}\n"
            'formato: --entry "HH:MM <duração> <task>"  (ex: "08:30 45m HM-240")'
        )
    return parse_hora(partes[0]), parse_duracao(partes[1]), partes[2]


_cache_task_bruta: dict[str, dict] = {}


def _buscar_task(ref: str, token: str) -> dict:
    """GET da task pela referência (custom id ou id real). Só leitura."""
    if ref in _cache_task_bruta:
        return _cache_task_bruta[ref]

    params = {"include_subtasks": "false"}
    if CUSTOM_ID.fullmatch(ref):
        params |= {"custom_task_ids": "true", "team_id": WORKSPACE_ID}

    try:
        dados = api_get(f"/task/{urllib.parse.quote(ref, safe='')}", params, token)
    except Erro as e:
        # O ClickUp responde 401 (não 404) para task inexistente ou fora do seu
        # acesso. Traduzir literalmente acusaria o token, que pode estar ótimo.
        if str(e).startswith(("401", "HTTP 404")):
            raise Erro(
                f"task não encontrada ou sem acesso: {ref!r}\n"
                "confira o custom id — o ClickUp responde 401 nesse caso, "
                "não 404, então isto NÃO quer dizer token inválido"
            ) from None
        raise
    if not dados.get("id"):
        raise Erro(f"task não resolvida: {ref!r}")
    _cache_task_bruta[ref] = dados
    return dados


def resolver_task(ref: str, token: str) -> tuple[str, str | None, str]:
    """Referência → (id real, custom id, nome). Exige resolver para exatamente uma."""
    if ref in _cache_task:
        return _cache_task[ref]
    dados = _buscar_task(ref, token)
    achado = (dados["id"], dados.get("custom_id"), dados.get("name") or "")
    _cache_task[ref] = achado
    return achado


def detalhar_task(ref: str, token: str, max_chars: int = 1500) -> dict:
    """O que o agente precisa para escrever o `requisito` do resumo do plano.

    A descrição sai em texto puro (`text_content`) e cortada: o agente resume,
    não transcreve. Descrição de task já trouxe credencial viva (o export do
    ClickUp tinha um token Z-API), então o resumo nunca copia valor literal.
    """
    dados = _buscar_task(ref, token)
    texto = (dados.get("text_content") or dados.get("description") or "").strip()
    cortado = len(texto) > max_chars
    return {
        "ref": dados.get("custom_id") or ref,
        "id": dados["id"],
        "nome": dados.get("name") or "",
        "status": ((dados.get("status") or {}).get("status") or ""),
        "lista": ((dados.get("list") or {}).get("name") or ""),
        "url": dados.get("url") or f"https://app.clickup.com/t/{dados['id']}",
        "descricao": texto[:max_chars] + (" [...]" if cortado else ""),
    }


def comando_tarefas(refs: list[str], token: str, como_json: bool, max_chars: int) -> int:
    """Lê nome, status e descrição das tasks. Nunca escreve."""
    saida, falhas = [], []
    for ref in refs:
        try:
            saida.append(detalhar_task(ref, token, max_chars))
        except Erro as e:
            falhas.append({"ref": ref, "erro": str(e).splitlines()[0]})
    if como_json:
        json.dump({"tarefas": saida, "falhas": falhas}, sys.stdout,
                  ensure_ascii=False, indent=2)
        print()
        return 0 if not falhas else 1
    for t in saida:
        print(f"\n\033[1m{t['ref']}\033[0m  {t['nome']}")
        print(f"  \033[2m{t['status']} · {t['lista']} · {t['url']}\033[0m")
        for linha in (t["descricao"] or "(sem descrição)").splitlines():
            if linha.strip():
                print(f"  {linha.strip()}")
    for f in falhas:
        print(f"\n\033[31m{f['ref']}\033[0m  {f['erro']}")
    return 0 if not falhas else 1


@dataclass
class Candidato:
    inicio: datetime
    fim: datetime
    duracao_min: int
    ref: str
    task_id: str | None = None
    task_nome: str = ""
    estado: str = "criar"  # criar | ja_existe | bloqueado
    motivo: str = ""

    def bloquear(self, motivo: str) -> None:
        self.estado, self.motivo = "bloqueado", motivo


def fundir_contiguos(cands: list[Candidato]) -> list[Candidato]:
    """Junta candidatos encostados da mesma task num lançamento só.

    Por que existe: a grade de 15min e a resolução dos `???` produzem blocos
    adjacentes da mesma task. `tr.sugerir` já funde o que consegue, mas só antes
    de o agente resolver os buracos — um bloco `task=None` entre dois da mesma
    task vira, depois da leitura, três blocos iguais e encostados. Sem isto,
    02/09/2026 iria para a planilha como 12 lançamentos onde 3 bastam.

    A fusão não perde nada **na planilha**: o lançamento só carrega task, início
    e duração — a origem e a nota de cada bloco vivem no plano e na tela, que
    seguem granulares de propósito. É lá que a justificativa é auditável.

    Segurança: só funde o que é exatamente contíguo, então o resultado é sempre
    uma união de intervalos já propostos. Isso só pode ampliar um intervalo,
    nunca criar buraco — e todo guard de `validar_candidatos` (expediente,
    almoço, meia-noite, sobreposição) reprova mais, nunca menos, com o bloco
    maior. O almoço, em particular, quebra a contiguidade sozinho: 11:45–12:00 e
    13:30–13:45 não se encostam.

    Idempotente: mesmas entradas → mesma fusão, então reexecutar reconhece o que
    foi gravado como `ja_existe` em vez de tentar criar de novo.
    """
    fundidos: list[Candidato] = []
    for c in sorted(cands, key=lambda c: c.inicio):
        ant = fundidos[-1] if fundidos else None
        # Compara a referência crua (normalizada): é o que a tela e o terminal
        # enxergam antes de `resolver_task`. Refs diferentes para a mesma task
        # não fundem — conservador de propósito, já que o custo é só perder uma
        # fusão, enquanto fundir errado juntaria tasks distintas.
        if ant and ant.fim == c.inicio and ant.ref.strip().upper() == c.ref.strip().upper():
            ant.fim = c.fim
            ant.duracao_min += c.duracao_min
        else:
            fundidos.append(c)
    return fundidos


def montar_candidatos(
    dia: Date, entradas: list[str], tz: ZoneInfo, agenda: Agenda
) -> list[Candidato]:
    cands = []
    for bruta in entradas:
        hora, dur, ref = parse_entrada(bruta)
        inicio = datetime.combine(dia, hora, tzinfo=tz)
        cands.append(Candidato(inicio, inicio + timedelta(minutes=dur), dur, ref))
    return fundir_contiguos(cands)


def validar_candidatos(
    cands: list[Candidato], existente: Dia, agenda: Agenda, tz: ZoneInfo
) -> None:
    """Guardrails temporais. A meta de 8h30 NÃO é trava aqui — é conferência,
    feita pela releitura depois da escrita."""
    almoco_ini = datetime.combine(existente.data, agenda.lunch_start, tzinfo=tz)
    almoco_fim = datetime.combine(existente.data, agenda.lunch_end, tzinfo=tz)
    exp_ini = datetime.combine(existente.data, agenda.work_start, tzinfo=tz)
    exp_fim = datetime.combine(existente.data, agenda.work_end, tzinfo=tz)

    for c in cands:
        if c.duracao_min % agenda.block_minutes:
            c.bloquear(f"duração {c.duracao_min}min não é múltiplo de {agenda.block_minutes}")
            continue
        # Até 25/09/2026 só a duração era conferida: "08:10 45m" passava. A grade
        # é absoluta (08:00, 08:15...), a mesma que o plano e a tela usam.
        if (c.inicio.hour * 60 + c.inicio.minute) % agenda.block_minutes:
            c.bloquear(f"início {c.inicio:%H:%M} fora da grade de {agenda.block_minutes}min")
            continue
        if c.inicio < exp_ini or c.fim > exp_fim:
            c.bloquear(f"fora do expediente {agenda.work_start:%H:%M}–{agenda.work_end:%H:%M}")
            continue
        if c.inicio < almoco_fim and c.fim > almoco_ini:
            c.bloquear(f"cruza o almoço {agenda.lunch_start:%H:%M}–{agenda.lunch_end:%H:%M}")
            continue
        if c.inicio.date() != existente.data or c.fim.date() != existente.data:
            c.bloquear("atravessa a meia-noite")
            continue

        for l in existente.lancamentos:
            if l.rodando:
                continue
            lfim = l.fim or l.inicio
            if c.inicio < lfim and c.fim > l.inicio:
                mesmo = (
                    l.task_id == c.task_id
                    and l.inicio == c.inicio
                    and l.duracao_min == c.duracao_min
                )
                if mesmo:
                    c.estado = "ja_existe"
                    c.motivo = f"idêntico ao lançamento {l.id}"
                else:
                    c.bloquear(
                        f"sobrepõe {l.task_ref or l.task_nome} "
                        f"{l.inicio:%H:%M}–{lfim:%H:%M}"
                    )
                break

    ativos = [c for c in cands if c.estado == "criar"]
    for a, b in zip(ativos, ativos[1:]):
        if a.fim > b.inicio:
            b.bloquear(f"sobrepõe a entrada anterior ({a.inicio:%H:%M}–{a.fim:%H:%M})")


URL_PLANILHA = f"https://app.clickup.com/{WORKSPACE_ID}/time"


def semana_de(d: Date) -> tuple[Date, Date]:
    """Domingo a sábado — é o recorte que a planilha do ClickUp usa."""
    domingo = d - timedelta(days=(d.weekday() + 1) % 7)
    return domingo, domingo + timedelta(days=6)


def link_planilha(dias: list[Date]) -> None:
    """A releitura por API não enxerga defeito de gravação (ver o caso do `end`
    em 11/09/2026). Conferir na tela faz parte do processo, então o link sai
    junto com o resultado."""
    semanas = sorted({semana_de(d) for d in dias})
    print(f"\n\033[1mplanilha:\033[0m {URL_PLANILHA}")
    for ini, fim in semanas:
        print(f"  \033[2msemana {ini:%d/%m}–{fim:%d/%m} · aba \"entradas de tempo\" "
              f"mostra a Hora Final\033[0m")
    print(f"  \033[2mopen {shlex.quote(URL_PLANILHA)}\033[0m")


# ------------------------------------------------------ comentários do ClickUp


def _comentarios(caminho: str, params: dict, desde_ms: int, token: str) -> list[dict]:
    """Comentários do mais novo para o mais velho, até passar de `desde_ms`.

    A API devolve 25 por vez; a próxima página é pedida com `start`/`start_id` do
    mais antigo do lote anterior.
    """
    todos: list[dict] = []
    pagina = dict(params)
    for _ in range(20):  # 500 comentários: além disso a task não é de um período curto
        lote = api_get(caminho, pagina, token).get("comments") or []
        todos += lote
        if len(lote) < 25 or int(lote[-1].get("date") or 0) < desde_ms:
            break
        pagina = params | {"start": lote[-1]["date"], "start_id": lote[-1]["id"]}
    return todos


def eventos_comentarios(inicio: Date, fim: Date, tz: ZoneInfo, token: str,
                        refs: set[str], relatorio: list) -> list[dict]:
    """Comentários seus no ClickUp, no período, como eventos para o `sugerir`.

    A API não tem um feed do que você fez; ela só lista comentários por task. As
    candidatas são as tasks citadas nas outras fontes e nos lançamentos do
    período, mais as atribuídas a você que mudaram desde o início dele.
    Comentário em task de outra pessoa que nenhuma outra fonte cita fica de fora.

    O texto do comentário não entra no evento: comentário e descrição de task já
    trouxeram credencial viva, e o trecho vai para o JSON que o agente lê.
    """
    import clickup_time_transcricao as tr

    fonte = {"nome": "clickup", "resolucao": "evento", "unidade": "tasks lidas"}
    de_ms = int(datetime.combine(inicio, time(0, 0), tzinfo=tz).timestamp() * 1000)
    ate_ms = int(datetime.combine(fim + timedelta(days=1), time(0, 0), tzinfo=tz).timestamp() * 1000)
    try:
        eu = str(api_get("/user", {}, token)["user"]["id"])
        candidatas = {r.upper() for r in refs if CUSTOM_ID.fullmatch(r)}
        for pagina in range(10):
            lote = api_get(f"/team/{WORKSPACE_ID}/task", {
                "assignees[]": eu, "date_updated_gt": de_ms, "include_closed": "true",
                "subtasks": "true", "page": pagina,
            }, token)
            tasks = lote.get("tasks") or []
            candidatas |= {t.get("custom_id") or t["id"] for t in tasks}
            if len(tasks) < 100 or lote.get("last_page"):
                break
    except Erro as e:
        _relatar(relatorio, tr.entrada_relatorio(fonte, [], 0)
                 | {"estado": f"falhou: {str(e).splitlines()[0][:120]}"})
        return []

    eventos, lidas, aviso = [], 0, None
    for ref in sorted(candidatas):
        params = ({"custom_task_ids": "true", "team_id": WORKSPACE_ID}
                  if CUSTOM_ID.fullmatch(ref) else {})
        try:
            raiz = _comentarios(f"/task/{urllib.parse.quote(ref, safe='')}/comment",
                                params, de_ms, token)
            respostas = []
            for c in raiz:
                if int(c.get("reply_count") or 0) > 0:
                    respostas += [r | {"_resposta": True} for r in api_get(
                        f"/comment/{c['id']}/reply", {}, token).get("comments") or []]
        except Erro as e:
            if str(e).startswith("429"):
                aviso = f"limite de requisições do ClickUp: parou em {ref}, o resto não foi lido"
                break
            continue  # 401 = task de outro workspace ou citada errado; não é falha da fonte
        lidas += 1
        for c in raiz + respostas:
            quando = int(c.get("date") or 0)
            if str((c.get("user") or {}).get("id")) != eu or not (de_ms <= quando < ate_ms):
                continue
            onde = "resposta sua num comentário de" if c.get("_resposta") else "comentário seu em"
            eventos.append({
                "dt": datetime.fromtimestamp(quando / 1000, tz),
                "sessao": f"clickup:{c['id']}", "kind": "externo",
                "txt": f"{onde} {ref}", "fonte": "clickup",
                "ancora": (ref.upper(), "clickup"),
            })

    _relatar(relatorio, tr.entrada_relatorio(fonte, eventos, lidas, aviso))
    return eventos


def _relatar(relatorio: list, entrada: dict) -> None:
    """Junto das fontes lidas, antes das lacunas (`sem adaptador`, resolução `—`)."""
    pos = next((i for i, f in enumerate(relatorio) if f["resolucao"] == "—"), len(relatorio))
    relatorio.insert(pos, entrada)


def montar_sugestao(inicio: Date, fim: Date, tz: ZoneInfo, agenda: Agenda,
                    token: str) -> dict:
    """Estrutura de dados da sugestão. É o contrato consumido pela skill."""
    import clickup_time_transcricao as tr

    relatorio: list = []
    eventos = tr.carregar_eventos(inicio, fim, tz, relatorio)
    dias = ler(inicio, fim, tz, agenda, token)

    # Os comentários do ClickUp só se acham task a task, então as candidatas saem
    # do que as outras fontes e a planilha já citam no período.
    citadas = {task for lista in tr.extrair_ancoras(eventos).values() for _, task, _, _ in lista}
    citadas |= {l.task_ref for d in dias for l in d.lancamentos if l.task_ref}
    eventos += eventos_comentarios(inicio, fim, tz, token, citadas, relatorio)
    eventos.sort(key=lambda e: (e["dt"], e["sessao"]))

    ancoras = tr.extrair_ancoras(eventos)
    tr.atribuir(eventos, ancoras)

    saida = {
        "timezone": str(tz),
        "sources": relatorio,
        "transcript_events": len(eventos),
        "anchors": sum(len(v) for v in ancoras.values()),
        "sessions": len(ancoras),
        "schedule": {
            "work_start": agenda.work_start.strftime("%H:%M"),
            "work_end": agenda.work_end.strftime("%H:%M"),
            "lunch_start": agenda.lunch_start.strftime("%H:%M"),
            "lunch_end": agenda.lunch_end.strftime("%H:%M"),
            "block_minutes": agenda.block_minutes,
            "target_minutes": agenda.target_minutes,
        },
        "days": [],
    }

    for dia in dias:
        if dia.data.weekday() > 4:
            continue
        vagas = livres(dia, agenda, tz)
        blocos = tr.sugerir(dia.data, eventos, vagas, agenda, tz) if vagas else []
        registro = {
            "date": dia.data.isoformat(),
            "weekday": DIAS_PT[dia.data.weekday()],
            "existing_minutes": dia.total_min(),
            "target_minutes": agenda.target_minutes,
            "missing_minutes": agenda.target_minutes - dia.total_min(),
            "free_windows": [
                {"start": a.strftime("%H:%M"), "end": b.strftime("%H:%M"),
                 "minutes": int((b - a).total_seconds() // 60)}
                for a, b in vagas
            ],
            # O que já está na planilha, para a tela mostrar o dia inteiro em
            # ordem: é isso que explica por que dois trechos da mesma task não
            # viraram um lançamento só (há um evento marcado entre eles).
            "existing": [
                {"start": l.inicio.strftime("%H:%M"),
                 "end": (l.fim or l.inicio).strftime("%H:%M"),
                 "minutes": l.duracao_min,
                 "task": l.task_ref or l.task_id,
                 "name": l.task_nome or "",
                 "id": l.id}
                for l in sorted(dia.lancamentos, key=lambda l: l.inicio)
                if not l.rodando
            ],
            "blocks": [],
        }
        for b in blocos:
            dur = int((b["fim"] - b["ini"]).total_seconds() // 60)
            item = {
                "start": b["ini"].strftime("%H:%M"),
                "end": b["fim"].strftime("%H:%M"),
                "minutes": dur,
                "events": b["n"],
                "task": b["task"],
            }
            if b["task"]:
                task, tipo, trecho, hora = b["evid"]
                item["anchor"] = {
                    "type": tipo,
                    "at": hora.strftime("%H:%M"),
                    "age_minutes": int((b["ini"] - hora).total_seconds() // 60),
                    "excerpt": trecho,
                }
                item["entry"] = f'{b["ini"]:%H:%M} {hm(dur)} {task}'
                if b.get("outras"):
                    item["other_evidence"] = [
                        {"at": dt.strftime("%H:%M"), "task": t, "type": tp, "excerpt": txt}
                        for dt, t, tp, txt in b["outras"]
                    ]
            else:
                item["reason"] = "sem_ancora" if b["n"] else "sem_atividade"
            registro["blocks"].append(item)
        saida["days"].append(registro)
    return saida


def comando_sugerir(inicio: Date, fim: Date, tz: ZoneInfo, agenda: Agenda,
                    token: str, como_json: bool = False) -> int:
    """Lê transcrições + ClickUp e propõe as linhas --entry. Nunca escreve."""
    dados = montar_sugestao(inicio, fim, tz, agenda, token)

    if como_json:
        json.dump(dados, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    print("\n\033[1mfontes varridas\033[0m")
    for f in dados["sources"]:
        cor = {"ok": "32", "sem adaptador": "33", "não instalado": "2"}.get(f["estado"], "33")
        detalhe = (f"{f['unidades']} {f.get('unidade','')}, {f['eventos']} eventos"
                   if f["estado"] == "ok" else f["estado"])
        print(f"  \033[{cor}m{f['nome']:<13}\033[0m {detalhe:<34} "
              f"\033[2mresolução: {f['resolucao']}\033[0m")
        if f.get("aviso"):
            print(f"  {'':<13} \033[33m{f['aviso']}\033[0m")
    print(f"\n\033[2m{dados['transcript_events']} eventos no total, "
          f"{dados['anchors']} âncoras em {dados['sessions']} sessão(ões)\033[0m")

    for d in dados["days"]:
        falta = d["missing_minutes"]
        print(f"\n\033[1m{d['weekday']}, {d['date'][8:10]}/{d['date'][5:7]}\033[0m  "
              f"apontado {hm(d['existing_minutes'])} / {hm(d['target_minutes'])}"
              + (f", falta {hm(falta)}" if falta > 0 else ""))
        if not d["blocks"]:
            print("  \033[2mdia completo\033[0m")
            continue
        for b in d["blocks"]:
            if b["task"]:
                a = b["anchor"]
                cor = {"url": "32", "fala": "36", "branch": "33",
                       "github": "35", "clickup": "34"}.get(a["type"], "0")
                selo = f"+{hm(a['age_minutes'])}" if a["age_minutes"] >= 60 else ""
                print(f'  --entry "{b["entry"]}"'.ljust(38)
                      + f"  \033[{cor}m{a['type']:<7}\033[0m {a['at']}"
                      + (f" \033[33m{selo:>5}\033[0m" if selo else "      ")
                      + f" \033[2m{a['excerpt'][:52]}\033[0m")
                for o in b.get("other_evidence", []):
                    print(f"{'':<40}\033[2mtambém: {o['type']} {o['at']} "
                          f"{o['task']} · {o['excerpt'][:48]}\033[0m")
            else:
                motivo = "sem âncora" if b["events"] else "sem atividade em nenhuma fonte"
                print(f'  --entry "{b["start"]} {hm(b["minutes"])} ???"'.ljust(38)
                      + f"  \033[31m{motivo}\033[0m"
                      + (f" \033[2m({b['events']} eventos)\033[0m" if b["events"] else ""))

    print("\n\033[2murl = link do ClickUp na sua fala · fala = HM-### na sua fala · "
          "branch = troca de branch em contexto git\033[0m")
    print("\033[2mgithub = push, PR, review ou comentário seu · "
          "clickup = comentário seu na task\033[0m")
    print("\033[2mresolva os ??? antes de passar as linhas para o `write`.\033[0m")
    link_planilha([Date.fromisoformat(d["date"]) for d in dados["days"]])
    return 0


def salvar_preview(
    dias_render: list[dict], agenda: Agenda, tz: ZoneInfo,
    caminho: str | None, comando: str | None = None, previa: bool = False,
) -> None:
    """Escreve o .html e imprime o caminho com o comando para abrir.

    Prévia e resultado gravado nunca disputam o mesmo arquivo: a prévia ganha o
    sufixo `-preview`, mesmo quando o caminho vem por `--html`. Assim os dois
    convivem lado a lado e dá para comparar o previsto com o que entrou.
    """
    import clickup_time_html

    if caminho is None:
        rotulo = dias_render[0]["dia"].data.isoformat()
        if len(dias_render) > 1:
            rotulo += f"_{dias_render[-1]['dia'].data.isoformat()}"
        caminho = os.path.join(tempfile.gettempdir(), f"apontamento-{rotulo}.html")

    if previa:
        raiz, ext = os.path.splitext(caminho)
        caminho = f"{raiz}-preview{ext or '.html'}"

    agora = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
    conteudo = clickup_time_html.gerar(dias_render, agenda, tz, comando, agora, previa)
    with open(caminho, "w", encoding="utf-8") as fh:
        fh.write(conteudo)

    print(f"\n\033[1m{'prévia' if previa else 'resultado'}:\033[0m {caminho}")
    print(f"  \033[2mopen {shlex.quote(caminho)}\033[0m")


def selar_fim(resposta: dict, c: "Candidato", token: str) -> None:
    """Reafirma o fim do lançamento recém-criado, via PUT.

    Por que existe: o POST **não** grava o campo de fim que a planilha lê, mesmo
    recebendo `end`. O sintoma é a coluna "Hora Final" mostrando "Data inválida",
    e ele é invisível pela API — o `GET` devolve `end` correto nos dois casos,
    porque o deriva de start+duration. Só a tela acusa.

    Em 11/09/2026 isso quebrou duas vezes: a primeira com `start`+`duration`, e a
    segunda depois de eu acrescentar `end` ao POST achando que bastava, porque o
    que tinha consertado os 15 lançamentos anteriores foi um PUT, não um POST.

    O PUT reenviando os mesmos valores é o caminho provado. Custa uma chamada a
    mais por lançamento e não tem como corromper: escreve de volta o que já está
    lá. Se um dia ficar claro qual campo o create respeita, isto sai.
    """
    dados = resposta.get("data") if isinstance(resposta, dict) else None
    if isinstance(dados, list):
        dados = dados[0] if dados else None
    entry_id = (dados or {}).get("id")
    if not entry_id:
        print("  \033[33m⚠ sem id na resposta: confira a Hora Final na planilha\033[0m")
        return
    api_put(
        f"/team/{WORKSPACE_ID}/time_entries/{entry_id}",
        {
            "start": int(c.inicio.timestamp() * 1000),
            "end": int(c.fim.timestamp() * 1000),
            "duration": c.duracao_min * 60000,
        },
        token,
    )


def escrever(
    dia: Date, entradas: list[str], tz: ZoneInfo, agenda: Agenda,
    token: str, confirmar: bool, html_path: str | None = None,
    comando: str | None = None,
) -> int:
    # Preflight: relê o dia AGORA, não confia em leitura anterior (CT-06.2).
    existente = ler(dia, dia, tz, agenda, token)[0]
    cands = montar_candidatos(dia, entradas, tz, agenda)

    for c in cands:
        try:
            c.task_id, custom, c.task_nome = resolver_task(c.ref, token)
            c.ref = custom or c.ref
        except Erro as e:
            c.bloquear(str(e))

    validar_candidatos(cands, existente, agenda, tz)

    print(f"\n\033[1m{DIAS_PT[dia.weekday()]}, {dia:%d/%m}\033[0m — "
          f"já apontado: {hm(existente.total_min())} / {hm(agenda.target_minutes)}")
    for c in cands:
        cor, rot = {
            "criar": ("32", "criar"),
            "ja_existe": ("2", "já existe"),
            "bloqueado": ("31", "BLOQUEADO"),
        }[c.estado]
        extra = f"  \033[2m{c.motivo}\033[0m" if c.motivo else ""
        print(f"  \033[{cor}m{rot:>9}\033[0m  {c.inicio:%H:%M}–{c.fim:%H:%M}  "
              f"{hm(c.duracao_min):>6}  {c.ref}  {c.task_nome[:40]}{extra}")

    bloqueados = [c for c in cands if c.estado == "bloqueado"]
    criar = [c for c in cands if c.estado == "criar"]

    if bloqueados:
        print(f"\n\033[31m{len(bloqueados)} entrada(s) bloqueada(s).\033[0m "
              "Nada foi escrito — concilie antes de repetir.")
        return 1
    if not criar:
        print("\nNada a criar: todas as entradas já existem.")
        return 0
    if not confirmar:
        novo = existente.total_min() + sum(c.duracao_min for c in criar)
        print(f"\ntotal do dia ficaria em {hm(novo)} / {hm(agenda.target_minutes)}")
        print("\033[33mPrévia.\033[0m Nada foi escrito — repita com \033[1m--confirm\033[0m.")
        salvar_preview([{"dia": existente, "novos": cands}], agenda, tz, html_path,
                       comando, previa=True)
        link_planilha([dia])
        return 0

    for c in criar:
        criado = api_post(
            f"/team/{WORKSPACE_ID}/time_entries",
            {
                # `end` é obrigatório na prática, embora a doc trate como
                # alternativa a `duration`. Em 11/09/2026 15 lançamentos foram
                # criados só com start+duration: a API devolvia `end` correto
                # (derivado), mas a coluna "Hora Final" da planilha mostrava
                # "Data inválida" — a UI lê o campo gravado, que ficava vazio.
                # Reenviar os mesmos valores com `end` explícito consertou os 15.
                "start": int(c.inicio.timestamp() * 1000),
                "end": int(c.fim.timestamp() * 1000),
                "duration": c.duracao_min * 60000,
                "tid": c.task_id,
            },
            token,
        )
        selar_fim(criado, c, token)
        print(f"  \033[32m✓ criado\033[0m  {c.inicio:%H:%M}  {c.ref}")

    # Conferência: relê o dia e mostra como ficou (duplicata, total, sobras).
    print("\n\033[1m— releitura após a escrita —\033[0m")
    final = ler(dia, dia, tz, agenda, token)
    imprimir(final, agenda, tz)
    salvar_preview([{"dia": final[0], "novos": None}], agenda, tz, html_path)
    link_planilha([dia])
    return 0


# --------------------------------------------------------------------- CLI


def parse_hora(s: str) -> time:
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except Exception:
        raise Erro(f"horário inválido: {s!r} (use HH:MM)") from None


def parse_data(s: str) -> Date:
    try:
        return Date.fromisoformat(s)
    except ValueError:
        raise Erro(f"data inválida: {s!r} (use AAAA-MM-DD)") from None


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="clickup-time.sh", add_help=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("read", help="lê os lançamentos de uma data ou intervalo")
    r.add_argument("--date")
    r.add_argument("--from", dest="de")
    r.add_argument("--to", dest="ate")
    r.add_argument("--timezone", default=TIMEZONE_PADRAO)
    r.add_argument("--work-start", default="08:00")
    r.add_argument("--work-end", default="18:00")
    r.add_argument("--lunch-start", default=f"{LUNCH_START:%H:%M}")
    r.add_argument("--lunch-end", default=f"{LUNCH_END:%H:%M}")
    r.add_argument("--block-minutes", type=int, default=BLOCK_MINUTES)
    r.add_argument("--target-minutes", type=int, default=TARGET_MINUTES)
    r.add_argument("--json", action="store_true", help="saída de máquina")
    r.add_argument("--html", nargs="?", const="", metavar="ARQUIVO",
                   help="gera preview .html (sem valor, escolhe um caminho em /tmp)")

    g = sub.add_parser("sugerir", help="propõe blocos a partir das transcrições")
    g.add_argument("--date")
    g.add_argument("--from", dest="de")
    g.add_argument("--to", dest="ate")
    g.add_argument("--timezone", default=TIMEZONE_PADRAO)
    g.add_argument("--work-start", default="08:00")
    g.add_argument("--work-end", default="18:00")
    g.add_argument("--lunch-start", default=f"{LUNCH_START:%H:%M}")
    g.add_argument("--lunch-end", default=f"{LUNCH_END:%H:%M}")
    g.add_argument("--block-minutes", type=int, default=BLOCK_MINUTES)
    g.add_argument("--target-minutes", type=int, default=TARGET_MINUTES)
    g.add_argument("--json", action="store_true", help="contrato de máquina")

    t = sub.add_parser("tarefas", help="lê nome, status e descrição de tasks (só leitura)")
    t.add_argument("refs", nargs="+", metavar="TASK", help="custom id (HM-423) ou id real")
    t.add_argument("--json", action="store_true", help="saída de máquina")
    t.add_argument("--max-chars", type=int, default=1500,
                   help="corte da descrição (padrão: 1500)")

    dg = sub.add_parser("digital", help="grava o token pelo clickup-token: leituras pedem a digital")
    dg.add_argument("--conferir", action="store_true",
                    help="só diz o que falta configurar, sem pedir nada")
    dg.add_argument("--compilar", action="store_true",
                    help="quem mantém a skill: gera bin/clickup-token (exige o Xcode)")

    f = sub.add_parser("front", help="front local opcional (só leitura)")
    f.add_argument("--timezone", default=TIMEZONE_PADRAO)
    f.add_argument("--work-start", default="08:00")
    f.add_argument("--work-end", default="18:00")
    f.add_argument("--lunch-start", default=f"{LUNCH_START:%H:%M}")
    f.add_argument("--lunch-end", default=f"{LUNCH_END:%H:%M}")
    f.add_argument("--block-minutes", type=int, default=BLOCK_MINUTES)
    f.add_argument("--target-minutes", type=int, default=TARGET_MINUTES)
    f.add_argument("--no-open", action="store_true", help="não abre o navegador")
    f.add_argument("--somente-leitura", action="store_true",
                   help="desliga o endpoint de escrita do front")
    f.add_argument("--plano", metavar="ARQUIVO",
                   help="JSON com a proposta do agente, por dia")
    f.add_argument("--fundo", action="store_true",
                   help="sobe em segundo plano, imprime a URL e devolve o terminal")
    f.add_argument("--parar", action="store_true",
                   help="encerra o front que está em segundo plano")

    w = sub.add_parser("write", help="cria lançamentos novos (exige --confirm)")
    w.add_argument("--date", required=True)
    w.add_argument("--entry", dest="entries", action="append", default=[],
                   metavar='"HH:MM DUR TASK"', help='ex: --entry "08:30 45m HM-240"')
    w.add_argument("--confirm", action="store_true", help="sem isto, só mostra a prévia")
    w.add_argument("--timezone", default=TIMEZONE_PADRAO)
    w.add_argument("--work-start", default="08:00")
    w.add_argument("--work-end", default="18:00")
    w.add_argument("--lunch-start", default=f"{LUNCH_START:%H:%M}")
    w.add_argument("--lunch-end", default=f"{LUNCH_END:%H:%M}")
    w.add_argument("--block-minutes", type=int, default=BLOCK_MINUTES)
    w.add_argument("--target-minutes", type=int, default=TARGET_MINUTES)
    w.add_argument("--html", nargs="?", const="", metavar="ARQUIVO",
                   help="onde salvar o preview (padrão: /tmp)")

    args = p.parse_args(argv)

    if args.cmd == "front":
        import clickup_time_front
        if args.parar:
            return clickup_time_front.parar()
        try:
            tz = ZoneInfo(args.timezone)
        except Exception:
            raise Erro(f"timezone inválida: {args.timezone!r}") from None
        agenda = Agenda(
            work_start=parse_hora(args.work_start),
            work_end=parse_hora(args.work_end),
            lunch_start=parse_hora(args.lunch_start),
            lunch_end=parse_hora(args.lunch_end),
            block_minutes=args.block_minutes,
            target_minutes=args.target_minutes,
        )
        agenda.validar()
        # O plano é validado antes do token: erro do agente no plano não deve
        # custar um diálogo do Keychain.
        # O front importa este arquivo como `clickup_time`, e aqui ele roda como
        # `__main__`: são duas classes `Erro`. Sem a tradução, plano recusado
        # sairia como traceback em vez da lista de problemas.
        try:
            plano = clickup_time_front.carregar_plano(args.plano, agenda) if args.plano else {}
        except clickup_time_front.ct.Erro as exc:
            raise Erro(str(exc)) from None
        return clickup_time_front.subir(tz, agenda, obter_token(),
                                        not args.no_open and not args.fundo,
                                        not args.somente_leitura, plano, args.fundo)

    if args.cmd == "digital":
        return comando_digital(args.conferir, args.compilar)

    if args.cmd == "tarefas":
        refs = [r.strip() for bruto in args.refs for r in bruto.split(",") if r.strip()]
        return comando_tarefas(refs, obter_token(), args.json, args.max_chars)

    if args.cmd == "write":
        if not args.entries:
            raise Erro('informe ao menos um --entry "HH:MM <duração> <task>"')
        try:
            tz = ZoneInfo(args.timezone)
        except Exception:
            raise Erro(f"timezone inválida: {args.timezone!r}") from None
        agenda = Agenda(
            work_start=parse_hora(args.work_start),
            work_end=parse_hora(args.work_end),
            lunch_start=parse_hora(args.lunch_start),
            lunch_end=parse_hora(args.lunch_end),
            block_minutes=args.block_minutes,
            target_minutes=args.target_minutes,
        )
        agenda.validar()
        # Parseia as entradas ANTES de pedir o token: erro de digitação não
        # deve custar um diálogo do Keychain.
        for bruta in args.entries:
            parse_entrada(bruta)
        comando = "./clickup-time.sh " + " ".join(shlex.quote(a) for a in argv)
        return escrever(parse_data(args.date), args.entries, tz, agenda,
                        obter_token(), args.confirm, args.html or None, comando)

    # Validação antes de qualquer chamada de rede (CT-01.4).
    if args.cmd == "sugerir":
        args.html = None
    if args.date and (args.de or args.ate):
        raise Erro("--date não combina com --from/--to")
    if bool(args.de) != bool(args.ate):
        raise Erro("intervalo exige --from e --to")
    if not args.date and not args.de:
        raise Erro("informe --date ou --from/--to")

    try:
        tz = ZoneInfo(args.timezone)
    except Exception:
        raise Erro(f"timezone inválida: {args.timezone!r}") from None

    if args.date:
        inicio = fim = parse_data(args.date)
    else:
        inicio, fim = parse_data(args.de), parse_data(args.ate)
    if fim < inicio:
        raise Erro("--to é anterior a --from")

    agenda = Agenda(
        work_start=parse_hora(args.work_start),
        work_end=parse_hora(args.work_end),
        lunch_start=parse_hora(args.lunch_start),
        lunch_end=parse_hora(args.lunch_end),
        block_minutes=args.block_minutes,
        target_minutes=args.target_minutes,
    )
    agenda.validar()

    if args.cmd == "sugerir":
        return comando_sugerir(inicio, fim, tz, agenda, obter_token(), args.json)

    dias = ler(inicio, fim, tz, agenda, obter_token())

    if args.json:
        json.dump(como_json(dias, agenda, tz), sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        imprimir(dias, agenda, tz)
        link_planilha([d.data for d in dias])
    if args.html is not None:
        salvar_preview([{"dia": d, "novos": None} for d in dias],
                       agenda, tz, args.html or None)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Erro as e:
        print(f"\033[31m[erro]\033[0m {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
