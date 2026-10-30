#!/usr/bin/env python3
"""clickup_time_html.py — preview HTML do apontamento, arquivo único e offline.

Gera um .html autocontido: sem script, sem imagem externa, sem fetch. A única
referência remota é a folha do Google Fonts; abrindo sem rede ela falha em
silêncio e o fallback de sistema assume, então o arquivo continua legível.

Dois trilhos sobre o mesmo eixo do expediente: o que já está no ClickUp
("antes") e como o dia ficaria ("depois"). Âncora, bloco novo e almoço têm
tratamento visual distinto — a diferença tem que ler de longe, não pela legenda.
"""

from __future__ import annotations

import html
from datetime import date as Date
from datetime import datetime, timedelta

DIAS_EXTENSO = [
    "Segunda-feira", "Terça-feira", "Quarta-feira",
    "Quinta-feira", "Sexta-feira", "Sábado", "Domingo",
]

CSS = """
:root{--ground:#f2f4f7;--surface:#fff;--ink:#171b22;--ink-soft:#5d6672;--ink-faint:#8d96a3;
--rule:#d9dfe7;--rule-soft:#e8ecf1;--ancora:#59616e;--ancora-bg:#e7eaee;--novo:#1f6a58;
--novo-bg:#d5e9e2;--almoco:#c8cfd8;
--sombra:0 1px 2px rgba(23,27,34,.06),0 8px 24px -12px rgba(23,27,34,.18)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ground:#101317;
--surface:#181c22;--ink:#e8ecf1;--ink-soft:#9aa4b2;--ink-faint:#6d7683;--rule:#2b313a;
--rule-soft:#232830;--ancora:#9aa4b2;--ancora-bg:#2a3038;--novo:#6fcfb4;--novo-bg:#1b3b34;
--almoco:#2f353d;--sombra:0 1px 2px rgba(0,0,0,.4),0 8px 24px -12px rgba(0,0,0,.6)}}
:root[data-theme="dark"]{--ground:#101317;--surface:#181c22;--ink:#e8ecf1;--ink-soft:#9aa4b2;
--ink-faint:#6d7683;--rule:#2b313a;--rule-soft:#232830;--ancora:#9aa4b2;--ancora-bg:#2a3038;
--novo:#6fcfb4;--novo-bg:#1b3b34;--almoco:#2f353d;
--sombra:0 1px 2px rgba(0,0,0,.4),0 8px 24px -12px rgba(0,0,0,.6)}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-size:16px;line-height:1.5;
font-family:Archivo,-apple-system,"SF Pro Text","Helvetica Neue",Arial,sans-serif;
-webkit-font-smoothing:antialiased}
.pagina{max-width:60rem;margin:0 auto;padding:3rem 1.5rem 5rem;display:flex;
flex-direction:column;gap:2.5rem}
.rotulo{font-size:.688rem;font-weight:600;letter-spacing:.14em;text-transform:uppercase;
color:var(--ink-faint)}
header{display:flex;flex-direction:column;gap:.75rem}
h1{margin:0;font-size:clamp(1.75rem,4vw,2.5rem);font-weight:700;letter-spacing:-.02em;
text-wrap:balance}
.subtitulo{margin:0;font-size:1.0625rem;color:var(--ink-soft);max-width:52ch;
font-family:Newsreader,"New York",Georgia,serif}
.placar{display:flex;flex-wrap:wrap;align-items:center;gap:1rem 1.25rem;margin-top:.5rem;
padding:1rem 1.25rem;background:var(--surface);border:1px solid var(--rule);border-radius:3px;
box-shadow:var(--sombra)}
.placar .par{display:flex;flex-direction:column;gap:.2rem}
.placar .valor{font-size:1.5rem;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums;
font-family:"JetBrains Mono","SF Mono",Menlo,ui-monospace,monospace}
.placar .seta{color:var(--ink-faint);font-size:1.25rem}
.placar .antes .valor{color:var(--ink-soft)}
.placar .depois .valor{color:var(--novo)}
.placar .resto{margin-left:auto;text-align:right}
.placar .resto p{margin:0;font-size:.9375rem;color:var(--ink-soft);max-width:32ch;
font-family:Newsreader,"New York",Georgia,serif}
.trilhos{background:var(--surface);border:1px solid var(--rule);border-radius:3px;
box-shadow:var(--sombra);overflow-x:auto}
.trilhos-interno{min-width:44rem;padding:1.25rem 1.5rem 1.5rem}
.eixo{position:relative;height:1.25rem;margin-left:4.5rem;border-bottom:1px solid var(--rule)}
.tick{position:absolute;top:0;transform:translateX(-50%);font-size:.6875rem;
font-variant-numeric:tabular-nums;color:var(--ink-faint);
font-family:"JetBrains Mono","SF Mono",Menlo,ui-monospace,monospace}
.tick::after{content:"";position:absolute;left:50%;top:1.15rem;width:1px;height:.3rem;
background:var(--rule)}
.trilho{display:flex;align-items:stretch;gap:.75rem;margin-top:1rem}
.trilho+.trilho{margin-top:.75rem}
.trilho .nome{flex:0 0 3.75rem;padding-top:.9rem;text-align:right}
.faixa{position:relative;flex:1;height:3rem;border-radius:2px;border:1px solid var(--rule-soft);
background:repeating-linear-gradient(-45deg,transparent 0 5px,var(--rule-soft) 5px 6px),var(--surface)}
.bloco{position:absolute;top:0;bottom:0;border-radius:2px;padding:.3rem .4rem;overflow:hidden;
display:flex;flex-direction:column;justify-content:center;gap:.1rem}
.bloco .id{font-size:.6875rem;font-weight:700;white-space:nowrap;letter-spacing:-.01em;
font-family:"JetBrains Mono","SF Mono",Menlo,ui-monospace,monospace}
.bloco .dur{font-size:.625rem;white-space:nowrap;opacity:.8;
font-family:"JetBrains Mono","SF Mono",Menlo,ui-monospace,monospace}
.bloco.ancora{background:var(--ancora-bg);color:var(--ancora);border:1px solid transparent}
.bloco.novo{background:var(--novo-bg);color:var(--novo);border:1px solid var(--novo)}
.bloco.almoco{border:1px solid var(--rule);color:var(--ink-faint);
background:repeating-linear-gradient(-45deg,transparent 0 6px,var(--almoco) 6px 7px)}
.bloco.estreito{padding:.3rem .15rem}
.bloco.estreito .dur{display:none}
.legenda{display:flex;flex-wrap:wrap;gap:1.25rem;margin:1.25rem 0 0 4.5rem}
.legenda span{display:inline-flex;align-items:center;gap:.45rem;font-size:.8125rem;
color:var(--ink-soft)}
.amostra{width:.9rem;height:.9rem;border-radius:2px;flex:none}
.amostra.ancora{background:var(--ancora-bg);border:1px solid var(--ancora)}
.amostra.novo{background:var(--novo-bg);border:1px solid var(--novo)}
section{display:flex;flex-direction:column;gap:.875rem}
h2{margin:0;font-size:1.0625rem;font-weight:700;letter-spacing:-.01em}
.envolve-tabela{overflow-x:auto}
table{width:100%;min-width:32rem;border-collapse:collapse}
th{text-align:left;font-size:.688rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;
color:var(--ink-faint);padding:0 .75rem .5rem 0;border-bottom:1px solid var(--rule)}
td{padding:.6rem .75rem .6rem 0;border-bottom:1px solid var(--rule-soft);vertical-align:baseline;
font-size:.9375rem}
td.mono,th.mono{font-variant-numeric:tabular-nums;white-space:nowrap;
font-family:"JetBrains Mono","SF Mono",Menlo,ui-monospace,monospace}
.chip{display:inline-block;padding:.1rem .4rem;border-radius:2px;font-size:.75rem;font-weight:500;
background:var(--novo-bg);color:var(--novo);
font-family:"JetBrains Mono","SF Mono",Menlo,ui-monospace,monospace}
.chip.ancora{background:var(--ancora-bg);color:var(--ancora)}
.comando{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--novo);
border-radius:2px;padding:1rem 1.25rem;overflow-x:auto;font-size:.8125rem;line-height:1.7;
white-space:pre;color:var(--ink);
font-family:"JetBrains Mono","SF Mono",Menlo,ui-monospace,monospace}
.nota{margin:0;font-size:1rem;color:var(--ink-soft);max-width:64ch;
font-family:Newsreader,"New York",Georgia,serif}
footer{border-top:1px solid var(--rule);padding-top:1.25rem;font-size:.9375rem;
color:var(--ink-faint);font-family:Newsreader,"New York",Georgia,serif}
footer a{color:var(--novo)}
footer a:focus-visible{outline:2px solid var(--novo);outline-offset:2px}
"""


