#!/usr/bin/env python3
"""clickup_time_front.py — front local do fluxo de apontamento.

Não substitui o terminal: reusa os mesmos módulos, e o uso por linha de comando
continua idêntico.

## Onde o agente entra

O front não tem LLM dentro. A divisão é:

    agente  ->  roda `sugerir --json`, lê as transcrições, resolve os `???`,
                lê as tasks (`tarefas`), escreve um plano e sobe o front com
                `--plano plano.json`
    front   ->  mostra a proposta com a justificativa de cada trecho, deixa
                ajustar, e grava o que você confirmar
    você    ->  confirma

O plano é a superfície de entrega do agente. Formato:

    {"2026-09-02": {
       "blocos": [
         {"start": "08:15", "minutes": 75, "task": "HM-305",
          "origem": "inferencia", "nota": "a sessão discute a correção da 305"}
       ],
       "resumo": {
         "HM-305": {"requisito": "o que a task pede, em uma frase",
                    "feito": "o que foi feito nela neste dia"}
       }
    }}

A forma antiga, `{"2026-09-02": [blocos]}`, continua aceita — só não tem resumo.

`origem`, do mais forte para o mais fraco:

    usuario      o usuário disse, na conversa, o que era aquele horário
    ancora       o script achou a referência na transcrição
    inferencia   o agente leu a sessão daquele horário e deduziu
    proximidade  não havia nada ali; o buraco foi fechado com a task vizinha

## A lista é por lançamento, em tabela

Colunas: intervalo, duração, tarefa e o que foi encontrado. Início, fim e
duração são editáveis em todo o expediente; a alteração que quebrar o horário
ganha aviso e "desfazer" logo abaixo e trava a gravação do dia. A garantia é do
servidor (`validar_candidatos`), a tela só aponta a culpada.

O plano pode vir em trechos — um por origem, cada um com a sua nota —, mas a
tela junta os trechos encostados da mesma task numa linha só. A linha só se
divide quando há algo entre os trechos: um lançamento já marcado, o almoço ou
um buraco sem proposta. Dentro da linha ficam a composição por origem e as
notas de cada trecho, então juntar não esconde de onde veio cada minuto.

Até 24/09/2026 a lista era por trecho: 23/09 aparecia como 11 linhas, três
delas seguidas de HM-423, para 8 lançamentos.

## Escrita

O front grava, por POST, com dupla confirmação na tela e revalidação no
servidor pelo mesmo caminho do `write --confirm`: preflight, guardrails e
fingerprint contra duplicata. `--somente-leitura` desliga o endpoint.

O que foi gravado fica registrado na memória do processo (`/api/gravados`): o
botão do dia não some, fica inativo dizendo quando gravou, o comando executado
continua visível, e a aba Resultados tem uma sub-aba por dia gravado.

Segurança: escuta só em 127.0.0.1, porta efêmera, segredo aleatório exigido em
toda requisição, `Origin` estranha recusada, `Host` conferido. GET nunca muta.

Sobre o token: lido do Keychain uma vez, na subida, e mantido na memória do
processo. Troca "uma digital por leitura" por "uma digital por sessão".
Ctrl-C ao terminar.

Nota de manutenção: **não escreva barra invertida no JS desta página.** Ela
atravessa literal Python -> HTML -> parser JS, e em 11/09/2026 se perdeu nesse
caminho e derrubou o script inteiro, deixando todo botão inerte. Use
`String.fromCharCode`.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import signal
import secrets
import sys
import threading
import webbrowser
from datetime import date as Date
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import clickup_time as ct
import clickup_time_html as cth

SEGREDO = secrets.token_hex(16)
ESTADO = os.path.expanduser("~/.cache/clickup-time")
ORIGENS = ("usuario", "ancora", "inferencia", "proximidade")
DATA_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")

ESTILO = """
/* Cores próprias desta tela, como tokens. Até 25/09/2026 elas tinham um
   `:root:not([data-theme="light"])` solto, fora da media query, que valia também
   no tema claro do sistema: o selo de inferência saía marrom-escuro no claro. */
