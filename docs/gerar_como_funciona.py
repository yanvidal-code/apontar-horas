#!/usr/bin/env python3
"""Gera docs/como-funciona.html e docs/figuras/*.svg a partir das figuras abaixo.

    python3 docs/gerar_como_funciona.py

As figuras são desenhadas aqui, à mão, em coordenadas: quando a skill mudar,
mude a figura e rode de novo. O HTML sai autocontido (sem fonte nem script de
fora) e abre offline; cada figura sai também como .svg avulso, em tema claro e
escuro, para slides.

Cores por quem faz: você, o agente (LLM), os scripts, o GitHub e o ClickUp. A
origem de um minuto herda a cor de quem a sustenta: âncora é do script,
inferência é do agente, "você disse" é sua; proximidade não tem dono.
"""

import html
import os
import re

AQUI = os.path.dirname(os.path.abspath(__file__))
FIGURAS_DIR = os.path.join(AQUI, "figuras")

CLARO = {
    "bg": "#F4F5F3", "surface": "#FFFFFF", "ink": "#1B2427", "muted": "#58656B",
    "rule": "#CBD2CE", "lane": "#E9ECE9",
    "voce": "#2350C4", "agente": "#7446BF", "scripts": "#1D7653", "github": "#4B5561",
    "clickup": "#B23F74", "segredo": "#A35F00", "prox": "#8E989C", "prox-bg": "#E3E7E5",
}
ESCURO = {
    "bg": "#111618", "surface": "#182024", "ink": "#E3E8E6", "muted": "#9AA7AC",
    "rule": "#35444A", "lane": "#182226",
    "voce": "#8FB0FF", "agente": "#BC9CF6", "scripts": "#55C593", "github": "#A9B4BF",
    "clickup": "#F08BB9", "segredo": "#E9A640", "prox": "#7D8A8F", "prox-bg": "#243034",
}

SANS = "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif"
MONO = "Menlo, 'SF Mono', Consolas, monospace"


def c(token):
    return f"var(--{token})"


def txt(x, y, s, size=12, weight=400, cor="ink", anchor="start", mono=False):
    fam = f' font-family="{MONO}"' if mono else ""
    return (f'<text x="{x:g}" y="{y:g}" font-size="{size}" font-weight="{weight}"'
            f' text-anchor="{anchor}"{fam} style="fill:{c(cor)}">{html.escape(s)}</text>')


def ret(x, y, w, h, fill="surface", stroke="rule", sw=1.2, rx=3, opac=None, tracejado=False):
    st = f"fill:{c(fill)}" if fill else "fill:none"
    if opac is not None:
        st += f";fill-opacity:{opac}"
    if stroke:
        st += f";stroke:{c(stroke)};stroke-width:{sw}"
    if tracejado:
        st += ";stroke-dasharray:3 3"
    return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx}" style="{st}"/>'


def seta(fig, d, cor="ink", tracejado=False, larg=1.4, inicio=False):
    dash = ";stroke-dasharray:5 4" if tracejado else ""
    ini = f' marker-start="url(#{fig}-seta-{cor})"' if inicio else ""
    return (f'<path d="{d}" style="fill:none;stroke:{c(cor)};stroke-width:{larg}{dash}"'
            f' marker-end="url(#{fig}-seta-{cor})"{ini}/>')


def marcadores(fig, cores):
    return [
        f'<marker id="{fig}-seta-{cor}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"'
        f' markerHeight="7" orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z"'
        f' style="fill:{c(cor)}"/></marker>'
        for cor in cores
    ]


def svg(w, h, rotulo, corpo, defs=()):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img"'
            f' aria-label="{html.escape(rotulo)}" font-family="{SANS}"'
            f' style="color:{c("ink")}">'
            f'<defs>{"".join(defs)}</defs>{"".join(corpo)}</svg>')


def caixa(cx, cy, linhas, cor="rule", w=124, h=56, forte=False):
    """Caixa centrada com 1 a 3 linhas: a primeira é o título, as outras, apoio."""
    out = [ret(cx - w / 2, cy - h / 2, w, h, stroke=cor, sw=2 if forte else 1.3)]
    n = len(linhas)
    base = cy - (n - 1) * 8 + 4
    for k, (s, mono) in enumerate(linhas):
        principal = k == 0
        out.append(txt(cx, base + k * 16, s, size=12.5 if principal else 11,
                       weight=(500 if mono else 600) if principal else 400,
                       cor=(cor if principal and cor != "rule" else ("ink" if principal else "muted")),
                       anchor="middle", mono=mono))
    return out


# ------------------------------------------------------------ figura 1


