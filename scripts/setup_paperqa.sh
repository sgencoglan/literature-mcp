#!/usr/bin/env bash
# PaperQA2 indeksi için eksik bağımlılıkları kurar.
#
# CPU-only PyTorch kurulur; CUDA paketleri indirilmez. Ardından PaperQA2,
# sentence-transformers, MCP, PyMuPDF ve httpx kurulur.
#
# Kullanım:
#   bash scripts/setup_paperqa.sh
#   bash scripts/setup_paperqa.sh --check
#   PYTHON=/path/to/python bash scripts/setup_paperqa.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi

check_deps() {
  "$PY" - <<'PY'
import sys

problems = []
try:
    import torch
    print(f"torch: {torch.__version__} (CUDA: {torch.version.cuda or 'yok'})")
    if torch.version.cuda:
        problems.append(
            "PyTorch CUDA sürümü kurulu; CPU-only kurulum için "
            "scripts/setup_paperqa.sh çalıştırın."
        )
except Exception as exc:  # noqa: BLE001
    problems.append(f"torch eksik/bozuk: {exc}")

try:
    import sentence_transformers
    print(f"sentence-transformers: {sentence_transformers.__version__}")
except Exception as exc:  # noqa: BLE001
    problems.append(f"sentence-transformers eksik/bozuk: {exc}")

try:
    import paperqa
    print("paperqa: OK")
except Exception as exc:  # noqa: BLE001
    problems.append(f"paperqa eksik/bozuk: {exc}")

try:
    import pymupdf
    print(f"PyMuPDF: {pymupdf.__version__}")
except Exception as exc:  # noqa: BLE001
    problems.append(f"PyMuPDF eksik/bozuk: {exc}")

if problems:
    print("\nEksikler:", file=sys.stderr)
    for problem in problems:
        print(f"- {problem}", file=sys.stderr)
    raise SystemExit(1)
print("\nPaperQA indeksi için bağımlılıklar hazır.")
PY
}

if [[ "${1:-}" == "--check" ]]; then
  check_deps
  exit 0
fi

echo "Python: $PY"
echo "CPU-only PyTorch kuruluyor (CUDA paketi indirilmez)..."
# Torch'un PyPI bağımlılıklarını önce kur; ardından CPU tekerleğini yalnızca
# PyTorch indeksinden al. Böylece pip CUDA tekerleğine yönelmez.
"$PY" -m pip install --upgrade pip
"$PY" -m pip install filelock typing-extensions sympy networkx jinja2 fsspec
"$PY" -m pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.0"

echo "PaperQA2 ve diğer bağımlılıklar kuruluyor..."
"$PY" -m pip install \
  "paperqa>=2.0" \
  "sentence-transformers>=2.2" \
  "mcp>=1.0,<2" \
  "PyMuPDF>=1.24" \
  "httpx>=0.27"

echo
check_deps
echo
echo "Not: İlk indeks kurulumunda sentence-transformers modeli indirilir"
echo "(st-multi-qa-MiniLM-L6-cos-v1). İnternet ve disk alanı gerekir."
