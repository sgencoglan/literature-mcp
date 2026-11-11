#!/usr/bin/env bash
# Lint + version check. `validate_all.sh` runs the tests; this script runs the
# static checks that do not need a full test environment.
#
# Kullanım:
#   bash scripts/lint.sh
#   RUFF=/path/to/ruff bash scripts/lint.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-}"
if [[ -z "$PY" && -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="${PY:-python3}"
fi

fail=0

echo "== Sürüm tutarlılığı =="
if ! "$PY" scripts/check_version.py; then
  fail=1
fi

echo
echo "== Ruff =="
if [[ -n "${RUFF:-}" ]]; then
  ruff_bin="$RUFF"
elif [[ -x "$ROOT/.venv/bin/ruff" ]]; then
  ruff_bin="$ROOT/.venv/bin/ruff"
elif command -v ruff >/dev/null 2>&1; then
  ruff_bin="$(command -v ruff)"
else
  ruff_bin=""
fi

if [[ -z "$ruff_bin" ]]; then
  echo "ruff bulunamadı; atlandı (pip install ruff)."
else
  if ! "$ruff_bin" check .; then
    fail=1
  fi
fi

if (( fail )); then
  echo
  echo "STATİK KONTROL BAŞARISIZ" >&2
  exit 1
fi

echo
echo "STATİK KONTROL TAMAM"
