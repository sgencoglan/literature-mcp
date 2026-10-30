#!/usr/bin/env bash
# llama.cpp sunucusunu bu makine sınıfı için güvenli bayraklarla başlatır.
#
# Kullanım:
#   bash scripts/start_llamacpp.sh              # Qwen2.5-3B
#   THREADS=2 CTX=4096 bash scripts/start_llamacpp.sh
#
# Ek llama-server bayrakları komut satırına eklenebilir:
#   bash scripts/start_llamacpp.sh qwen --verbose
set -euo pipefail

LLAMA_VERSION="${LLAMA_VERSION:-b11954}"
LLAMA_DIR="${LLAMA_DIR:-$HOME/.local/share/llama.cpp/llama-$LLAMA_VERSION}"
MODEL_ROOT="${MODEL_ROOT:-$HOME/.local/share/llama-models}"
MODEL_CHOICE="${1:-qwen}"
shift || true

case "$MODEL_CHOICE" in
  qwen|qwen2.5|qwen2.5-3b)
    MODEL_FILE="qwen2.5-3b-instruct-q4_k_m.gguf"
    MODEL_ALIAS="qwen2.5-3b-instruct"
    ;;
  *)
    echo "Bilinmeyen model: $MODEL_CHOICE (desteklenen: qwen)" >&2
    exit 1
    ;;
esac

MODEL_PATH="${MODEL_PATH:-$MODEL_ROOT/$MODEL_FILE}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"
CTX="${CTX:-8192}"
THREADS="${THREADS:-2}"
NGL="${NGL:-0}"
TEMP="${TEMP:-0.1}"

if [[ ! -x "$LLAMA_DIR/llama-server" ]]; then
  echo "llama-server bulunamadı: $LLAMA_DIR/llama-server" >&2
  echo "Önce: bash scripts/setup_llamacpp.sh $MODEL_CHOICE" >&2
  exit 1
fi
if [[ ! -s "$MODEL_PATH" ]]; then
  echo "Model bulunamadı: $MODEL_PATH" >&2
  echo "Önce: bash scripts/setup_llamacpp.sh $MODEL_CHOICE" >&2
  exit 1
fi

export LD_LIBRARY_PATH="$LLAMA_DIR/lib:${LD_LIBRARY_PATH:-}"
exec "$LLAMA_DIR/llama-server" \
  -m "$MODEL_PATH" \
  --alias "$MODEL_ALIAS" \
  -c "$CTX" \
  -t "$THREADS" \
  -ngl "$NGL" \
  --temp "$TEMP" \
  --host "$HOST" \
  --port "$PORT" \
  --jinja \
  "$@"