def _hm(minutos: int) -> str:
    h, m = divmod(abs(minutos), 60)
    s = "-" if minutos < 0 else ""
    return f"{s}{h}h{m:02d}" if h else f"{s}{m}min"


def _pct(momento: datetime, dia: Date, agenda, tz) -> float:
    ini = datetime.combine(dia, agenda.work_start, tzinfo=tz)
    span = (
        datetime.combine(dia, agenda.work_end, tzinfo=tz) - ini
    ).total_seconds() / 60
    return max(0.0, min(100.0, (momento - ini).total_seconds() / 60 / span * 100))


def _bloco(classe: str, esq: float, larg: float, ref: str, dur: str) -> str:
    estreito = " estreito" if larg < 6 else ""
    corpo = f'<span class="id">{html.escape(ref)}</span>'
    if not estreito:
        corpo += f'<span class="dur">{html.escape(dur)}</span>'
    return (
        f'<div class="bloco {classe}{estreito}" '
        f'style="left:{esq:.4g}%;width:{larg:.4g}%">{corpo}</div>'
    )


def _faixa(itens, dia, agenda, tz) -> str:
    """itens: (classe, inicio, fim, rótulo). O almoço entra sempre."""
    almoco_ini = datetime.combine(dia, agenda.lunch_start, tzinfo=tz)
    almoco_fim = datetime.combine(dia, agenda.lunch_end, tzinfo=tz)
    partes = [
        _bloco(
            "almoco",
            _pct(almoco_ini, dia, agenda, tz),
            _pct(almoco_fim, dia, agenda, tz) - _pct(almoco_ini, dia, agenda, tz),
            "ALMOÇO",
            f"{agenda.lunch_start:%H:%M}–{agenda.lunch_end:%H:%M}",
        )
    ]
    for classe, inicio, fim, ref in itens:
        esq = _pct(inicio, dia, agenda, tz)
        larg = _pct(fim, dia, agenda, tz) - esq
        if larg <= 0:
            continue
        mins = int((fim - inicio).total_seconds() // 60)
        partes.append(_bloco(classe, esq, larg, ref, _hm(mins)))
    return '<div class="faixa">' + "".join(partes) + "</div>"


def _eixo(agenda) -> str:
    ini = agenda.work_start.hour
    fim = agenda.work_end.hour
    total = fim - ini
    ticks = "".join(
        f'<span class="tick" style="left:{(h - ini) / total * 100:.4g}%">{h:02d}</span>'
        for h in range(ini, fim + 1)
    )
    return f'<div class="eixo" aria-hidden="true">{ticks}</div>'


def gerar(dias, agenda, tz, comando: str | None = None, gerado_em: str = "",
          previa: bool = False) -> str:
    """dias: lista de dicts {data, antes:[Lancamento], novos:[Candidato]|None}."""
    secoes = []
    total_antes = sum(d["dia"].total_min() for d in dias)
    total_novos = sum(
        sum(c.duracao_min for c in (d.get("novos") or []) if c.estado == "criar")
        for d in dias
    )
    tem_previsao = any(d.get("novos") for d in dias)

    for entrada in dias:
        dia_obj = entrada["dia"]
        data = dia_obj.data
        novos = [c for c in (entrada.get("novos") or []) if c.estado == "criar"]

        ancoras = [
            ("ancora", l.inicio, l.fim or l.inicio, l.task_ref or (l.task_nome or "—"))
            for l in dia_obj.lancamentos
            if not l.rodando
        ]
        trilhos = [("Antes" if novos else "Hoje", ancoras)]
        if novos:
            trilhos.append(
                ("Depois", ancoras + [("novo", c.inicio, c.fim, c.ref) for c in novos])
            )

        corpo = "".join(
            f'<div class="trilho"><span class="nome rotulo">{nome}</span>'
            f"{_faixa(itens, data, agenda, tz)}</div>"
            for nome, itens in trilhos
        )
        legenda = (
            '<div class="legenda">'
            '<span><i class="amostra ancora"></i> Âncora — já está no ClickUp</span>'
            + ('<span><i class="amostra novo"></i> Seria criado agora</span>' if novos else "")
            + "</div>"
        )
        titulo_dia = (
            f"{DIAS_EXTENSO[data.weekday()]}, {data:%d/%m}"
            f' <span class="rotulo">{_hm(dia_obj.total_min())} de '
            f"{_hm(agenda.target_minutes)}</span>"
        )
        secoes.append(
            f"<section><h2>{titulo_dia}</h2>"
            f'<div class="trilhos"><div class="trilhos-interno">'
            f"{_eixo(agenda)}{corpo}{legenda}</div></div></section>"
        )

        linhas = "".join(
            f'<tr><td class="mono">{c.inicio:%H:%M}–{c.fim:%H:%M}</td>'
            f'<td class="mono">{_hm(c.duracao_min)}</td>'
            f'<td><span class="chip">{html.escape(c.ref)}</span></td>'
            f"<td>{html.escape(c.task_nome[:70])}</td></tr>"
            for c in novos
        )
        if linhas:
            secoes.append(
                "<section><h2>O que seria criado</h2>"
                '<div class="envolve-tabela"><table><thead><tr>'
                '<th class="mono">Horário</th><th class="mono">Duração</th>'
                "<th>Task</th><th>Nome</th></tr></thead>"
                f"<tbody>{linhas}</tbody></table></div></section>"
            )

    bloco_comando = ""
    if comando:
        bloco_comando = (
            "<section><h2>O comando</h2>"
            f'<div class="comando">{html.escape(comando)}</div>'
            '<p class="nota">Prévia. Só houve leitura — nenhum lançamento foi criado. '
            "Repita com <strong>--confirm</strong> para gravar.</p></section>"
        )

    if tem_previsao:
        placar = (
            f'<div class="placar">'
            f'<div class="par antes"><span class="rotulo">Antes</span>'
            f'<span class="valor">{_hm(total_antes)}</span></div>'
            f'<span class="seta" aria-hidden="true">&rarr;</span>'
            f'<div class="par depois"><span class="rotulo">Depois</span>'
            f'<span class="valor">{_hm(total_antes + total_novos)}</span></div>'
            f'<div class="resto"><span class="rotulo">Meta</span>'
            f"<p>{_hm(agenda.target_minutes)} por dia útil, "
            f"{len(dias)} dia(s) neste recorte.</p></div></div>"
        )
        subtitulo = "Como a planilha do ClickUp está hoje e como ficaria. Nada foi gravado."
    else:
        placar = (
            f'<div class="placar">'
            f'<div class="par antes"><span class="rotulo">Apontado</span>'
            f'<span class="valor">{_hm(total_antes)}</span></div>'
            f'<div class="resto"><span class="rotulo">Meta</span>'
            f"<p>{_hm(agenda.target_minutes * len(dias))} no recorte "
            f"({len(dias)} dia(s) × {_hm(agenda.target_minutes)}).</p></div></div>"
        )
        subtitulo = "Estado atual da planilha do ClickUp, lido pela API."

    periodo = (
        f"{dias[0]['dia'].data:%d/%m}"
        if len(dias) == 1
        else f"{dias[0]['dia'].data:%d/%m} a {dias[-1]['dia'].data:%d/%m}"
    )

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{"Prévia" if previa else "Apontamento"} {periodo}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Newsreader:opsz,wght@6..72,400&display=swap">
<style>{CSS}</style></head>
<body><div class="pagina">
<header><p class="rotulo">ClickUp · Irrah Tech{" · nada gravado" if previa else ""}</p>
<h1>{"Prévia" if previa else "Apontamento"} {periodo}</h1>
<p class="subtitulo">{subtitulo}</p>
{placar}</header>
{"".join(secoes)}
{bloco_comando}
<footer>Gerado por <code>clickup-time.sh</code>{f" em {gerado_em}" if gerado_em else ""}.
Arquivo autocontido — abre offline.
<a href="https://app.clickup.com/90131214647/time">Conferir na planilha do ClickUp</a>
— a aba "entradas de tempo" mostra a Hora Final, que a releitura por API não valida.</footer>
</div></body></html>
"""
