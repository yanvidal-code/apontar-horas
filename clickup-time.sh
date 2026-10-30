#!/usr/bin/env bash
#
# clickup-time.sh — apontamento de horas no ClickUp.
#
# Procedimento completo em SKILL.md, ao lado deste arquivo.
#
# Uso:
#   ./clickup-time.sh read    --from 2026-09-01 --to 2026-09-04 [--json] [--html]
#   ./clickup-time.sh sugerir --from 2026-09-01 --to 2026-09-04 [--json]
#   ./clickup-time.sh tarefas HM-423 HM-386 [--json]
#   ./clickup-time.sh write   --date 2026-09-02 --entry \"09:00 45m HM-204\"
#   ./clickup-time.sh write   --date 2026-09-02 --entry \"...\" --confirm
#   ./clickup-time.sh digital                 # grava o token; leituras pedem a digital
#
# `read`, `sugerir` e `tarefas` só leem. `write` sem --confirm é prévia e não grava nada.
#
# Agenda (padrões, todos sobrescrevíveis):
#   --work-start 08:00  --work-end 18:00
#   --lunch-start 12:00 --lunch-end 13:30
#   --block-minutes 15  --target-minutes 510   # 8h30, igual à meta do ClickUp
#   --timezone America/Fortaleza
#
# Credencial:
#   O token sai do Keychain (service `clickup-irrah-tech`), lido pelo clickup-token
#   depois da digital — nunca de arquivo, de variável de ambiente ou do chat. O
#   `./apontar` configura na primeira vez; para trocar o token, num terminal seu:
#
#     ./clickup-time.sh digital     # pede o token sem eco
#
# A meta de 8h30 é CONFERÊNCIA, não trava: o `read` mostra quanto falta em cada
# dia e quais faixas continuam livres. Quem decide o que apontar é você.
#
# Requer: python3 e macOS com Keychain; gh logado para a fonte GitHub (opcional).
# O clickup-token vem pronto em bin/; só quem mantém a skill precisa do Xcode,
# para `digital --compilar`. O único POST do módulo está atrás do `write --confirm`.

set -euo pipefail

# Resolve symlink: chamado pelo atalho da raiz, o BASH_SOURCE aponta para o
# atalho, e os módulos irmãos (clickup_time_html, _transcricao) não seriam
# encontrados.
ORIGEM="${BASH_SOURCE[0]}"
while [ -L "$ORIGEM" ]; do
  DESTINO="$(readlink "$ORIGEM")"
  case "$DESTINO" in
    /*) ORIGEM="$DESTINO";;
     *) ORIGEM="$(cd "$(dirname "$ORIGEM")" && pwd)/$DESTINO";;
  esac
done
SCRIPT_DIR="$(cd "$(dirname "$ORIGEM")" && pwd)"

exec python3 "$SCRIPT_DIR/clickup_time.py" "$@"