:root{color-scheme:light;--conflito-bg:#f6e2de;--infer-bg:#f2e3d2;--infer-ink:#9a541c;
--erro-bg:#f6e2de;--erro-ink:#7a2416;--quebra-borda:#c2533d}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
--conflito-bg:#3a1d18;--infer-bg:#3a2c1c;--infer-ink:#e0a868;--erro-bg:#3a1d18;--erro-ink:#f0c4bb;
--quebra-borda:#d0715c}}
:root[data-theme="dark"]{color-scheme:dark;--conflito-bg:#3a1d18;--infer-bg:#3a2c1c;
--infer-ink:#e0a868;--erro-bg:#3a1d18;--erro-ink:#f0c4bb;--quebra-borda:#d0715c}
[hidden]{display:none!important}
.tema{position:absolute;top:calc(.75rem + env(safe-area-inset-top,0px));right:1rem;z-index:6;
display:inline-flex;align-items:center;justify-content:center;width:2.25rem;height:2.25rem;
padding:0;background:var(--surface);color:var(--ink-soft);border:1px solid var(--rule);
border-radius:3px;box-shadow:var(--sombra)}
.tema:hover{color:var(--ink)}
.tema svg{width:1.125rem;height:1.125rem}
.tema .sol{display:none}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .tema .sol{display:block}
:root:not([data-theme="light"]) .tema .lua{display:none}}
:root[data-theme="dark"] .tema .sol{display:block}
:root[data-theme="dark"] .tema .lua{display:none}
.barra{display:flex;flex-wrap:wrap;gap:.75rem;align-items:flex-end;padding:1rem 1.25rem;
background:var(--surface);border:1px solid var(--rule);border-radius:3px;box-shadow:var(--sombra)}
.campo{display:flex;flex-direction:column;gap:.25rem}
input[type=date]{font:inherit;font-size:.9375rem;padding:.4rem .5rem;
border:1px solid var(--rule);border-radius:2px;background:var(--ground);color:var(--ink)}
button{font:inherit;font-weight:600;font-size:.875rem;padding:.5rem .9rem;border-radius:2px;
border:1px solid var(--novo);background:var(--novo);color:var(--surface);cursor:pointer}
button.calmo{background:transparent;color:var(--ink-soft);border-color:var(--rule)}
button.perigo{background:#9a2f1c;border-color:#9a2f1c;color:#fff}
button:disabled{opacity:.45;cursor:not-allowed}
button.feito:disabled{opacity:1;cursor:default;background:var(--ancora-bg);color:var(--ancora);
border-color:var(--rule)}
button:focus-visible{outline:2px solid var(--novo);outline-offset:2px}
.mono{font-family:"JetBrains Mono","SF Mono",Menlo,monospace;font-variant-numeric:tabular-nums}

.abas{display:flex;flex-wrap:wrap;gap:.25rem;border-bottom:1px solid var(--rule);
position:sticky;top:env(safe-area-inset-top,0px);background:var(--ground);z-index:5;
padding-top:.5rem;margin-bottom:-1.25rem}
.abas button{background:transparent;color:var(--ink-soft);border:1px solid transparent;
border-bottom:none;border-radius:3px 3px 0 0;padding:.55rem 1.1rem;margin-bottom:-1px;
font-size:.9375rem}
.abas button[aria-selected=true]{background:var(--surface);color:var(--ink);border-color:var(--rule)}
.abas .cont{font-family:"JetBrains Mono","SF Mono",Menlo,monospace;font-size:.75rem;
font-weight:500;color:var(--ink-faint);margin-left:.35rem}
.painel{display:flex;flex-direction:column;gap:1.25rem}
.subabas{display:flex;flex-wrap:wrap;gap:.4rem}
.subabas button{background:transparent;color:var(--ink-soft);border-color:var(--rule);
font-size:.8125rem;padding:.35rem .75rem}
.subabas button[aria-selected=true]{background:var(--novo-bg);color:var(--novo);border-color:var(--novo)}

.dia{background:var(--surface);border:1px solid var(--rule);border-radius:3px;
box-shadow:var(--sombra);padding:1.25rem 1.5rem;display:flex;flex-direction:column;gap:.4rem}
.cab-dia{display:flex;flex-wrap:wrap;align-items:baseline;gap:.35rem .75rem;margin-bottom:.35rem}
.cab-dia h2{margin:0}
.total{font-family:"JetBrains Mono","SF Mono",Menlo,monospace;font-variant-numeric:tabular-nums;
font-weight:700;margin-left:auto}
.total.cheio{color:var(--novo)}
.total.acima{color:#9a541c}

.tabela{overflow-x:auto}
table.grade{width:100%;border-collapse:collapse;font-size:.9375rem}
.grade th{text-align:left;font-size:.6875rem;font-weight:600;letter-spacing:.1em;
text-transform:uppercase;color:var(--ink-faint);padding:.35rem .5rem .5rem;
border-bottom:1px solid var(--rule);white-space:nowrap}
.grade td{padding:.65rem .5rem;border-bottom:1px solid var(--rule-soft);vertical-align:top}
.grade tbody tr:last-child td{border-bottom:none}
.grade .c-inc{width:2rem;padding-right:0}
.grade .c-int{width:10rem;white-space:nowrap}
.grade .c-dur{width:5.75rem;white-space:nowrap}
.grade .c-task{width:15rem}
.grade td.c-int,.grade td.c-dur{font-family:"JetBrains Mono","SF Mono",Menlo,monospace;
font-size:.8125rem;font-variant-numeric:tabular-nums;color:var(--ink-soft)}
.grade td.c-dur{color:var(--ink);font-weight:500}
.grade .horas{display:inline-flex;align-items:center;gap:.3rem;margin-top:-.2rem}
.grade select{font:inherit;font-size:.8125rem;padding:.2rem .25rem;border-radius:2px;
border:1px solid var(--rule);background:var(--ground);color:var(--ink);
font-family:"JetBrains Mono","SF Mono",Menlo,monospace;font-variant-numeric:tabular-nums}
.grade input[type=checkbox]{accent-color:var(--novo);width:1rem;height:1rem;margin:.15rem 0 0}
.grade .ref{display:block;font-family:"JetBrains Mono","SF Mono",Menlo,monospace;
font-size:.875rem;font-weight:700}
.grade .nome{display:block;color:var(--ink-soft);font-size:.875rem;line-height:1.35}
.grade tr.exist td{opacity:.62}
.grade tr.desmarcada td{opacity:.42}
.grade tr.conflito td{background:var(--conflito-bg)}
.grade tr.quebra td{padding-top:0;background:var(--conflito-bg)}
.grade tr:has(+ tr.quebra) td{border-bottom:none}
.caixa-quebra{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem 1rem;padding:.7rem .85rem;
border:1px solid var(--quebra-borda);border-left-width:3px;border-radius:2px;background:var(--surface)}
.caixa-quebra p{margin:0;flex:1 1 22rem;font-size:.875rem;color:var(--erro-ink);line-height:1.45}
.caixa-quebra button{flex:none}
.grade .fixo{margin:0;font-size:.875rem;color:var(--ink-soft);display:flex;flex-wrap:wrap;
gap:.4rem;align-items:baseline}
.semtask{font-family:Newsreader,"New York",Georgia,serif;font-size:.9375rem;color:#9a541c}
.notas{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:.45rem}
.notas li{font-family:Newsreader,"New York",Georgia,serif;font-size:.9375rem;line-height:1.45;
color:var(--ink)}
.notas .marca{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem;margin-bottom:.1rem}
.notas .h{font-family:"JetBrains Mono","SF Mono",Menlo,monospace;font-size:.75rem;
color:var(--ink-faint)}
.sobra{font-size:.8125rem;color:#9a541c;margin:.45rem 0 0}
.selo{font-size:.6875rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
padding:.1rem .4rem;border-radius:2px;white-space:nowrap}
.selo.ancora{background:var(--ancora-bg);color:var(--ancora)}
.selo.inferencia{background:var(--infer-bg);color:var(--infer-ink)}
.selo.proximidade{background:transparent;color:var(--ink-faint);border:1px solid var(--rule)}
.selo.usuario{background:var(--novo-bg);color:var(--novo)}
.selo.ajuste{background:transparent;color:#9a541c;border:1px dashed #9a541c}
.selo.vazio{background:transparent;color:var(--ink-faint);border:1px dashed var(--rule)}
.selo.gravado{background:var(--ancora-bg);color:var(--ancora)}
.selo.agora{background:var(--novo-bg);color:var(--novo)}
.conflito-aviso{margin:.25rem 0 0;font-size:.875rem;color:#9a2f1c}
.preenchido{margin:.15rem 0 0;font-family:Newsreader,"New York",Georgia,serif;
font-size:.9375rem;color:var(--ink-soft);max-width:72ch}
.preenchido b{color:#9a541c;font-family:Archivo,-apple-system,sans-serif}
.foras{margin:.25rem 0 0;padding-left:1.1rem;font-size:.875rem;color:#9a541c}

.resumos{display:flex;flex-direction:column;gap:1rem}
.resumo-dia{background:var(--surface);border:1px solid var(--rule);border-radius:3px;
box-shadow:var(--sombra);padding:1.25rem 1.5rem;display:flex;flex-direction:column;gap:1rem}
.resumo-dia h3{margin:0;font-size:1rem}
.tarefa{display:flex;flex-direction:column;gap:.3rem;padding-top:.85rem;border-top:1px solid var(--rule-soft)}
.tarefa:first-of-type{border-top:none;padding-top:0}
.tarefa .cab{display:flex;flex-wrap:wrap;gap:.25rem .6rem;align-items:baseline}
.tarefa .cab b{font-family:"JetBrains Mono","SF Mono",Menlo,monospace;font-size:.875rem}
.tarefa .cab .horas{margin-left:auto;font-family:"JetBrains Mono","SF Mono",Menlo,monospace;
font-size:.8125rem;color:var(--ink-soft)}
.tarefa .cab a{font-size:.8125rem;color:var(--novo)}
.tarefa p{margin:0;font-family:Newsreader,"New York",Georgia,serif;font-size:.9375rem;
color:var(--ink);max-width:72ch}
.tarefa p .rotulo{font-family:Archivo,-apple-system,sans-serif;margin-right:.4rem}
.tarefa p.falta{color:var(--ink-faint)}
.baixar{padding-top:.85rem;border-top:1px solid var(--rule-soft)}
.baixar .arquivo{font-family:"JetBrains Mono","SF Mono",Menlo,monospace;font-size:.8125rem;color:var(--ink-faint)}

.lanc{display:flex;flex-wrap:wrap;align-items:baseline;gap:.3rem .9rem;font-size:.8125rem;
padding:.55rem .7rem;background:var(--ground);border:1px solid var(--rule-soft);border-radius:2px}
.lanc b{font-size:.6875rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
color:var(--ink-soft)}
.lanc span{font-family:"JetBrains Mono","SF Mono",Menlo,monospace;
font-variant-numeric:tabular-nums;color:var(--ink)}
.lanc i{font-style:normal;font-weight:700}
.executado{display:flex;flex-direction:column;gap:.5rem;padding-top:.75rem;margin-top:.25rem;
border-top:1px solid var(--rule-soft)}
.executado .rotulo{margin:0}
pre.cmd{background:var(--ground);border:1px solid var(--rule);border-left:3px solid var(--novo);
border-radius:2px;padding:1rem;overflow-x:auto;font-family:"JetBrains Mono","SF Mono",Menlo,monospace;
font-size:.8125rem;line-height:1.7;margin:0;white-space:pre-wrap;word-break:break-word}
pre.cmd.inativo{border-left-color:var(--rule);color:var(--ink-faint);user-select:all}
iframe{width:100%;height:72vh;border:1px solid var(--rule);border-radius:3px;background:var(--surface)}
.aviso{font-family:Newsreader,"New York",Georgia,serif;font-size:.9375rem;color:var(--ink-soft);
margin:0;max-width:70ch}
.aviso a{color:var(--novo)}
.vazio-aba{font-family:Newsreader,"New York",Georgia,serif;font-size:1rem;color:var(--ink-soft);
margin:0;padding:1.25rem 1.5rem;background:var(--surface);border:1px dashed var(--rule);border-radius:3px}
#erro{display:none;padding:.75rem 1rem;border-radius:2px;border:1px solid #9a2f1c;
background:var(--erro-bg);color:var(--erro-ink);font-size:.9375rem;white-space:pre-wrap}
.acoes{display:flex;flex-wrap:wrap;gap:.75rem;align-items:center}
.fontes{display:flex;flex-wrap:wrap;gap:.5rem 1.25rem;font-size:.8125rem;color:var(--ink-soft)}
.fontes b{font-weight:600;color:var(--ink)}
#toast{position:fixed;left:50%;bottom:calc(1.5rem + env(safe-area-inset-bottom,0px));
transform:translate(-50%,.75rem);background:var(--ink);color:var(--surface);padding:.6rem 1rem;
border-radius:3px;font-size:.875rem;box-shadow:var(--sombra);opacity:0;pointer-events:none;
transition:opacity .18s ease,transform .18s ease;z-index:50}
#toast.vivo{opacity:1;transform:translate(-50%,0)}
#toast.ruim{background:#9a2f1c;color:#fff}
@media (prefers-reduced-motion:reduce){#toast{transition:none}}
/* Estreito, a tabela vira um cartão por linha: intervalo e duração lado a lado,
   tarefa e o que foi encontrado embaixo, em largura inteira. */
@media (max-width:52rem){
  .grade thead{display:none}
  /* min-width vem do `table{min-width:32rem}` da prévia, no CSS compartilhado. */
  .grade,.grade tbody{display:block;min-width:0}
  .grade tr{display:grid;grid-template-columns:1.75rem auto minmax(0,1fr);gap:.35rem .6rem;
  padding:.7rem 0;border-bottom:1px solid var(--rule-soft)}
  .grade tbody tr:last-child{border-bottom:none}
  .grade td[class]{display:block;width:auto;padding:0;border:none}
  .grade td.c-inc{grid-row:1/span 3}
  .grade td.c-task,.grade td.c-achado{grid-column:2/-1}
  .grade tr.quebra{padding-top:0}
  .grade td.c-quebra{grid-column:1/-1}
  .grade tr.quebra td.c-inc{display:none}
  .grade tr:has(+ tr.quebra){border-bottom:none}
}
@media (max-width:44rem){
  .dia,.resumo-dia{padding:1rem}
}
"""

CORPO = """
<button class="tema" id="tema" type="button" aria-label="Mudar o tema">
  <svg class="lua" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>
  <svg class="sol" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="4"/>
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
</button>

<header>
  <p class="rotulo">ClickUp &middot; Irrah Tech &middot; front local</p>
  <h1>Apontar horas</h1>
  <p class="subtitulo">Mostra o que o agente prop&ocirc;s e por qu&ecirc;, deixa ajustar,
  e grava o que voc&ecirc; confirmar.</p>
</header>

<div id="erro"></div>

<div class="barra">
  <div class="campo" id="seletor">
    <span class="rotulo">Per&iacute;odo</span>
    <div class="acoes"><input type="date" id="de"><input type="date" id="ate"></div>
  </div>
  <div class="campo" id="rotuloPeriodo" hidden>
    <span class="rotulo">Per&iacute;odo analisado pelo agente</span>
    <strong id="textoPeriodo" class="mono"></strong>
  </div>
  <button id="carregar">Carregar</button>
</div>

<nav class="abas" role="tablist" aria-label="Etapas">
  <button role="tab" id="tab-lista" data-aba="lista" aria-controls="aba-lista"
          aria-selected="true">Lista</button>
  <button role="tab" id="tab-gravar" data-aba="gravar" aria-controls="aba-gravar"
          aria-selected="false">Gravar<span class="cont" id="contGravar"></span></button>
  <button role="tab" id="tab-resultados" data-aba="resultados" aria-controls="aba-resultados"
          aria-selected="false">Resultados<span class="cont" id="contResultados"></span></button>
</nav>

<section class="painel" id="aba-lista" role="tabpanel" aria-labelledby="tab-lista">
  <div class="fontes" id="fontes"></div>
  <div id="dias" class="painel"></div>
  <div id="resumos" class="resumos"></div>
</section>

<section class="painel" id="aba-gravar" role="tabpanel" aria-labelledby="tab-gravar" hidden>
  <p class="aviso" id="avisoGravar"></p>
  <div id="cartoes" class="painel"></div>
  <section id="secPrevia" hidden>
    <h2 id="tituloPrevia">Pr&eacute;via</h2>
    <iframe id="framePrevia" title="Pr&eacute;via do dia"></iframe>
  </section>
</section>

<section class="painel" id="aba-resultados" role="tabpanel" aria-labelledby="tab-resultados" hidden>
  <div class="subabas" role="tablist" id="subabas" aria-label="Dias gravados"></div>
  <div id="resultado" class="painel"></div>
</section>

<div id="toast" role="status" aria-live="polite"></div>
"""

SCRIPT = """
const K = new URLSearchParams(location.search).get("k");
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const PODE_GRAVAR = __PODE_GRAVAR__;
const PLANO = __PLANO__;
const PERIODO = __PERIODO__;
const FLAGS_AGENDA = __FLAGS_AGENDA__;
const PASSO = __PASSO__;
const ROTULO = {usuario:"você disse", ancora:"âncora", inferencia:"inferência",
                proximidade:"proximidade", ajuste:"ajuste na tela"};
const TIPO_ANCORA = {url:"link do ClickUp na sua fala", fala:"task citada na sua fala",
                     branch:"troca de branch", github:"sua atividade no GitHub",
                     clickup:"seu comentário no ClickUp"};

let dados = null;     // resposta de /api/sugerir
let dias = [];        // um modelo por dia, montado por montarDia()
let estado = {};      // por linha de proposta: {incluir, ini, fim, i0, f0}
let gravados = {};    // por data: {registros:[{quando, entradas, comando}], html}
let confirmando = null, abaAtual = "lista", diaResultado = null;
let historico = [], seq = 0;   // alteracoes feitas na tela, da mais antiga para a mais nova
let culpas = {};               // chave da quebra -> {id, seq}: quem quebrou, fixado quando a quebra surgiu

function hm(m){const h=Math.floor(m/60),r=m%60;return h?(h+"h"+String(r).padStart(2,"0")):(r+"min")}
function esc(t){const d=document.createElement("div");d.textContent=(t==null?"":t);return d.innerHTML}
function min(s){const p=s.split(":");return (+p[0])*60 + (+p[1])}
function hhmm(m){return String(Math.floor(m/60)).padStart(2,"0") + ":" + String(m%60).padStart(2,"0")}
function faixa(i,f){return hhmm(i) + "&ndash;" + hhmm(f)}
function erro(msg){const e=$("#erro");e.textContent=msg;e.style.display=msg?"block":"none";
  if(msg) e.scrollIntoView({behavior:"smooth",block:"nearest"});}
function hoje(){const d=new Date();return d.toISOString().slice(0,10)}
function domingo(){const d=new Date();d.setDate(d.getDate()-d.getDay());return d.toISOString().slice(0,10)}
// O JSON traz o dia abreviado ("ter"), que serve para o cabecalho mas nao para o
// botao que grava: ali vale nomear o dia por extenso, porque e a ultima leitura
// antes de uma escrita que nao se desfaz.
const POR_EXTENSO = {seg:"segunda-feira", ter:"terça-feira", qua:"quarta-feira",
                     qui:"quinta-feira", sex:"sexta-feira", "sáb":"sábado", dom:"domingo"};
function curto(d){return d.weekday + ", " + d.date.slice(8) + "/" + d.date.slice(5,7)}
function extenso(d){return (POR_EXTENSO[d.weekday]||d.weekday) + ", " + d.date.slice(8) + "/" + d.date.slice(5,7)}

if(PERIODO){
  // O agente ja decidiu o periodo e fez a pesquisa: refazer a escolha aqui
  // seria pedir de novo o que ja foi respondido.
  $("#de").value = PERIODO.de; $("#ate").value = PERIODO.ate;
  $("#seletor").hidden = true; $("#rotuloPeriodo").hidden = false;
  $("#textoPeriodo").textContent = PERIODO.de === PERIODO.ate ? PERIODO.de
    : (PERIODO.de + "  →  " + PERIODO.ate);
} else { $("#de").value = domingo(); $("#ate").value = hoje(); }

async function api(rota, params, corpo){
  const q = new URLSearchParams(Object.assign({}, params||{}, {k:K}));
  const opcoes = corpo ? {method:"POST", headers:{"Content-Type":"application/json"},
                          body: JSON.stringify(corpo)} : {};
  const r = await fetch(rota + "?" + q, opcoes);
  const txt = await r.text();
  if(!r.ok) throw new Error(txt);
  return JSON.parse(txt);
}

let toastTimer = null;
function toast(msg, ruim){
  const el = $("#toast"); el.textContent = msg; el.classList.toggle("ruim", !!ruim);
  el.classList.add("vivo"); clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("vivo"), 2600);
}

// ---- abas -------------------------------------------------------------------

function mostrarAba(nome){
  abaAtual = nome;
  $$(".abas [role=tab]").forEach(b => b.setAttribute("aria-selected", b.dataset.aba === nome ? "true" : "false"));
  ["lista","gravar","resultados"].forEach(n => { $("#aba-" + n).hidden = n !== nome; });
}
$$(".abas [role=tab]").forEach(b => b.onclick = () => mostrarAba(b.dataset.aba));

// ---- modelo do dia ----------------------------------------------------------

function notaAncora(b){
  const a = b.anchor || {};
  return (TIPO_ANCORA[a.type] || a.type || "ancora") + " às " + a.at
    + (a.age_minutes >= 60 ? " (" + hm(a.age_minutes) + " antes do trecho)" : "")
    + ": " + (a.excerpt || "");
}

// Monta as linhas do dia em ordem: lancamentos ja marcados, propostas e buracos.
// O almoco NAO entra: a lista e de marcacoes, e almoco nao e marcado. Com linha
// propria (hora, duracao, rotulo) ele se lia como mais um lancamento (24/09/2026).
// Ele so aparece como o intervalo entre as linhas da manha e as da tarde. As propostas vem do plano do agente (ou das ancoras do script, sem
// plano), recortadas contra as janelas livres da leitura mais recente:
//   - o pedaco livre vira proposta;
//   - o pedaco que caiu num lancamento da mesma task e o que ja foi gravado, e
//     some da proposta -- e isso que impede o dia de voltar inteiro depois de
//     gravar (15/09/2026);
//   - o pedaco que caiu num lancamento de outra task fica de fora, com aviso.
// Trechos encostados da mesma task viram UMA linha: a lista mostra lancamentos,
// e a composicao por origem fica dentro da linha.
function montarDia(d){
  const livres = d.free_windows.map(w => ({i: min(w.start), f: min(w.end)}));
  const janelaDe = m => livres.find(w => w.i <= m && m < w.f) || null;
  const existentes = (d.existing || []).map(e => ({tipo:"exist", i: min(e.start), f: min(e.end),
                                                   task: e.task, nome: e.name}));
  const cobre = m => existentes.find(e => e.i <= m && m < e.f) || null;

  const plano = PLANO[d.date];
  const itens = plano
    ? plano.blocos.map(x => ({i: min(x.start), f: min(x.start) + x.minutes, task: x.task,
                              origem: x.origem, nota: x.nota}))
    : d.blocks.filter(b => b.task).map(b => ({i: min(b.start), f: min(b.end), task: b.task,
                                              origem: "ancora", nota: notaAncora(b)}));
  itens.sort((a,b) => a.i - b.i);

  const partes = [], foras = [];
  itens.forEach(x => {
    let atual = null;
    for(let m = x.i; m < x.f; m += PASSO){
      const ate = Math.min(m + PASSO, x.f);
      const jan = janelaDe(m), e = jan ? null : cobre(m);
      const st = jan ? "livre" : (e && e.task === x.task ? "gravado" : "fora");
      if(atual && atual.st === st && atual.f === m && atual.jan === jan){ atual.f = ate; continue; }
      atual = {st, jan, i: m, f: ate, task: x.task, origem: x.origem, nota: x.nota, sobre: e};
      if(st === "livre") partes.push(atual);
      if(st === "fora") foras.push(atual);
    }
  });

  const props = [];
  partes.sort((a,b) => a.i - b.i).forEach(p => {
    const ant = props.length ? props[props.length - 1] : null;
    if(ant && ant.f === p.i && ant.task === p.task && ant.janela === p.jan){
      ant.f = p.f; ant.partes.push(p);
    } else {
      props.push({tipo:"prop", task: p.task, i: p.i, f: p.f, janela: p.jan, partes: [p]});
    }
  });
  props.forEach(l => { l.i0 = l.i; l.f0 = l.f; l.id = d.date + "|" + l.i0; });

  // Buracos: o que as janelas livres tem e nenhuma proposta cobre.
  const coberto = m => props.some(l => l.i0 <= m && m < l.f0);
  const buracos = [];
  livres.forEach(w => {
    let ini = null;
    for(let m = w.i; m <= w.f; m += PASSO){
      const vago = m < w.f && !coberto(m);
      if(vago && ini === null) ini = m;
      if(!vago && ini !== null){ buracos.push({tipo:"vazio", i: ini, f: m}); ini = null; }
    }
  });

  // Lancamento que casa com o que esta sessao do front gravou ganha selo proprio.
  const agora = new Set();
  ((gravados[d.date] || {}).registros || []).forEach(r => r.entradas.forEach(s => {
    const p = s.split(" "), i = min(p[0]), dur = parseInt(p[1], 10);
    agora.add(i + "|" + (i + dur) + "|" + p[2]);
  }));
  existentes.forEach(e => { e.agora = agora.has(e.i + "|" + e.f + "|" + e.task); });

  const linhas = [].concat(existentes, props, buracos).sort((a,b) => a.i - b.i || a.f - b.f);
  return {d, linhas, props, foras,
          resumo: (plano && plano.resumo) || {}, temPlano: !!plano};
}

function montar(){
  const antes = estado; estado = {};
  dias = dados.days.map(montarDia);
  dias.forEach(dia => {
    const jaGravou = ((gravados[dia.d.date] || {}).registros || []).length > 0;
    dia.props.forEach(l => {
      const v = antes[l.id];
      if(v && v.i0 === l.i0 && v.f0 === l.f0){ estado[l.id] = v; return; }
      // Depois de uma gravacao, o que sobrou da proposta e o que o usuario deixou
      // de fora de proposito: volta desmarcado, senao o botao reaparece oferecendo
      // gravar justamente o que ele tirou.
      estado[l.id] = {incluir: !jaGravou, ini: l.i0, fim: l.f0, i0: l.i0, f0: l.f0, sobra: jaGravou};
    });
  });
  // Alteracao de linha que nao existe mais (gravou, ou o plano mudou) nao tem o
  // que desfazer.
  historico = historico.filter(h => estado[h.id] && estado[h.id] === antes[h.id]);
}

function ativos(dia){ return dia.props.filter(l => estado[l.id].incluir); }

function composicao(l){
  const e = estado[l.id], por = {}, notas = [];
  let coberto = 0;
  l.partes.forEach(p => {
    const a = Math.max(p.i, e.ini), b = Math.min(p.f, e.fim);
    if(b <= a) return;
    por[p.origem] = (por[p.origem] || 0) + (b - a); coberto += b - a;
    const ant = notas.length ? notas[notas.length - 1] : null;
    if(ant && ant.f === a && ant.origem === p.origem && ant.nota === p.nota) ant.f = b;
    else notas.push({i: a, f: b, origem: p.origem, nota: p.nota});
  });
  const ajuste = (e.fim - e.ini) - coberto;
  if(ajuste > 0) por.ajuste = ajuste;
  return {por, notas};
}

// ---- quebras -------------------------------------------------------------------
// Quem garante e o Python: validar_candidatos() refaz tudo isto antes de gravar e
// recusa o dia inteiro se uma entrada quebrar, venha da tela ou do terminal. A
// conta aqui espelha a de la so para apontar, na hora, QUAL alteracao quebrou.
//
// A culpa e fixada no momento em que a quebra aparece (mudar() registra em
// `culpas`). Recalcular pela "ultima linha mexida" errava: mexer depois numa
// linha envolvida roubava a culpa de uma quebra que ela nao causou.

function achadosDe(dia){
  const s = dados.schedule, ei = min(s.work_start), ef = min(s.work_end);
  const ai = min(s.lunch_start), af = min(s.lunch_end);
  const at = ativos(dia).map(l => ({l, i: estado[l.id].ini, f: estado[l.id].fim}));
  const achados = [];
  at.forEach(x => {
    const um = [x], k = "u|" + x.l.id + "|";
    if(x.f <= x.i) achados.push({chave: k + "fim", quem: um, msg: "o fim ficou antes do in&iacute;cio"});
    else if(x.i % PASSO || x.f % PASSO) achados.push({chave: k + "grade", quem: um, msg: "saiu da grade de " + PASSO + " minutos"});
    else if(x.i < ei || x.f > ef) achados.push({chave: k + "exp", quem: um, msg: "saiu do expediente " + faixa(ei, ef)});
    else if(x.i < af && x.f > ai) achados.push({chave: k + "almoco", quem: um, msg: "invadiu o almo&ccedil;o " + faixa(ai, af)});
    dia.linhas.filter(e => e.tipo === "exist").forEach(e => {
      // Identico ao que ja esta la e o que o servidor trata como "ja existe".
      const identico = e.task === x.l.task && e.i === x.i && e.f === x.f;
      if(x.i < e.f && x.f > e.i && !identico)
        achados.push({chave: k + "e|" + e.i + "|" + e.task, quem: um,
                      msg: "passou a sobrepor " + esc(e.task) + " " + faixa(e.i, e.f) + ", que j&aacute; est&aacute; no ClickUp"});
    });
  });
  for(let a = 0; a < at.length; a++) for(let b = a + 1; b < at.length; b++)
    if(at[a].i < at[b].f && at[b].i < at[a].f)
      achados.push({chave: "p|" + [at[a].l.id, at[b].l.id].sort().join("|"), quem: [at[a], at[b]], par: true});
  return achados;
}

function problemas(dia){
  const porId = {}, achados = achadosDe(dia);
  const de = id => porId[id] || (porId[id] = {culpa: [], tocada: false, seq: 0});
  achados.forEach(p => {
    const c = culpas[p.chave];
    // Sem registro (quebra que ja veio assim), cai na linha mexida por ultimo.
    const culpado = (c && p.quem.find(x => x.l.id === c.id))
      || p.quem.slice().sort((x, y) => ultimoSeq(y.l.id) - ultimoSeq(x.l.id))[0];
    const outro = p.par ? p.quem.find(x => x !== culpado) : null;
    const reg = de(culpado.l.id), sq = c ? c.seq : ultimoSeq(culpado.l.id);
    reg.culpa.push(p.par ? "passou a sobrepor a linha de " + esc(outro.l.task) + " " + faixa(outro.i, outro.f) : p.msg);
    // Mais de uma quebra na mesma linha: vale a alteracao mais antiga -- desfaze-la
    // volta a linha para antes de todas.
    if(sq && (!reg.seq || sq < reg.seq)) reg.seq = sq;
    p.quem.forEach(x => { de(x.l.id).tocada = true; });
  });
  return {porId, total: achados.length};
}

function ultimaMudanca(id){
  for(let n = historico.length - 1; n >= 0; n--) if(historico[n].id === id) return historico[n];
  return null;
}
function ultimoSeq(id){ const h = ultimaMudanca(id); return h ? h.seq : 0; }

function podarCulpas(){
  const vivas = new Set();
  dias.forEach(dia => achadosDe(dia).forEach(p => vivas.add(p.chave)));
  Object.keys(culpas).forEach(k => { if(!vivas.has(k)) delete culpas[k]; });
}

function lancamentos(dia){
  // O que vira lancamento no ClickUp: as linhas marcadas, e as que o ajuste do
  // usuario deixou encostadas na mesma task, fundidas. Espelha fundir_contiguos()
  // do Python -- os dois tem que dar a mesma resposta.
  const itens = ativos(dia).map(l => ({i: estado[l.id].ini, dur: estado[l.id].fim - estado[l.id].ini,
                                       task: l.task})).sort((a,c) => a.i - c.i);
  const juntos = [];
  itens.forEach(it => {
    const ant = juntos.length ? juntos[juntos.length - 1] : null;
    if(ant && ant.i + ant.dur === it.i && ant.task === it.task) ant.dur += it.dur;
    else juntos.push(Object.assign({}, it));
  });
  return juntos;
}

function entradasDe(dia){
  // Minutos crus, nao hm(): hm() e formatacao humana e devolve "45min" abaixo de
  // uma hora, que parse_duracao recusa.
  return lancamentos(dia).map(x => hhmm(x.i) + " " + x.dur + "m " + x.task);
}

function comandoDe(data, entradas){
  const CONT = String.fromCharCode(32, 92, 10);
  return "./clickup-time.sh write --date " + data + CONT
    + entradas.map(e => '  --entry "' + e + '"').join(CONT)
    + (FLAGS_AGENDA.length ? CONT + "  " + FLAGS_AGENDA.join(" ") : "")
    + CONT + "  --confirm";
}

function nomeTask(ref){ const t = (dados.tasks || {})[ref]; return t && t.nome ? t.nome : ""; }

function totais(dia){
  const prop = ativos(dia).reduce((a,l) => a + estado[l.id].fim - estado[l.id].ini, 0);
  let prox = 0;
  ativos(dia).forEach(l => { prox += composicao(l).por.proximidade || 0; });
  return {prop, prox, total: dia.d.existing_minutes + prop};
}

// ---- TXT da daily --------------------------------------------------------------
// Texto puro com o resumo do dia, para levar a daily: task, nome, o que foi feito
// e o que ela pede. Mesmas tasks e mesma ordem da tela. O arquivo leva a data do
// dia resumido, nao a de hoje: numa semana inteira, cada dia sai com nome proprio.

function arquivoDaily(d){
  return "daily-" + d.date.slice(8) + "-" + d.date.slice(5,7) + "-" + d.date.slice(0,4) + ".txt";
}

function textoDaily(dia){
  const NL = String.fromCharCode(10), d = dia.d;
  const blocos = tarefasDoDia(dia).ordem.map(ref => {
    const t = (dados.tasks || {})[ref] || {}, r = dia.resumo[ref] || {};
    return [ref + (t.nome ? " — " + t.nome : ""),
            r.feito ? "O que foi feito: " + r.feito : "",
            r.requisito ? "O que é: " + r.requisito : ""].filter(Boolean).join(NL);
  });
  return ["Daily — " + extenso(d) + "/" + d.date.slice(0,4)].concat(blocos).join(NL + NL) + NL;
}

function baixarTxt(data){
  const dia = dias.find(x => x.d.date === data);
  if(!dia) return;
  const nome = arquivoDaily(dia.d);
  const url = URL.createObjectURL(new Blob([textoDaily(dia)], {type: "text/plain;charset=utf-8"}));
  const a = document.createElement("a");
  a.href = url; a.download = nome;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Baixado: " + nome);
}

// ---- tema -----------------------------------------------------------------------
// Sem escolha, segue o sistema, e acompanha se ele mudar. A escolha vai num
// cookie, nao no localStorage: a porta do front muda a cada subida e o
// localStorage e por origem com porta, entao a escolha sumiria toda vez. Cookie
// e por host. Voltar ao tema do sistema apaga a escolha.

const TEMA = "clickup-time-tema";
const escuroNoSistema = window.matchMedia("(prefers-color-scheme: dark)");
function temaEscolhido(){
  const c = document.cookie.split("; ").find(x => x.indexOf(TEMA + "=") === 0);
  const v = c ? c.slice(TEMA.length + 1) : "";
  return v === "dark" || v === "light" ? v : null;
}
function temaDoSistema(){ return escuroNoSistema.matches ? "dark" : "light"; }
function temaNoFrame(fr){
  // Previa e resultado vem prontos do servidor, com o mesmo CSS de tokens: basta
  // repassar a escolha. srcdoc e mesma origem, entao o documento e acessivel.
  try{
    const raiz = fr.contentDocument && fr.contentDocument.documentElement, v = temaEscolhido();
    if(!raiz) return;
    if(v) raiz.setAttribute("data-theme", v); else raiz.removeAttribute("data-theme");
  }catch(e){}
}
function aplicarTema(){
  const v = temaEscolhido(), raiz = document.documentElement, escuro = (v || temaDoSistema()) === "dark";
  if(v) raiz.setAttribute("data-theme", v); else raiz.removeAttribute("data-theme");
  const rot = escuro ? "Mudar para o tema claro" : "Mudar para o tema escuro";
  $("#tema").setAttribute("aria-label", rot); $("#tema").title = rot;
  $$("iframe").forEach(temaNoFrame);
}
$("#tema").onclick = () => {
  const novo = (temaEscolhido() || temaDoSistema()) === "dark" ? "light" : "dark";
  document.cookie = novo === temaDoSistema()
    ? TEMA + "=; max-age=0; path=/; SameSite=Strict"
    : TEMA + "=" + novo + "; max-age=31536000; path=/; SameSite=Strict";
  aplicarTema();
};
escuroNoSistema.addEventListener("change", aplicarTema);
$("#framePrevia").addEventListener("load", e => temaNoFrame(e.target));
aplicarTema();

// ---- aba Lista --------------------------------------------------------------

function opcoes(de, ate, sel){
  // Na grade absoluta (08:00, 08:15...), nao a partir do inicio da janela: uma
  // janela que abre 09:05, depois de um evento, nao pode oferecer 09:20.
  const o = [];
  for(let m = Math.ceil(de / PASSO) * PASSO; m <= ate; m += PASSO)
    o.push('<option value="' + m + '"' + (m === sel ? " selected" : "") + ">" + hhmm(m) + "</option>");
  return o.join("");
}

// Uma linha da tabela: intervalo, duracao, tarefa e o que foi encontrado, cada um
// na sua coluna. Ate 25/09/2026 era uma grade com as notas penduradas embaixo da
// linha, e a hora editavel, a task e a justificativa se misturavam na leitura.
function celulaTask(ref, nome){
  return '<td class="c-task"><span class="ref">' + esc(ref) + "</span>"
    + (nome ? '<span class="nome">' + esc(nome) + "</span>" : "") + "</td>";
}

function opcoesDur(max, sel){
  const o = [];
  for(let m = PASSO; m <= max; m += PASSO)
    o.push('<option value="' + m + '"' + (m === sel ? " selected" : "") + ">" + hm(m) + "</option>");
  return o.join("");
}

function descreverMudanca(h){
  if(h.campo === "incluir") return h.depois.incluir ? "Voc&ecirc; marcou esta linha" : "Voc&ecirc; desmarcou esta linha";
  if(h.campo === "ini") return "Voc&ecirc; mudou o in&iacute;cio de " + hhmm(h.antes.ini) + " para " + hhmm(h.depois.ini);
  if(h.campo === "fim") return "Voc&ecirc; mudou o fim de " + hhmm(h.antes.fim) + " para " + hhmm(h.depois.fim);
  return "Voc&ecirc; mudou a dura&ccedil;&atilde;o de " + hm(h.antes.fim - h.antes.ini) + " para " + hm(h.depois.fim - h.depois.ini);
}

function linhaHtml(dia, l, prob){
  if(l.tipo === "exist")
    return '<tr class="exist"><td class="c-inc"></td><td class="c-int">' + faixa(l.i, l.f) + "</td>"
      + '<td class="c-dur">' + hm(l.f - l.i) + "</td>" + celulaTask(l.task, l.nome)
      + '<td class="c-achado"><p class="fixo"><span class="selo ' + (l.agora ? "agora" : "gravado") + '">'
      + (l.agora ? "gravado agora" : "no ClickUp") + "</span>"
      + (l.agora ? "gravado por esta tela" : "j&aacute; apontado; fica como est&aacute;") + "</p></td></tr>";
  if(l.tipo === "vazio")
    return '<tr class="vazia"><td class="c-inc"></td><td class="c-int">' + faixa(l.i, l.f) + "</td>"
      + '<td class="c-dur">' + hm(l.f - l.i) + "</td>"
      + '<td class="c-task"><span class="semtask">sem task</span></td>'
      + '<td class="c-achado"><p class="fixo"><span class="selo vazio">pendente</span>'
      + "nada encontrado; pe&ccedil;a ao agente no terminal</p></td></tr>";

  const e = estado[l.id], c = composicao(l), sc = dados.schedule;
  const ei = min(sc.work_start), ef = min(sc.work_end);
  const pr = prob.porId[l.id], quebra = pr && pr.culpa.length ? pr : null;
  const h = quebra ? historico.find(x => x.seq === quebra.seq) : null;
  const notas = c.notas.map(n => '<li><span class="marca"><span class="selo ' + esc(n.origem) + '">'
      + esc(ROTULO[n.origem] || n.origem) + '</span><span class="h">' + faixa(n.i, n.f) + "</span></span>"
      + esc(n.nota) + "</li>")
    .concat(c.por.ajuste ? ['<li><span class="marca"><span class="selo ajuste">' + ROTULO.ajuste + " "
      + hm(c.por.ajuste) + "</span></span>Esticado na tela al&eacute;m do proposto, sem nota: a justificativa &eacute; sua.</li>"] : [])
    .join("");
  return '<tr class="' + (e.incluir ? "" : "desmarcada") + (pr && pr.tocada ? " conflito" : "") + '">'
    + '<td class="c-inc"><input type="checkbox" data-incluir="' + l.id + '"' + (e.incluir ? " checked" : "")
    + ' aria-label="Incluir ' + esc(l.task) + " " + hhmm(e.ini) + '"></td>'
    + '<td class="c-int"><span class="horas"><select data-ini="' + l.id + '" aria-label="In&iacute;cio">'
    + opcoes(ei, ef - PASSO, e.ini) + "</select>&ndash;"
    + '<select data-fim="' + l.id + '" aria-label="Fim">' + opcoes(ei + PASSO, ef, e.fim) + "</select></span></td>"
    + '<td class="c-dur"><select data-dur="' + l.id + '" aria-label="Dura&ccedil;&atilde;o">'
    + opcoesDur(ef - e.ini, e.fim - e.ini) + "</select></td>"
    + celulaTask(l.task, nomeTask(l.task))
    + '<td class="c-achado">' + (notas ? '<ul class="notas">' + notas + "</ul>" : "")
    + (e.sobra ? '<p class="sobra">Sobrou da grava&ccedil;&atilde;o anterior deste dia e voltou desmarcado. Marque se quiser gravar.</p>' : "")
    + "</td></tr>"
    // O aviso fica logo abaixo da linha cuja alteracao quebrou, com o desfazer ali.
    + (quebra ? '<tr class="quebra"><td class="c-inc"></td><td class="c-quebra" colspan="4"><div class="caixa-quebra">'
      + "<p><b>Esta altera&ccedil;&atilde;o quebrou o hor&aacute;rio.</b> "
      + (h ? descreverMudanca(h) + " e a linha " : "A linha ") + quebra.culpa.join("; ")
      + ". A grava&ccedil;&atilde;o deste dia fica travada at&eacute; voc&ecirc; ajustar ou desfazer.</p>"
      + (h ? '<button class="calmo" data-desfazer="' + l.id + '" data-seq="' + h.seq + '">Desfazer esta altera&ccedil;&atilde;o</button>' : "")
      + "</div></td></tr>" : "");
}

function diaHtml(dia){
  const prob = problemas(dia), t = totais(dia), d = dia.d;
  const alvo = d.target_minutes;
  const classe = t.total > alvo ? " acima" : (t.total === alvo ? " cheio" : "");
  let aviso = "";
  if(t.prox){
    aviso = "<b>" + hm(t.prox) + " por proximidade</b> &mdash; sem evid&ecirc;ncia nas transcri&ccedil;&otilde;es, "
      + "preenchidas com a task vizinha para fechar o dia."
      + (t.prox * 2 > t.prop ? " <b>&Eacute; mais da metade do que est&aacute; proposto.</b>" : "")
      + " Se foi outra coisa, diga ao agente no terminal.";
  }
  const foras = dia.foras.map(x => "<li>O plano cobria " + faixa(x.i, x.f) + " com " + esc(x.task)
    + (x.sobre ? ", mas ali j&aacute; h&aacute; " + esc(x.sobre.task) + " no ClickUp" : ", fora das janelas livres")
    + " &mdash; ficou fora da proposta.</li>").join("");
  return '<article class="dia"><div class="cab-dia"><h2>' + esc(curto(d)) + "</h2>"
    + '<span class="rotulo">j&aacute; apontado ' + hm(d.existing_minutes) + " &middot; proposto " + hm(t.prop) + "</span>"
    + '<span class="total' + classe + '">' + hm(t.total) + " / " + hm(alvo) + "</span></div>"
    + (dia.temPlano ? "" : '<p class="aviso">Sem plano do agente para este dia: s&oacute; as &acirc;ncoras do script.</p>')
    + '<div class="tabela"><table class="grade"><thead><tr>'
    + '<th class="c-inc" scope="col"><span hidden>Incluir</span></th><th class="c-int" scope="col">Intervalo</th>'
    + '<th class="c-dur" scope="col">Dura&ccedil;&atilde;o</th><th class="c-task" scope="col">Tarefa</th>'
    + '<th class="c-achado" scope="col">O que foi encontrado</th></tr></thead><tbody>'
    + dia.linhas.map(l => linhaHtml(dia, l, prob)).join("") + "</tbody></table></div>"
    + (prob.total ? '<p class="conflito-aviso">' + (prob.total > 1 ? prob.total + " quebras de hor&aacute;rio" : "Uma quebra de hor&aacute;rio")
      + " neste dia. A grava&ccedil;&atilde;o fica travada at&eacute; ajustar ou desfazer &mdash; o aviso est&aacute; abaixo da linha que quebrou.</p>" : "")
    + (t.total > alvo ? '<p class="preenchido">O dia passa da meta de ' + hm(alvo) + " em " + hm(t.total - alvo) + ".</p>" : "")
    + (aviso ? '<p class="preenchido">' + aviso + "</p>" : "")
    + (foras ? '<ul class="foras">' + foras + "</ul>" : "")
    + '<div class="acoes" style="margin-top:.5rem"><button class="calmo" data-restaurar="' + d.date
    + '">Restaurar proposta</button></div></article>';
}

function tarefasDoDia(dia){
    // Quais tasks: as propostas marcadas, as que o front acabou de gravar e as
    // que o plano resumiu. As horas somam o que ja esta no ClickUp daquela task:
    // depois de gravar, a proposta vira lancamento e as horas nao podem zerar.
    const horas = {}, ordem = [];
    const conta = (t, m) => { if(!(t in horas)){ horas[t] = 0; ordem.push(t); } horas[t] += m; };
    const trechos = [].concat(
      ativos(dia).map(l => ({task: l.task, i: estado[l.id].ini, m: estado[l.id].fim - estado[l.id].ini})),
      dia.linhas.filter(l => l.tipo === "exist" && (l.agora || l.task in dia.resumo))
                .map(l => ({task: l.task, i: l.i, m: l.f - l.i})));
    trechos.sort((a,b) => a.i - b.i).forEach(x => conta(x.task, x.m));
    Object.keys(dia.resumo).forEach(t => conta(t, 0));
    return {ordem, horas};
}

function resumosHtml(){
  const blocos = dias.map(dia => {
    const td = tarefasDoDia(dia), ordem = td.ordem, horas = td.horas;
    if(!ordem.length) return "";
    const itens = ordem.map(ref => {
      const t = (dados.tasks || {})[ref] || {}, r = dia.resumo[ref] || {};
      return '<div class="tarefa"><div class="cab"><b>' + esc(ref) + "</b><span>" + esc(t.nome || "") + "</span>"
        + (t.status ? '<span class="rotulo">' + esc(t.status) + "</span>" : "")
        + (t.url ? '<a href="' + esc(t.url) + '" target="_blank" rel="noopener">abrir no ClickUp</a>' : "")
        + '<span class="horas">' + (horas[ref] ? hm(horas[ref]) + " no dia" : "sem horas no dia") + "</span></div>"
        + (r.requisito ? '<p><span class="rotulo">Requisito</span>' + esc(r.requisito) + "</p>"
                       : '<p class="falta">Sem resumo do requisito no plano.</p>')
        + (r.feito ? '<p><span class="rotulo">Feito</span>' + esc(r.feito) + "</p>"
                   : '<p class="falta">Sem descri&ccedil;&atilde;o do que foi feito no plano.</p>')
        + "</div>";
    }).join("");
    return '<div class="resumo-dia"><h3>' + esc(curto(dia.d)) + "</h3>" + itens
      + '<div class="acoes baixar"><button class="calmo" data-txt="' + dia.d.date + '">Baixar TXT</button>'
      + '<span class="arquivo">' + esc(arquivoDaily(dia.d)) + "</span></div></div>";
  }).join("");
  return blocos ? "<h2>O que foi feito, por dia</h2>" + blocos : "";
}

function renderLista(){
  const foco = document.activeElement, alvo = foco && ["incluir","ini","fim","dur"].find(k => foco.dataset && foco.dataset[k]);
  const chaveFoco = alvo ? "[data-" + alvo + '="' + foco.dataset[alvo] + '"]' : null;

  $("#fontes").innerHTML = dados.sources.map(f => "<span><b>" + esc(f.nome) + "</b> &mdash; "
    + (f.estado === "ok" ? (f.unidades + " " + (f.unidade||"") + ", " + f.eventos + " eventos") : esc(f.estado))
    + (f.aviso ? " <em>(" + esc(f.aviso) + ")</em>" : "")
    + "</span>").join("");
  $("#dias").innerHTML = dias.map(diaHtml).join("");
  $("#resumos").innerHTML = resumosHtml();

  // Inicio mexe so no inicio (o fim fica), fim so no fim, duracao mexe no fim.
  // Nenhum deles se limita a janela livre: quebrar e permitido, e aponta a culpada.
  $$("[data-incluir]").forEach(el => el.onchange = () =>
    mudar(el.dataset.incluir, "incluir", e => { e.incluir = el.checked; }));
  $$("[data-ini]").forEach(el => el.onchange = () => mudar(el.dataset.ini, "ini", e => {
    e.ini = parseInt(el.value, 10); if(e.fim <= e.ini) e.fim = e.ini + PASSO; }));
  $$("[data-fim]").forEach(el => el.onchange = () => mudar(el.dataset.fim, "fim", e => {
    e.fim = parseInt(el.value, 10); if(e.ini >= e.fim) e.ini = e.fim - PASSO; }));
  $$("[data-dur]").forEach(el => el.onchange = () => mudar(el.dataset.dur, "dur", e => {
    e.fim = e.ini + parseInt(el.value, 10); }));
  $$("[data-desfazer]").forEach(b => b.onclick = () => desfazer(b.dataset.desfazer, parseInt(b.dataset.seq, 10)));
  $$("[data-txt]").forEach(b => b.onclick = () => baixarTxt(b.dataset.txt));
  $$("[data-restaurar]").forEach(b => b.onclick = () => {
    const dia = dias.find(x => x.d.date === b.dataset.restaurar);
    dia.props.forEach(l => { estado[l.id] = {incluir: true, ini: l.i0, fim: l.f0, i0: l.i0, f0: l.f0}; });
    historico = historico.filter(h => !dia.props.some(l => l.id === h.id));
    Object.keys(culpas).forEach(k => { if(dia.props.some(l => culpas[k].id === l.id)) delete culpas[k]; });
    renderTudo(); toast("Proposta restaurada para " + curto(dia.d));
  });
  if(chaveFoco){ const el = document.querySelector(chaveFoco); if(el) el.focus(); }
}

function diaDaLinha(id){ return dias.find(dia => dia.props.some(l => l.id === id)); }

function mudar(id, campo, aplicar){
  const e = estado[id], antes = {incluir: e.incluir, ini: e.ini, fim: e.fim};
  aplicar(e);
  if(e.incluir === antes.incluir && e.ini === antes.ini && e.fim === antes.fim) return;
  const h = {id, campo, antes, depois: {incluir: e.incluir, ini: e.ini, fim: e.fim}, seq: ++seq};
  historico.push(h);
  // Toda quebra que surgiu agora envolve esta linha, porque so ela mudou.
  let quebrou = false;
  achadosDe(diaDaLinha(id)).forEach(p => {
    if(culpas[p.chave]) return;
    culpas[p.chave] = {id, seq: h.seq}; quebrou = true;
  });
  renderTudo();
  if(quebrou) toast("Essa alteração quebrou o horário — o aviso está abaixo da linha", true);
}

function desfazer(id, sq){
  // Volta a linha para antes da alteracao que quebrou. Os ajustes feitos nela
  // depois disso saem junto: eram em cima de um estado quebrado.
  const n = historico.findIndex(x => x.id === id && x.seq === sq);
  if(n < 0) return;
  const h = historico[n];
  historico = historico.filter((x, k) => k < n || x.id !== id);
  Object.assign(estado[id], h.antes);
  renderTudo();
  const el = document.querySelector("[data-" + h.campo + '="' + id + '"]');
  if(el) el.focus();
  toast("Alteração desfeita");
}

// ---- aba Gravar -------------------------------------------------------------

function renderGravar(){
  $("#avisoGravar").innerHTML = PODE_GRAVAR
    ? "Grava s&oacute; as linhas marcadas na Lista. O servidor revalida antes: almo&ccedil;o, expediente, grade de "
      + PASSO + " minutos, sobreposi&ccedil;&atilde;o e duplicata."
    : "Modo somente-leitura: use o comando no terminal.";

  const cartoes = dias.map(dia => {
    const d = dia.d, ent = entradasDe(dia), regs = (gravados[d.date] || {}).registros || [];
    if(!ent.length && !regs.length) return "";
    const ruins = problemas(dia).total > 0, t = totais(dia);
    let html = '<article class="dia"><div class="cab-dia"><h2>' + esc(curto(d)) + "</h2>";
    if(ent.length){
      html += '<span class="total' + (t.total > d.target_minutes ? " acima" : "") + '">dia fica em '
        + hm(t.total) + " / " + hm(d.target_minutes) + "</span></div>"
        + '<div class="lanc"><b>vai gravar ' + ent.length + " lan&ccedil;amento" + (ent.length > 1 ? "s" : "")
        + " &middot; " + hm(t.prop) + "</b>"
        + lancamentos(dia).map(x => "<span>" + faixa(x.i, x.i + x.dur) + " <i>" + hm(x.dur) + "</i> "
            + esc(x.task) + "</span>").join("") + "</div>"
        + (ruins ? '<p class="conflito-aviso">Uma altera&ccedil;&atilde;o na Lista quebrou o hor&aacute;rio. Ajuste ou desfa&ccedil;a antes de gravar.</p>' : "")
        + '<div class="acoes"><button class="calmo" data-previa="' + d.date + '"' + (ruins ? " disabled" : "")
        + ">Gerar pr&eacute;via</button>"
        + (PODE_GRAVAR ? '<button data-gravar="' + d.date + '"' + (ruins ? " disabled" : "") + ">Gravar "
            + esc(extenso(d)) + " (" + ent.length + ")</button>" : "") + "</div>"
        + (ruins ? ""
          : '<span class="rotulo">Ou rode no terminal</span>'
            + '<pre class="cmd" id="cmd-' + d.date + '">' + esc(comandoDe(d.date, ent)) + "</pre>"
            + '<div class="acoes"><button class="calmo" data-copiar="' + d.date + '">Copiar comando</button></div>');
    } else {
      html += '<span class="rotulo" style="margin-left:auto">nada novo para gravar</span></div>';
    }
    // O que ja foi gravado nao some: fica inativo, com hora e comando, para o
    // usuario saber o que entrou sem precisar abrir a planilha.
    regs.slice().reverse().forEach(r => {
      html += '<div class="executado"><div class="acoes"><button class="feito" disabled>'
        + "&check; Gravado &mdash; " + esc(extenso(d)) + " (" + r.entradas.length + ")</button>"
        + '<span class="aviso">executado &agrave;s ' + esc(r.quando)
        + ' &middot; <a href="#" data-ver="' + d.date + '">ver resultado</a></span></div>'
        + '<span class="rotulo">Comando executado</span>'
        + '<pre class="cmd inativo" aria-disabled="true">' + esc(r.comando) + "</pre></div>";
    });
    return html + "</article>";
  }).join("");

  $("#cartoes").innerHTML = cartoes || '<p class="vazio-aba">Nada marcado para gravar. Marque linhas na aba Lista.</p>';
  $$("[data-gravar]").forEach(b => b.onclick = () => gravar(b.dataset.gravar, b));
  $$("[data-previa]").forEach(b => b.onclick = () => previa(b.dataset.previa, b));
  $$("[data-copiar]").forEach(b => b.onclick = () => copiar(b.dataset.copiar));
  $$("[data-ver]").forEach(a => a.onclick = ev => { ev.preventDefault(); diaResultado = a.dataset.ver;
                                                    renderResultados(); mostrarAba("resultados"); });
}

// ---- aba Resultados ---------------------------------------------------------

function renderResultados(){
  const datas = Object.keys(gravados).filter(k => (gravados[k].registros || []).length).sort();
  $("#contResultados").textContent = datas.length ? String(datas.length) : "";
  if(!datas.length){
    $("#subabas").innerHTML = "";
    $("#resultado").innerHTML = '<p class="vazio-aba">Nada gravado nesta sess&atilde;o do front. Depois de gravar um dia, '
      + "o resultado aparece aqui, numa aba com o nome do dia.</p>";
    return;
  }
  if(datas.indexOf(diaResultado) < 0) diaResultado = datas[datas.length - 1];
  const rotulo = k => { const d = (dados.days || []).find(x => x.date === k);
                        return d ? curto(d) : (k.slice(8) + "/" + k.slice(5,7)); };
  $("#subabas").innerHTML = datas.map(k => '<button role="tab" data-sub="' + k + '" aria-selected="'
    + (k === diaResultado) + '">' + esc(rotulo(k)) + "</button>").join("");
  const g = gravados[diaResultado];
  $("#resultado").innerHTML = '<p class="aviso">'
    + g.registros.map(r => "Gravado &agrave;s " + esc(r.quando) + ": " + r.entradas.length + " lan&ccedil;amento"
      + (r.entradas.length > 1 ? "s" : "")).join(" &middot; ")
    + '. Confira a Hora Final na <a href="https://app.clickup.com/90131214647/time" target="_blank" rel="noopener">planilha do ClickUp</a>'
    + " &mdash; a releitura pela API n&atilde;o enxerga esse defeito.</p>"
    + '<iframe title="Resultado gravado de ' + esc(rotulo(diaResultado)) + '"></iframe>';
  const fr = $("#resultado iframe");
  fr.addEventListener("load", () => temaNoFrame(fr));
  fr.srcdoc = g.html || "";
  $$("[data-sub]").forEach(b => b.onclick = () => { diaResultado = b.dataset.sub; renderResultados(); });
}

function renderTudo(){
  podarCulpas();
  renderLista(); renderGravar(); renderResultados();
  const n = dias.filter(dia => entradasDe(dia).length).length;
  $("#contGravar").textContent = n ? String(n) : "";
}

// ---- acoes ------------------------------------------------------------------

async function carregar(){
  erro(""); $("#carregar").disabled = true; $("#carregar").textContent = "Lendo...";
  try{
    const r = await Promise.all([api("/api/sugerir", {from: $("#de").value, to: $("#ate").value}),
                                 api("/api/gravados")]);
    dados = r[0]; gravados = r[1] || {};
    montar(); renderTudo();
  }catch(e){ erro("Falhou ao carregar: " + e.message); }
  $("#carregar").disabled = false;
  $("#carregar").textContent = PERIODO ? "Recarregar" : "Carregar";
}
$("#carregar").onclick = carregar;
if(PERIODO) carregar();

async function copiar(data){
  // writeText rejeita em contexto nao-seguro e quando a aba esta sem foco. Sem o
  // catch, o clique falhava calado e o usuario colava o comando anterior.
  try{ await navigator.clipboard.writeText($("#cmd-" + data).textContent); toast("Comando copiado"); }
  catch(e){ toast("Não consegui copiar — selecione e use Cmd+C", true); }
}

async function previa(data, botao){
  erro("");
  const dia = dias.find(x => x.d.date === data), ent = entradasDe(dia);
  if(!ent.length || problemas(dia).total) return;
  botao.disabled = true; botao.textContent = "Gerando...";
  try{
    const r = await api("/api/previa", {date: data, entries: JSON.stringify(ent)});
    $("#tituloPrevia").textContent = "Prévia — " + curto(dia.d);
    $("#secPrevia").hidden = false;
    $("#framePrevia").srcdoc = r.html;
    $("#secPrevia").scrollIntoView({behavior:"smooth"});
  }catch(e){ erro("Falhou a prévia: " + e.message); }
  botao.disabled = false; botao.textContent = "Gerar prévia";
}

async function gravar(data, botao){
  erro("");
  const dia = dias.find(x => x.d.date === data), ent = entradasDe(dia);
  if(!ent.length || problemas(dia).total) return;

  if(confirmando !== data){
    confirmando = data;
    botao.classList.add("perigo");
    botao.textContent = "Confirmar " + ent.length + " lançamento(s) em " + extenso(dia.d) + "?";
    setTimeout(() => { if(confirmando === data){ confirmando = null; renderGravar(); } }, 12000);
    return;
  }
  confirmando = null;
  botao.disabled = true; botao.textContent = "Gravando...";
  try{
    await api("/api/gravar", null, {date: data, entries: ent, total: ent.length});
    $("#secPrevia").hidden = true;
    await carregar();
    diaResultado = data;
    renderResultados();
    toast("Gravado. O resultado está na aba Resultados.");
  }catch(e){ erro("Falhou ao gravar: " + e.message); renderGravar(); }
}
"""


PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Apontar horas</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Newsreader:opsz,wght@6..72,400&display=swap">
<style>__CSS____ESTILO__</style>
<script>(function(){var n="clickup-time-tema=";var c=document.cookie.split("; ").find(function(x){return x.indexOf(n)===0});
var v=c?c.slice(n.length):"";if(v==="dark"||v==="light")document.documentElement.setAttribute("data-theme",v)})()</script>
</head>
<body><div class="pagina">__CORPO__</div>
<script>__SCRIPT__</script></body></html>
"""


# ------------------------------------------------------------------- plano


def carregar_plano(caminho: str, agenda: ct.Agenda) -> dict:
    """Lê e valida o plano do agente. Devolve `{data: {blocos, resumo}}`.

    Validar aqui, e não na tela, é o que faz o erro do agente voltar para o
    agente: bloco sem nota, fora do expediente, cruzando o almoço ou sobreposto a
    outro do próprio plano para a subida, com a lista de todos os problemas.
    Em 24/09/2026 isso só aparecia depois, na prévia.
    """
    try:
        with open(caminho, encoding="utf-8") as fh:
            bruto = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ct.Erro(f"plano ilegível: {exc}") from None
    if not isinstance(bruto, dict) or not bruto:
        raise ct.Erro('o plano precisa ser um objeto {"AAAA-MM-DD": {"blocos": [...], "resumo": {...}}}')

    def m(t) -> int:
        return t.hour * 60 + t.minute

    exp = (m(agenda.work_start), m(agenda.work_end))
    almoco = (m(agenda.lunch_start), m(agenda.lunch_end))
    problemas: list[str] = []
    avisos: list[str] = []
    plano: dict = {}

    for data, valor in sorted(bruto.items()):
        try:
            if not DATA_ISO.fullmatch(data):
                raise ValueError
            Date.fromisoformat(data)
        except ValueError:
            problemas.append(f"chave {data!r} não é data AAAA-MM-DD")
            continue

        if isinstance(valor, list):
            blocos, resumo = valor, {}
        elif isinstance(valor, dict):
            blocos, resumo = valor.get("blocos") or [], valor.get("resumo") or {}
        else:
            problemas.append(f"{data}: valor precisa ser lista de blocos ou {{blocos, resumo}}")
            continue
        if isinstance(resumo, list):
            resumo = {r.get("task"): r for r in resumo if isinstance(r, dict) and r.get("task")}
        if not isinstance(blocos, list) or not isinstance(resumo, dict):
            problemas.append(f"{data}: `blocos` é lista e `resumo` é objeto por task")
            continue

        limpos, intervalos = [], []
        for n, b in enumerate(blocos, 1):
            rot = f"{data} bloco {n}"
            if not isinstance(b, dict):
                problemas.append(f"{rot}: não é objeto")
                continue
            try:
                ini = m(ct.parse_hora(str(b.get("start", ""))))
            except ct.Erro:
                problemas.append(f"{rot}: start {b.get('start')!r} não é HH:MM")
                continue
            rot = f"{data} {b.get('start')}"
            dur, task = b.get("minutes"), str(b.get("task") or "").strip()
            origem, nota = b.get("origem"), str(b.get("nota") or "").strip()
            if not isinstance(dur, int) or dur <= 0 or dur % agenda.block_minutes:
                problemas.append(f"{rot}: minutes={dur!r} precisa ser múltiplo positivo de "
                                 f"{agenda.block_minutes}")
                continue
            if ini % agenda.block_minutes:
                problemas.append(f"{rot}: início fora da grade de {agenda.block_minutes}min")
            if not task:
                problemas.append(f"{rot}: sem task")
            if origem not in ORIGENS:
                problemas.append(f"{rot}: origem {origem!r} (use {', '.join(ORIGENS)})")
            if not nota:
                problemas.append(f"{rot}: sem nota — sem evidência escrita, não proponha")
            fim = ini + dur
            if ini < exp[0] or fim > exp[1]:
                problemas.append(f"{rot}: fora do expediente "
                                 f"{agenda.work_start:%H:%M}–{agenda.work_end:%H:%M}")
            if ini < almoco[1] and fim > almoco[0]:
                problemas.append(f"{rot}: cruza o almoço "
                                 f"{agenda.lunch_start:%H:%M}–{agenda.lunch_end:%H:%M}")
            intervalos.append((ini, fim, rot))
            limpos.append({"start": f"{ini // 60:02d}:{ini % 60:02d}", "minutes": dur,
                           "task": task, "origem": origem, "nota": nota})

        intervalos.sort()
        for (_, f1, r1), (i2, _, r2) in zip(intervalos, intervalos[1:]):
            if f1 > i2:
                problemas.append(f"{r2}: sobrepõe o bloco de {r1.split(' ')[1]}")

        tasks = {b["task"] for b in limpos}
        sem = sorted(tasks - set(resumo))
        if sem:
            avisos.append(f"{data}: sem resumo para {', '.join(sem)}")
        for ref, r in resumo.items():
            if not isinstance(r, dict) or not r.get("requisito") or not r.get("feito"):
                avisos.append(f"{data}: resumo de {ref} sem `requisito` ou sem `feito`")
        plano[data] = {"blocos": limpos,
                       "resumo": {k: {"requisito": str((v or {}).get("requisito") or ""),
                                      "feito": str((v or {}).get("feito") or "")}
                                  for k, v in resumo.items() if isinstance(v, dict)}}

    if problemas:
        raise ct.Erro("plano recusado:\n  " + "\n  ".join(problemas))
    for a in avisos:
        print(f"  \033[33m⚠ plano: {a}\033[0m")
    return plano


def flags_agenda(agenda: ct.Agenda, tz) -> list[str]:
    """As flags que o comando do terminal precisa para bater com a tela.

    Sem elas, o comando copiado de um dia com almoço 13:00–13:30 rodaria com o
    almoço padrão (12:00–13:30) e o `write` bloquearia o proposto entre 12:00 e 13:00.
    """
    pares = [
        ("--work-start", agenda.work_start, ct.WORK_START),
        ("--work-end", agenda.work_end, ct.WORK_END),
        ("--lunch-start", agenda.lunch_start, ct.LUNCH_START),
        ("--lunch-end", agenda.lunch_end, ct.LUNCH_END),
    ]
    saida = []
    for flag, valor, padrao in pares:
        if valor != padrao:
            saida += [flag, valor.strftime("%H:%M")]
    if agenda.block_minutes != ct.BLOCK_MINUTES:
        saida += ["--block-minutes", str(agenda.block_minutes)]
    if agenda.target_minutes != ct.TARGET_MINUTES:
        saida += ["--target-minutes", str(agenda.target_minutes)]
    if str(tz) != ct.TIMEZONE_PADRAO:
        saida += ["--timezone", str(tz)]
    return saida


def comando_de(dia: Date, entradas: list[str], agenda: ct.Agenda, tz) -> str:
    """Mesmo texto que a tela monta em `comandoDe()`."""
    linhas = [f"./clickup-time.sh write --date {dia.isoformat()}"]
    linhas += [f'  --entry "{e}"' for e in entradas]
    fl = flags_agenda(agenda, tz)
    if fl:
        linhas.append("  " + " ".join(fl))
    linhas.append("  --confirm")
    return " \\\n".join(linhas)


def _para_script(obj) -> str:
    # Nota de transcrição pode trazer "</script>"; escapado assim, continua JSON
    # válido e não fecha a tag.
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


# ----------------------------------------------------------------- servidor


class Handler(BaseHTTPRequestHandler):
    token: str = ""
    tz = None
    agenda = None
    pode_gravar: bool = True
    plano: dict = {}
    periodo: dict | None = None
    # O que esta sessão gravou, por data. Vive na memória do processo: é o que
    # deixa o botão do dia inativo com a hora da gravação e a aba Resultados com
    # um dia por aba, mesmo depois de recarregar a página.
    gravados: dict = {}
    trava = threading.Lock()

    def log_message(self, *_):
        pass

    def _autorizado(self, q) -> bool:
        if not secrets.compare_digest((q.get("k") or [""])[0], SEGREDO):
            return False
        origem = self.headers.get("Origin")
        if origem and not origem.startswith(("http://127.0.0.1:", "http://localhost:")):
            return False
        return (self.headers.get("Host") or "").startswith(("127.0.0.1", "localhost"))

    def _responder(self, corpo: bytes, tipo: str, codigo: int = 200) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, obj, codigo: int = 200) -> None:
        self._responder(json.dumps(obj, ensure_ascii=False).encode(),
                        "application/json; charset=utf-8", codigo)

    def _erro(self, msg, codigo: int = 400) -> None:
        self._responder(str(msg).encode(), "text/plain; charset=utf-8", codigo)

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if not self._autorizado(q):
            self._erro("nao autorizado", 403)
            return

        if url.path == "/":
            script = (SCRIPT
                      .replace("__PODE_GRAVAR__", "true" if self.pode_gravar else "false")
                      .replace("__PLANO__", _para_script(self.plano))
                      .replace("__PERIODO__", _para_script(self.periodo))
                      .replace("__FLAGS_AGENDA__", _para_script(flags_agenda(self.agenda, self.tz)))
                      .replace("__PASSO__", str(self.agenda.block_minutes)))
            pagina = (PAGINA
                      .replace("__CSS__", cth.CSS)
                      .replace("__ESTILO__", ESTILO)
                      .replace("__CORPO__", CORPO)
                      .replace("__SCRIPT__", script))
            self._responder(pagina.encode(), "text/html; charset=utf-8")
            return

        try:
            if url.path == "/api/sugerir":
                de = Date.fromisoformat(q["from"][0])
                ate = Date.fromisoformat(q["to"][0])
                if (ate - de).days > 31:
                    raise ct.Erro("intervalo maior que 31 dias")
                dados = ct.montar_sugestao(de, ate, self.tz, self.agenda, self.token)
                dados["tasks"] = self._tasks(dados)
                self._json(dados)
                return

            if url.path == "/api/gravados":
                with self.trava:
                    self._json(self.gravados)
                return

            if url.path == "/api/previa":
                dia = Date.fromisoformat(q["date"][0])
                entradas = self._entradas(json.loads(q["entries"][0]))
                self._json({"html": self._montar_html(dia, entradas)})
                return
        except (ct.Erro, KeyError, ValueError, json.JSONDecodeError) as exc:
            self._erro(exc)
            return

        self._erro("nao encontrado", 404)

    def _tasks(self, dados: dict) -> dict:
        """Nome, status e link de cada task que a tela vai mostrar. O requisito e
        o que foi feito vêm do plano: resumir é trabalho do agente."""
        refs = set()
        for d in dados["days"]:
            refs |= {b["task"] for b in d["blocks"] if b.get("task")}
            refs |= {e["task"] for e in d.get("existing", []) if e.get("task")}
            p = self.plano.get(d["date"]) or {}
            refs |= {b["task"] for b in p.get("blocos", [])}
            refs |= set(p.get("resumo", {}))
        saida = {}
        for ref in sorted(refs):
            try:
                t = ct.detalhar_task(ref, self.token, max_chars=0)
                saida[ref] = {"nome": t["nome"], "status": t["status"], "url": t["url"]}
            except ct.Erro as e:
                saida[ref] = {"nome": "", "status": "", "url": "", "erro": str(e).splitlines()[0]}
        return saida

    # ----------------------------------------------------------------- POST

    def do_POST(self) -> None:
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if not self._autorizado(q):
            self._erro("nao autorizado", 403)
            return
        if url.path != "/api/gravar":
            self._erro("nao encontrado", 404)
            return
        if not self.pode_gravar:
            self._erro("servidor em modo somente-leitura", 403)
            return

        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            if tamanho > 64 * 1024:
                raise ct.Erro("corpo grande demais")
            corpo = json.loads(self.rfile.read(tamanho) or b"{}")
            dia = Date.fromisoformat(corpo["date"])
            entradas = self._entradas(corpo.get("entries"))
            # A contagem vem do cliente e é conferida aqui: um POST repetido com
            # lista diferente da que a tela mostrou não passa.
            if int(corpo.get("total", -1)) != len(entradas):
                raise ct.Erro("confirmacao nao bate com as entradas")

            # Mesmo caminho do `write --confirm`: preflight, guardrails,
            # fingerprint. A saída humana vira log da resposta.
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                codigo = ct.escrever(dia, entradas, self.tz, self.agenda, self.token,
                                     confirmar=True)
            log = buffer.getvalue()
            if codigo != 0:
                raise ct.Erro(log or "escrita bloqueada")
            html = self._montar_html(dia, [], final=True)
            registro = {"quando": datetime.now(self.tz).strftime("%H:%M"),
                        "entradas": entradas,
                        "comando": comando_de(dia, entradas, self.agenda, self.tz)}
            with self.trava:
                g = self.gravados.setdefault(dia.isoformat(), {"registros": [], "html": ""})
                g["registros"].append(registro)
                g["html"] = html
            self._json({"ok": True, "log": log, "html": html, "registro": registro})
        except (ct.Erro, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._erro(exc)

    # --------------------------------------------------------------- comuns

    @staticmethod
    def _entradas(bruto) -> list[str]:
        if not isinstance(bruto, list) or len(bruto) > 40:
            raise ct.Erro("lista de entradas invalida")
        return [str(e) for e in bruto]

    def _montar_html(self, dia: Date, entradas: list[str], final: bool = False) -> str:
        """Sem `final`, é o mesmo caminho do `write` sem --confirm: zero POST."""
        existente = ct.ler(dia, dia, self.tz, self.agenda, self.token)[0]
        cands = None
        if not final:
            cands = ct.montar_candidatos(dia, entradas, self.tz, self.agenda)
            for c in cands:
                try:
                    c.task_id, custom, c.task_nome = ct.resolver_task(c.ref, self.token)
                    c.ref = custom or c.ref
                except ct.Erro as e:
                    c.bloquear(str(e))
            ct.validar_candidatos(cands, existente, self.agenda, self.tz)
        agora = datetime.now(self.tz).strftime("%d/%m/%Y %H:%M")
        return cth.gerar([{"dia": existente, "novos": cands}], self.agenda, self.tz,
                         None, agora, previa=not final)


def subir(tz, agenda, token: str, abrir: bool = True, pode_gravar: bool = True,
          plano: dict | None = None, fundo: bool = False) -> int:
    Handler.token, Handler.tz, Handler.agenda = token, tz, agenda
    Handler.pode_gravar = pode_gravar
    Handler.plano = plano or {}
    Handler.gravados = {}
    # O período sai das chaves do plano: quem já pesquisou não deve ser obrigado
    # a informar de novo qual intervalo pesquisou.
    datas = sorted(plano or {})
    Handler.periodo = {"de": datas[0], "ate": datas[-1]} if datas else None

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    porta = servidor.server_address[1]
    url = f"http://127.0.0.1:{porta}/?k={SEGREDO}"

    print(f"\n\033[1mfront local:\033[0m {url}")
    print("  \033[2m127.0.0.1 apenas · segredo exigido em toda requisição · "
          "GET nunca muta\033[0m")
    if pode_gravar:
        print("  \033[33mgrava\033[0m \033[2m(dupla confirmação na tela + revalidação no "
              "servidor) — `--somente-leitura` desliga\033[0m")
    else:
        print("  \033[2msomente leitura: monta o comando para o terminal\033[0m")
    if plano:
        print(f"  \033[2mplano do agente: {len(plano)} dia(s)\033[0m")
    print("  \033[2mo token fica na memória deste processo — Ctrl-C ao terminar\033[0m\n")

    if fundo:
        # O socket já existe, então a URL é conhecida antes do fork. O pai
        # imprime e sai com _exit para não rodar finally e fechar o socket que
        # o filho herdou.
        os.makedirs(ESTADO, exist_ok=True)
        print("  \033[2mrodando em segundo plano · "
              "`./clickup-time.sh front --parar` encerra\033[0m\n")
        # _exit não esvazia o buffer: com a saída num pipe, a URL se perdia
        # (24/09/2026). Esvaziar antes do fork também impede o filho de herdar
        # e repetir o que já foi impresso.
        sys.stdout.flush()
        if os.fork() > 0:
            os._exit(0)
        os.setsid()
        with open(os.path.join(ESTADO, "front.pid"), "w") as fh:
            fh.write(str(os.getpid()))
        with open(os.path.join(ESTADO, "front.url"), "w") as fh:
            fh.write(url)
        nulo = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(nulo, fd)
    elif abrir:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado.")
    finally:
        servidor.server_close()
    return 0


def parar() -> int:
    """Encerra o front que estiver em segundo plano."""
    caminho = os.path.join(ESTADO, "front.pid")
    try:
        with open(caminho) as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        print("nenhum front em segundo plano encontrado.")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"front encerrado (pid {pid}).")
    except ProcessLookupError:
        print("o processo já não existe.")
    except PermissionError:
        print(f"sem permissão para encerrar o pid {pid}.")
        return 1
    finally:
        for nome in ("front.pid", "front.url"):
            try:
                os.remove(os.path.join(ESTADO, nome))
            except OSError:
                pass
    return 0