def figura_quem_faz():
    f = "f1"
    corpo = []
    faixas = [("voce", "Você", ["decide e grava"]),
              ("agente", "Agente (LLM)", ["lê e propõe;", "não grava sozinho"]),
              ("scripts", "Scripts", ["regra e trava"]),
              ("github", "GitHub", ["só leitura"]),
              ("clickup", "ClickUp", ["a planilha"])]
    topo, alt = 10, 100
    cy = {}
    for i, (chave, nome, sub) in enumerate(faixas):
        y = topo + i * alt
        corpo.append(ret(0, y, 1200, alt, fill=chave, stroke=None, rx=0, opac=0.07))
        corpo.append(f'<rect x="0" y="{y}" width="4" height="{alt}" style="fill:{c(chave)}"/>')
        centro = y + alt / 2
        cy[chave] = centro
        corpo.append(txt(18, centro - 6, nome, size=14, weight=600, cor=chave))
        for j, s in enumerate(sub):
            corpo.append(txt(18, centro + 12 + j * 14, s, size=11.5, cor="muted"))

    col = {i: 215 + (i - 1) * 150 for i in range(1, 8)}
    corpo += caixa(col[1], cy["voce"], [("./apontar ontem", True), ("1ª vez: configura a digital", False)], "voce")
    corpo += caixa(col[1], cy["agente"], [("/apontar", True), ("entende o período", False)], "agente")
    corpo += caixa(col[2], cy["scripts"], [("sugerir --json", True), ("lê transcrições e fontes", False)], "scripts")
    corpo += caixa(col[1], cy["github"], [("feed de eventos", False), ("push · PR · review", False)], "github")
    corpo += caixa(col[2], cy["clickup"], [("lançamentos", False), ("e comentários", False)], "clickup")
    corpo += caixa(col[3], cy["agente"], [("lê as sessões", False), ("resolve os ???", False),
                                          ("fecha os buracos", False)], "agente", h=64)
    corpo += caixa(col[4], cy["agente"], [("plano.json", True), ("task, origem e nota", False)], "agente")
    corpo += caixa(col[4], cy["scripts"], [("front local", False), ("valida o plano", False)], "scripts")
    corpo += caixa(col[5], cy["voce"], [("confere na tela", False), ("ajusta início e fim", False)], "voce")
    corpo += caixa(col[6], cy["voce"], [("Gravar", False), ("confirma duas vezes", False)], "voce", forte=True)
    corpo += caixa(col[6], cy["scripts"], [("revalida o dia", False), ("mesmas regras do write", False)], "scripts", forte=True)
    corpo += caixa(col[6], cy["clickup"], [("POST + PUT", True), ("sela a Hora Final", False)], "clickup", forte=True)
    corpo += caixa(col[7], cy["voce"], [("confere a planilha", False), ("o link sai no fim", False)], "voce")

    corpo.append(seta(f, "M215 88 V131"))
    corpo.append(txt(222, 124, "abre o Claude Code", size=11, cor="muted"))
    corpo.append(seta(f, "M277 160 H365 V231"))
    corpo.append(txt(321, 154, "roda", size=11, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M303 268 H215 V331"))
    corpo.append(txt(222, 300, "gh api", size=11, cor="muted", mono=True))
    corpo.append(seta(f, "M365 288 V431"))
    corpo.append(txt(372, 420, "lê (GET)", size=11, cor="muted"))
    corpo.append(seta(f, "M427 260 H515 V193"))
    corpo.append(txt(522, 203, "trechos com âncora", size=11, cor="muted"))
    corpo.append(txt(522, 217, "ou ???", size=11, cor="muted"))
    corpo.append(seta(f, "M577 160 H602"))
    corpo.append(seta(f, "M665 188 V231"))
    corpo.append(txt(672, 214, "front --plano", size=11, cor="muted", mono=True))
    corpo.append(seta(f, "M727 260 H815 V89"))
    corpo.append(txt(822, 155, "abre a tela", size=11, cor="muted"))
    corpo.append(txt(822, 169, "em 127.0.0.1", size=11, cor="muted"))
    corpo.append(seta(f, "M877 60 H902"))
    corpo.append(seta(f, "M965 88 V231", cor="voce", larg=2))
    corpo.append(txt(972, 152, "grava o dia", size=11.5, weight=600, cor="voce"))
    corpo.append(txt(972, 166, "sem passar pelo agente", size=11, cor="voce"))
    corpo.append(seta(f, "M965 288 V431", cor="voce", larg=2))
    corpo.append(txt(972, 372, "grava", size=11, cor="voce"))
    corpo.append(seta(f, "M1027 260 H1115 V89"))
    corpo.append(txt(1122, 180, "relê o dia", size=11, cor="muted"))
    corpo.append(txt(1122, 194, "e dá o link", size=11, cor="muted"))

    rotulo = ("Fluxo em cinco faixas: você, agente, scripts, GitHub e ClickUp. Os scripts leem "
              "transcrições, o GitHub e o ClickUp; o agente resolve o que exige leitura e escreve o "
              "plano; você confere e grava, e a gravação passa pelos scripts sem passar pelo agente.")
    return svg(1200, 520, rotulo, corpo, marcadores(f, ["ink", "voce"]))


# ------------------------------------------------------------ figura 2


def figura_fronteira():
    f = "f2"
    corpo = []
    corpo.append(ret(430, 0, 470, 470, fill="scripts", stroke=None, rx=0, opac=0.07))
    corpo.append(txt(446, 458, "DETERMINÍSTICO · PYTHON", size=10.5, weight=600, cor="scripts"))
    for xx in (320, 420):
        corpo.append(f'<line x1="{xx}" y1="40" x2="{xx}" y2="460"'
                     f' style="stroke:{c("rule")};stroke-width:1.2;stroke-dasharray:4 4"/>')
    corpo.append(txt(370, 404, "só comando", size=11, cor="muted", anchor="middle"))
    corpo.append(txt(370, 418, "e JSON;", size=11, cor="muted", anchor="middle"))
    corpo.append(txt(370, 438, "nunca o token", size=11, weight=600, cor="segredo", anchor="middle"))

    corpo.append(ret(20, 8, 220, 48, stroke="voce", sw=1.3))
    corpo.append(txt(130, 29, "Você", size=12.5, weight=600, cor="voce", anchor="middle"))
    corpo.append(txt(130, 46, "no chat e na tela", size=11, cor="muted", anchor="middle"))
    corpo.append(ret(20, 110, 280, 330, stroke="agente", sw=1.3))
    corpo.append(txt(36, 136, "LLM (o agente)", size=13.5, weight=600, cor="agente"))
    corpo.append(txt(36, 154, "faz o que exige leitura", size=11, cor="muted"))
    for k, s in enumerate(["resolve os ???", "junta fatias de sessões paralelas",
                           "liga PR e branch à task", "preenche buraco pela vizinha",
                           "escreve requisito e feito", "monta o plano, nota por trecho"]):
        corpo.append(txt(36, 186 + k * 24, "· " + s, size=12))
    corpo.append(txt(36, 360, "marca a origem de tudo:", size=11, cor="muted"))
    corpo.append(txt(36, 376, "usuario · ancora · inferencia", size=11, cor="muted", mono=True))
    corpo.append(txt(36, 392, "proximidade", size=11, cor="muted", mono=True))
    corpo.append(txt(36, 422, "não vê o token", size=11.5, weight=600, cor="segredo"))

    corpo.append(ret(440, 10, 280, 56, stroke="scripts", sw=1.3))
    corpo.append(txt(456, 32, "front local · 127.0.0.1", size=12.5, weight=600, cor="scripts"))
    corpo.append(txt(456, 50, "recusa plano sem nota ou fora da grade", size=11, cor="muted"))
    for y, titulo, subs, forte in [
        (100, "guarda de escrita", ["agenda, grade, almoço, sobreposição",
                                    "com qualquer bloqueio, nada entra"], True),
        (190, "leitura das fontes", ["agentes · GitHub · planilha · comentários"], False),
        (280, "âncoras e votação", ["regra fixa: mesma entrada, mesma saída"], False),
    ]:
        corpo.append(ret(440, y, 280, 60, stroke="scripts", sw=2 if forte else 1.3))
        corpo.append(txt(456, y + 22, titulo, size=12.5, weight=600, cor="scripts"))
        for k, sub in enumerate(subs):
            corpo.append(txt(456, y + 39 + k * 14, sub, size=11, cor="muted"))

    corpo.append(ret(760, 100, 130, 160, stroke="scripts", sw=1.3))
    corpo.append(txt(825, 124, "cliente HTTP", size=12.5, weight=600, cor="scripts", anchor="middle"))
    corpo.append(txt(825, 146, "o token só", size=11, cor="segredo", anchor="middle"))
    corpo.append(txt(825, 160, "existe aqui", size=11, cor="segredo", anchor="middle"))
    corpo.append(txt(825, 196, "GET: leitura", size=11, cor="muted", anchor="middle"))
    corpo.append(txt(825, 222, "POST + PUT:", size=11, cor="muted", anchor="middle"))
    corpo.append(txt(825, 236, "só pela guarda", size=11, cor="muted", anchor="middle"))

    corpo.append(ret(950, 115, 230, 60, stroke="clickup", sw=1.3))
    corpo.append(txt(966, 139, "API do ClickUp", size=12.5, weight=600, cor="clickup"))
    corpo.append(txt(966, 157, "lançamentos, tasks, comentários", size=11, cor="muted"))
    corpo.append(ret(950, 200, 230, 60, stroke="scripts", sw=1.3))
    corpo.append(txt(966, 224, "clickup-token", size=12.5, weight=600, cor="scripts", mono=True))
    corpo.append(txt(966, 242, "digital, depois o Keychain", size=11, cor="muted"))
    corpo.append(ret(950, 300, 230, 50, stroke="github", sw=1.3))
    corpo.append(txt(966, 321, "GitHub", size=12.5, weight=600, cor="github"))
    corpo.append(txt(966, 339, "feed de eventos, só leitura", size=11, cor="muted"))

    corpo.append(seta(f, "M240 26 H439"))
    corpo.append(txt(340, 20, "confere e grava", size=11, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M130 56 V109"))
    corpo.append(txt(137, 88, "pede e aprova", size=11, cor="muted"))
    corpo.append(seta(f, "M280 110 V58 H439"))
    corpo.append(txt(370, 52, "plano.json", size=11, anchor="middle", mono=True))
    corpo.append(seta(f, "M580 66 V99", cor="voce", larg=2))
    corpo.append(txt(587, 88, "Gravar", size=11, weight=600, cor="voce"))
    corpo.append(seta(f, "M300 118 H439"))
    corpo.append(txt(370, 112, "write · prévia", size=10.5, anchor="middle", mono=True))
    corpo.append(seta(f, "M300 146 H439", cor="voce", tracejado=True, larg=1.6))
    corpo.append(txt(370, 140, "write --confirm", size=10.5, cor="voce", anchor="middle", mono=True))
    corpo.append(txt(370, 162, "só depois do seu", size=10.5, cor="voce", anchor="middle"))
    corpo.append(txt(370, 175, "“pode gravar”", size=10.5, cor="voce", anchor="middle"))
    corpo.append(seta(f, "M300 216 H439"))
    corpo.append(txt(370, 198, "sugerir --json", size=10.5, anchor="middle", mono=True))
    corpo.append(txt(370, 210, "tarefas --json", size=10.5, anchor="middle", mono=True))
    corpo.append(seta(f, "M580 250 V279"))
    corpo.append(txt(587, 269, "eventos", size=11, cor="muted"))
    corpo.append(seta(f, "M440 312 H301"))
    corpo.append(txt(370, 328, "trechos, âncoras,", size=10.5, anchor="middle"))
    corpo.append(txt(370, 341, "“também”, tasks", size=10.5, anchor="middle"))
    corpo.append(seta(f, "M720 130 H759", cor="voce", larg=2))
    corpo.append(txt(740, 124, "grava", size=10.5, cor="voce", anchor="middle"))
    corpo.append(seta(f, "M720 220 H759"))
    corpo.append(txt(740, 214, "lê", size=10.5, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M720 240 H740 V325 H949"))
    corpo.append(txt(845, 319, "gh api", size=10.5, cor="muted", anchor="middle", mono=True))
    corpo.append(seta(f, "M890 145 H949"))
    corpo.append(txt(920, 139, "HTTPS", size=10.5, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M950 230 H891", cor="segredo"))
    corpo.append(txt(920, 224, "token", size=10.5, cor="segredo", anchor="middle"))

    rotulo = ("O LLM fica de um lado e o script determinístico do outro; entre eles só passam "
              "comandos e JSON. O token vive só no cliente HTTP do script; o GitHub é lido pelo gh. "
              "A escrita passa sempre pela guarda: pelo botão Gravar ou por write --confirm depois "
              "do seu pode gravar.")
    return svg(1200, 470, rotulo, corpo, marcadores(f, ["ink", "voce", "segredo"]))


# ------------------------------------------------------------ figura 3


def figura_arquivos():
    f = "f3"
    corpo = []

    def no(x, y, w, h, cor, titulo, subs, mono=True, forte=False, tam=12.5):
        out = [ret(x, y, w, h, stroke=cor, sw=2 if forte else 1.3)]
        out.append(txt(x + 14, y + 22, titulo, size=tam, weight=600,
                       cor="ink" if cor == "rule" else cor, mono=mono))
        for k, s in enumerate(subs):
            out.append(txt(x + 14, y + 40 + k * 15, s, size=11, cor="muted"))
        return out

    corpo += no(20, 30, 180, 60, "voce", "apontar", ["você roda no terminal"])
    corpo += no(20, 200, 180, 100, "agente", "Claude Code", ["segue o SKILL.md", "e o comando /apontar;", "roda os comandos"], mono=False)
    corpo += no(250, 220, 160, 60, "scripts", "clickup-time.sh", ["acha a pasta da skill"])
    corpo.append(ret(460, 100, 260, 300, stroke="scripts", sw=2))
    corpo.append(txt(476, 124, "clickup_time.py", size=13.5, weight=600, cor="scripts", mono=True))
    corpo.append(txt(476, 141, "CLI e núcleo", size=11, cor="muted"))
    itens = [("read · sugerir · tarefas", True), ("write · front · digital", True),
             ("agenda e grade de 15 min", False), ("comentários do ClickUp", False),
             ("guarda de escrita", False), ("instala o clickup-token", False),
             ("único cliente HTTP", False)]
    for k, (s, mono) in enumerate(itens):
        corpo.append(txt(476, 170 + k * 21, s, size=11.5 if mono else 12, mono=mono))
    for k, s in enumerate(["montar_sugestao()", "validar_candidatos()", "escrever() · obter_token()"]):
        corpo.append(txt(476, 334 + k * 16, s, size=10.5, cor="muted", mono=True))

    corpo += no(780, 30, 210, 90, "scripts", "clickup_time_transcricao.py", ["transcrições e GitHub", "âncoras e votação"], tam=11.5)
    corpo += no(780, 165, 210, 80, "scripts", "clickup_time_front.py", ["tela em 127.0.0.1", "grava pela guarda"], tam=11.5)
    corpo += no(780, 280, 210, 60, "scripts", "clickup_time_html.py", ["prévia .html offline"], tam=11.5)
    corpo += no(780, 370, 210, 70, "scripts", "bin/clickup-token", ["digital + Keychain", "pronto; fonte em .swift"], tam=11.5)
    corpo += no(460, 440, 260, 50, "clickup", "API do ClickUp", ["lançamentos, tasks, comentários"], mono=False)

    corpo += no(1030, 20, 150, 50, "agente", "transcrições", ["~/.claude · ~/.codex …"], mono=False)
    corpo += no(1030, 80, 150, 50, "github", "GitHub", ["gh api, só leitura"], mono=False)
    corpo += no(1030, 180, 150, 50, "voce", "navegador", ["você confere e grava"], mono=False)
    corpo += no(1030, 285, 150, 50, "rule", "arquivo .html", ["na pasta temporária"], mono=False)
    corpo += no(1030, 380, 150, 50, "rule", "Keychain", ["clickup-irrah-tech"], mono=False)

    corpo.append(seta(f, "M200 60 H330 V219"))
    corpo.append(txt(265, 52, "digital --conferir", size=10.5, cor="muted", anchor="middle", mono=True))
    corpo.append(seta(f, "M110 90 V199"))
    corpo.append(txt(117, 150, "claude /apontar", size=10.5, cor="muted", mono=True))
    corpo.append(seta(f, "M200 250 H249"))
    corpo.append(txt(225, 244, "roda", size=10.5, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M410 250 H459"))
    corpo.append(txt(435, 244, "python3", size=10, cor="muted", anchor="middle", mono=True))
    corpo.append(seta(f, "M720 110 H779"))
    corpo.append(txt(750, 104, "lê", size=10.5, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M990 45 H1029"))
    corpo.append(seta(f, "M990 105 H1029"))
    corpo.append(seta(f, "M720 195 H779"))
    corpo.append(txt(750, 189, "sobe", size=10.5, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M780 222 H721"))
    corpo.append(txt(750, 238, "grava", size=10.5, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M990 205 H1029"))
    corpo.append(seta(f, "M720 310 H779"))
    corpo.append(txt(750, 304, "prévia", size=10.5, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M990 310 H1029"))
    corpo.append(seta(f, "M720 390 H779", cor="segredo"))
    corpo.append(txt(750, 384, "token", size=10.5, cor="segredo", anchor="middle"))
    corpo.append(seta(f, "M990 405 H1029"))
    corpo.append(seta(f, "M590 400 V439"))
    corpo.append(txt(597, 424, "HTTPS", size=10.5, cor="muted"))

    rotulo = ("Mapa dos arquivos da skill: o apontar abre o Claude Code, que roda o clickup-time.sh, "
              "que chama o clickup_time.py; este usa o módulo de transcrições e GitHub, o front, a "
              "prévia em HTML e o clickup-token, e é o único que fala com a API do ClickUp.")
    return svg(1200, 500, rotulo, corpo, marcadores(f, ["ink", "segredo"]))


# ------------------------------------------------------------ figura 4


def figura_trecho():
    f = "f4"
    corpo = []

    def fonte(y, h, cor, titulo, subs, mono=False):
        out = [ret(20, y, 220, h, stroke=cor, sw=1.3)]
        out.append(txt(36, y + 22, titulo, size=13, weight=600, cor=cor))
        for k, s in enumerate(subs):
            out.append(txt(36, y + 40 + k * 16, s, size=11, cor="muted", mono=mono))
        return out

    corpo += fonte(34, 80, "agente", "Transcrições", ["claude-code · codex", "grok · opencode"], mono=True)
    corpo += fonte(146, 46, "github", "GitHub", ["push · PR · review · comentário"])
    corpo += fonte(200, 46, "clickup", "ClickUp", ["seus comentários nas tasks"])
    corpo += fonte(300, 50, "clickup", "Planilha", ["o que já está lançado"])

    corpo.append(ret(310, 20, 270, 108, fill="lane", stroke=None))
    corpo.append(txt(326, 40, "ÂNCORAS DA CONVERSA", size=10.5, weight=600, cor="muted"))
    for k, (tag, s) in enumerate([("url", "link do ClickUp na sua fala"),
                                  ("fala", "HM-### na sua fala"),
                                  ("branch", "troca de branch")]):
        corpo.append(txt(326, 62 + k * 18, tag, size=12, weight=500, mono=True, cor="agente"))
        corpo.append(txt(386, 62 + k * 18, s, size=12))
    corpo.append(txt(326, 118, "valem até a próxima da sessão, no dia", size=11, cor="muted"))
    corpo.append(ret(310, 146, 270, 100, fill="lane", stroke=None))
    corpo.append(txt(326, 166, "ÂNCORAS DE AÇÃO SUA", size=10.5, weight=600, cor="muted"))
    corpo.append(txt(326, 188, "github", size=12, weight=500, mono=True, cor="github"))
    corpo.append(txt(386, 188, "branch ou título do PR", size=12))
    corpo.append(txt(326, 206, "clickup", size=12, weight=500, mono=True, cor="clickup"))
    corpo.append(txt(386, 206, "a task do comentário", size=12))
    corpo.append(txt(326, 234, "valem só no próprio instante", size=11, cor="muted"))

    corpo.append(seta(f, "M240 74 H309"))
    corpo.append(seta(f, "M240 169 H309"))
    corpo.append(seta(f, "M240 223 H309"))

    corpo.append(ret(660, 20, 290, 242, stroke="scripts", sw=1.3))
    corpo.append(txt(676, 44, "Um trecho de 15 min", size=13.5, weight=600, cor="scripts"))
    corpo.append(txt(676, 62, "exemplo: 13:45–14:00", size=11, cor="muted"))
    x0, px = 680, 250 / 15
    corpo.append(f'<line x1="{x0}" y1="120" x2="{x0 + 250}" y2="120" style="stroke:{c("ink")};stroke-width:1.2"/>')
    for m, rot in [(0, "13:45"), (5, "13:50"), (10, "13:55"), (15, "14:00")]:
        xx = x0 + m * px
        corpo.append(f'<line x1="{xx:g}" y1="115" x2="{xx:g}" y2="125" style="stroke:{c("ink")};stroke-width:1.2"/>')
        corpo.append(txt(xx, 140, rot, size=10.5, cor="muted", anchor="middle", mono=True))
    for m, r, cor in [(1, 5, "agente"), (2, 5, "agente"), (3, 5, "agente"), (5, 3.5, "agente"),
                      (6, 3.5, "agente"), (8, 5, "clickup")]:
        corpo.append(f'<circle cx="{x0 + m * px:g}" cy="104" r="{r}" style="fill:{c(cor)}"/>')
    corpo.append(txt(680, 88, "sessão da HM-370", size=11, cor="agente"))
    corpo.append(txt(800, 88, "comentário · HM-253", size=11, cor="clickup"))
    for k, (task, pontos, cor) in enumerate([("HM-370", 42, "agente"), ("HM-253", 12, "clickup")]):
        y = 164 + k * 24
        corpo.append(txt(680, y + 11, task, size=11.5, weight=500, mono=True, cor=cor))
        corpo.append(ret(740, y, pontos * 3.5, 14, fill=cor, stroke=None, rx=1))
        corpo.append(txt(740 + pontos * 3.5 + 8, y + 11, str(pontos), size=11.5, weight=600, cor=cor, mono=True))
    corpo.append(txt(676, 228, "peso: fala 12 · ação sua 12", size=11, cor="muted"))
    corpo.append(txt(676, 244, "resposta 3 · ferramenta 2 · saída 1", size=11, cor="muted"))

    corpo.append(seta(f, "M580 74 H659"))
    corpo.append(seta(f, "M580 196 H659"))
    corpo.append(txt(620, 128, "cada evento", size=11, cor="muted", anchor="middle"))
    corpo.append(txt(620, 142, "vota", size=11, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M240 325 H805 V263"))
    corpo.append(txt(420, 317, "só as faixas livres: fora do almoço e do que já está lançado",
                     size=11, cor="muted", anchor="middle"))

    corpo.append(ret(1010, 40, 180, 72, stroke="scripts", sw=1.3))
    corpo.append(txt(1026, 64, "HM-370", size=14, weight=500, mono=True))
    corpo.append(txt(1026, 82, "13:45–14:00 · âncora", size=11, cor="muted"))
    corpo.append(txt(1026, 98, "fala das 13:46", size=11, cor="muted"))
    corpo.append(txt(1026, 134, "também: clickup 13:53", size=11, cor="clickup"))
    corpo.append(txt(1026, 150, "HM-253", size=11, cor="clickup", mono=True))
    corpo.append(ret(1010, 188, 180, 66, stroke="rule", tracejado=True))
    corpo.append(txt(1026, 212, "???", size=14, weight=500, mono=True))
    corpo.append(txt(1026, 230, "nenhum voto:", size=11, cor="muted"))
    corpo.append(txt(1026, 245, "o agente lê e resolve", size=11, cor="agente"))

    corpo.append(seta(f, "M950 76 H1009"))
    corpo.append(txt(980, 94, "maior", size=11, cor="muted", anchor="middle"))
    corpo.append(txt(980, 107, "soma", size=11, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M950 221 H1009", tracejado=True))
    corpo.append(txt(980, 239, "sem voto", size=11, cor="muted", anchor="middle"))

    rotulo = ("Transcrições, GitHub e ClickUp viram âncoras; cada evento de um trecho de 15 minutos "
              "vota na task da âncora vigente, com peso por tipo; a maior soma leva o trecho, e a "
              "ação sua que perdeu vai junto como também. Trecho sem voto sai como ???.")
    return svg(1200, 362, rotulo, corpo, marcadores(f, ["ink"]))


# ------------------------------------------------------------ figura 5


def figura_dia():
    f = "f5"
    x0, px = 110, 1.75

    def x(hhmm):
        h, m = map(int, hhmm.split(":"))
        return x0 + ((h - 8) * 60 + m) * px

    defs = [f'<pattern id="{f}-prox" width="6" height="6" patternUnits="userSpaceOnUse"'
            f' patternTransform="rotate(45)"><rect width="6" height="6" style="fill:{c("prox-bg")}"/>'
            f'<rect width="2.6" height="6" style="fill:{c("prox")}"/></pattern>']
    cor = {"ancora": c("scripts"), "infer": c("agente"), "usuario": c("voce"), "prox": f"url(#{f}-prox)"}
    corpo = [txt(16, 97, "proposta", size=12.5, weight=600), txt(16, 169, "evidência", size=12.5, weight=600)]

    lancamentos = [
        ("HM-445", [("08:00", "08:15", "prox"), ("08:15", "08:45", "ancora")]),
        ("Daily", [("08:45", "09:00", "usuario")]),
        ("HM-445", [("09:00", "10:00", "ancora")]),
        ("HM-383", [("10:00", "10:45", "ancora")]),
        ("HM-392", [("10:45", "11:00", "ancora")]),
        ("HM-416", [("11:00", "12:00", "infer")]),
        ("HM-370", [("13:30", "13:45", "prox"), ("13:45", "15:30", "ancora")]),
        ("HM-426", [("15:30", "16:15", "ancora")]),
        ("HM-445", [("16:15", "17:15", "ancora"), ("17:15", "18:00", "prox")]),
    ]
    y, h = 72, 40
    for nome, trechos in lancamentos:
        fim_l = trechos[-1][1]
        folga = 0 if fim_l in ("12:00", "18:00") else 1.5
        for a, b, org in trechos:
            xb = x(b) - (folga if b == fim_l else 0)
            corpo.append(f'<rect x="{x(a):g}" y="{y}" width="{xb - x(a):g}" height="{h}" style="fill:{cor[org]}"/>')
        corpo.append(txt((x(trechos[0][0]) + x(fim_l)) / 2, 62, nome, size=11.5, weight=500,
                         anchor="middle", mono=True))
    corpo.append(ret(x("12:00"), y, x("13:30") - x("12:00"), h, fill="lane", stroke="rule", sw=1, rx=0,
                     tracejado=True))
    corpo.append(txt((x("12:00") + x("13:30")) / 2, 96, "almoço · não é marcado", size=11,
                     cor="muted", anchor="middle"))

    base = y + h
    for m in range(0, 601, 15):
        xx = x0 + m * px
        hora = m % 60 == 0
        corpo.append(f'<line x1="{xx:g}" y1="{base}" x2="{xx:g}" y2="{base + (8 if hora else 4)}"'
                     f' style="stroke:{c("ink" if hora else "muted")};stroke-width:1"/>')
        if hora:
            corpo.append(txt(xx, base + 22, f"{8 + m // 60:02d}:00", size=10.5, cor="muted",
                             anchor="middle", mono=True))

    evid = [("08:21", "url 08:21", 1, "middle", 0, "agente"),
            ("10:04", "branch 10:04", 1, "middle", 0, "agente"),
            ("10:58", "github 10:58", 1, "middle", 0, "github"),
            ("13:46", "fala 13:46", 1, "end", -4, "agente"),
            ("13:53", "clickup 13:53 · HM-253, em “também”", 2, "start", -6, "clickup"),
            ("15:23", "url 15:23", 1, "middle", 0, "agente"),
            ("16:20", "fala 16:20", 1, "middle", 0, "agente")]
    for hhmm, rot, linha, anc, dx, cr in evid:
        xx = x(hhmm)
        corpo.append(f'<line x1="{xx:g}" y1="142" x2="{xx:g}" y2="160"'
                     f' style="stroke:{c("rule")};stroke-width:1;stroke-dasharray:2 2"/>')
        corpo.append(f'<circle cx="{xx:g}" cy="165" r="4" style="fill:{c(cr)}"/>')
        corpo.append(txt(xx + dx, 188 if linha == 1 else 204, rot, size=11, cor=cr, anchor=anc))
    a, b = x("11:00") + 5, x("12:00") - 5
    corpo.append(f'<path d="M{a:g} 160 V165 H{b:g} V160" style="fill:none;stroke:{c("agente")};stroke-width:1.4"/>')
    corpo.append(txt((a + b) / 2, 204, "o agente leu a sessão", size=11, cor="agente", anchor="middle"))

    lx = x0
    for org, nome, total in [("ancora", "âncora", "6h00"), ("infer", "inferência", "1h00"),
                             ("usuario", "você disse", "0h15"), ("prox", "proximidade", "1h15")]:
        corpo.append(f'<rect x="{lx:g}" y="236" width="16" height="11" style="fill:{cor[org]}"/>')
        corpo.append(txt(lx + 22, 246, nome, size=12, weight=600))
        corpo.append(txt(lx + 22 + len(nome) * 6.6 + 6, 246, total, size=12, cor="muted", mono=True))
        lx += 190
    corpo.append(txt(1160, 246, "8h30 no dia = meta", size=12, weight=600, anchor="end"))

    rotulo = ("Linha do tempo de 08:00 a 18:00 com os lançamentos propostos coloridos pela origem: "
              "6h00 de âncora, 1h00 de inferência, 0h15 que você disse (a Daily) e 1h15 de "
              "proximidade, somando a meta de 8h30; o almoço de 12:00 a 13:30 não é marcado.")
    return svg(1200, 262, rotulo, corpo, defs)


# ------------------------------------------------------------ figura 6


def figura_token():
    f = "f6"
    corpo = []
    corpo.append(ret(20, 45, 180, 50, stroke="voce", sw=1.3))
    corpo.append(txt(110, 66, "Você, no terminal", size=12.5, weight=600, cor="voce", anchor="middle"))
    corpo.append(txt(110, 83, "./apontar na 1ª vez", size=11, cor="muted", anchor="middle", mono=True))
    corpo.append(ret(260, 175, 180, 50, stroke="scripts", sw=1.3))
    corpo.append(txt(350, 196, "Scripts Python", size=12.5, weight=600, cor="scripts", anchor="middle"))
    corpo.append(txt(350, 213, "sugerir, front, write", size=11, cor="muted", anchor="middle"))
    corpo.append(ret(20, 175, 180, 50, stroke="clickup", sw=1.3))
    corpo.append(txt(110, 196, "API do ClickUp", size=12.5, weight=600, cor="clickup", anchor="middle"))
    corpo.append(txt(110, 213, "token só no header", size=11, cor="muted", anchor="middle"))
    corpo.append(ret(260, 302, 180, 66, stroke="agente", sw=1.3))
    corpo.append(txt(350, 322, "Agente", size=12.5, weight=600, cor="agente", anchor="middle"))
    corpo.append(txt(350, 339, "vê só o JSON", size=11, cor="muted", anchor="middle"))
    corpo.append(txt(350, 355, "o digital recusa sem terminal", size=11, cor="muted", anchor="middle"))

    corpo.append(txt(500, 22, "clickup-token", size=13.5, weight=600, cor="scripts", mono=True))
    corpo.append(txt(620, 22, "vem pronto em bin/, universal", size=11, cor="muted"))
    corpo.append(ret(500, 30, 220, 220, stroke="scripts", sw=1.3))
    corpo.append(f'<line x1="500" y1="140" x2="720" y2="140" style="stroke:{c("rule")};stroke-width:1.2"/>')
    corpo.append(txt(516, 60, "gravar", size=13, weight=600, mono=True))
    corpo.append(txt(516, 78, "1ª vez ou troca de token", size=11, cor="muted"))
    corpo.append(txt(516, 172, "ler", size=13, weight=600, mono=True))
    corpo.append(txt(516, 190, "cada execução", size=11, cor="muted"))

    corpo.append(ret(880, 30, 260, 220))
    corpo.append(txt(896, 58, "Keychain", size=13.5, weight=600))
    corpo.append(txt(896, 78, "clickup-irrah-tech", size=11.5, cor="muted", mono=True))
    corpo.append(txt(896, 112, "lista de confiança:", size=12))
    corpo.append(txt(896, 128, "só o clickup-token,", size=12, weight=600))
    corpo.append(txt(896, 144, "pelo hash do binário", size=12))

    corpo.append(ret(535, 300, 150, 50, stroke="segredo", sw=2))
    corpo.append(txt(610, 321, "Touch ID", size=12.5, weight=600, anchor="middle", cor="segredo"))
    corpo.append(txt(610, 338, "LocalAuthentication", size=10.5, cor="muted", anchor="middle", mono=True))
    corpo.append(ret(880, 305, 260, 50, stroke="rule", tracejado=True))
    corpo.append(txt(1010, 326, "security e outros apps", size=12.5, weight=600, anchor="middle"))
    corpo.append(txt(1010, 343, "caem no diálogo de senha", size=11, cor="muted", anchor="middle"))

    corpo.append(seta(f, "M200 70 H499"))
    corpo.append(txt(350, 62, "token, sem eco", size=11, cor="segredo", anchor="middle"))
    corpo.append(seta(f, "M720 70 H879"))
    corpo.append(txt(800, 62, "grava o item", size=11, cor="muted", anchor="middle"))
    corpo.append(txt(800, 86, "confiando só nele", size=11, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M440 192 H499"))
    corpo.append(txt(470, 186, "ler", size=11, cor="muted", anchor="middle", mono=True))
    corpo.append(seta(f, "M500 212 H441", cor="segredo"))
    corpo.append(txt(470, 228, "token", size=11, cor="segredo", anchor="middle"))
    corpo.append(seta(f, "M720 200 H879"))
    corpo.append(txt(800, 194, "lê sem diálogo", size=11, cor="muted", anchor="middle"))
    corpo.append(txt(800, 214, "(mesmo hash)", size=11, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M610 251 V299", cor="segredo", larg=1.8, inicio=True))
    corpo.append(txt(618, 279, "digital antes de ler", size=11, cor="segredo"))
    corpo.append(seta(f, "M1010 304 V251", cor="muted", tracejado=True))
    corpo.append(txt(1018, 282, "só com a senha", size=11, cor="muted"))
    corpo.append(seta(f, "M260 200 H201"))
    corpo.append(txt(230, 192, "header", size=11, cor="muted", anchor="middle"))
    corpo.append(seta(f, "M350 225 V301"))
    corpo.append(txt(358, 266, "só o JSON", size=11, cor="muted"))

    rotulo = ("O token entra uma vez pelo seu terminal e o clickup-token, que vem pronto com a skill, "
              "grava o item confiando só no próprio hash; cada leitura pede a digital; o agente "
              "recebe só o JSON; o security e outros apps só leem com a senha do chaveiro.")
    return svg(1200, 380, rotulo, corpo, marcadores(f, ["ink", "segredo", "muted"]))


FIGURAS = [
    ("figura-1-quem-faz-o-que", figura_quem_faz),
    ("figura-2-script-e-llm", figura_fronteira),
    ("figura-3-arquivos", figura_arquivos),
    ("figura-4-como-um-trecho-ganha-task", figura_trecho),
    ("figura-5-um-dia-proposto", figura_dia),
    ("figura-6-caminho-do-token", figura_token),
]


def avulso(inline: str, tema: dict) -> str:
    s = re.sub(r"var\(--([a-z-]+)\)", lambda m: tema[m.group(1)], inline)
    # fundo explícito: fora da página não há body pintando atrás
    vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', s)
    fundo = f'<rect width="{vb.group(1)}" height="{vb.group(2)}" fill="{tema["bg"]}"/>'
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + s.replace("</defs>", "</defs>" + fundo, 1) + "\n"


def tokens_css(tema: dict) -> str:
    return " ".join(f"--{k}:{v};" for k, v in tema.items())


if __name__ == "__main__":
    os.makedirs(FIGURAS_DIR, exist_ok=True)
    pagina = open(os.path.join(AQUI, "como-funciona.modelo.html")).read()
    pagina = pagina.replace("{{tokens-claro}}", tokens_css(CLARO)).replace("{{tokens-escuro}}", tokens_css(ESCURO))
    for nome, gerar in FIGURAS:
        s = gerar()
        for sufixo, tema in (("", CLARO), ("-escuro", ESCURO)):
            with open(os.path.join(FIGURAS_DIR, f"{nome}{sufixo}.svg"), "w") as fh:
                fh.write(avulso(s, tema))
        pagina = pagina.replace("{{" + nome + "}}", s)
    assert "{{" not in pagina, re.findall(r"\{\{[^}]+\}\}", pagina)
    with open(os.path.join(AQUI, "como-funciona.html"), "w") as fh:
        fh.write(pagina)
    print(f"docs/como-funciona.html e {len(FIGURAS) * 2} svg em docs/figuras/")
