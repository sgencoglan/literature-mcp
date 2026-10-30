#!/usr/bin/env bash
# llama.cpp + GGUF modelini sudo gerektirmeden kurar.
#
# Kullanım:
#   bash scripts/setup_llamacpp.sh            # Qwen2.5-3B-Instruct Q4_K_M
#   LLAMA_VERSION=b11954 bash scripts/setup_llamacpp.sh
#
# Kurulum yerleri (depo dışında):
#   ~/.local/share/llama.cpp/llama-<sürüm>/
#   ~/.local/share/llama-models/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_VERSION="${LLAMA_VERSION:-b11954}"
LLAMA_ROOT="${LLAMA_ROOT:-$HOME/.local/share/llama.cpp}"
MODEL_ROOT="${MODEL_ROOT:-$HOME/.local/share/llama-models}"
MODEL_CHOICE="${1:-qwen}"

case "$(uname -m)" in
  x86_64|amd64) LLAMA_ARCH="x64" ;;
  aarch64|arm64) LLAMA_ARCH="arm64" ;;
  *) echo "Desteklenmeyen mimari: $(uname -m)" >&2; exit 1 ;;
esac

case "$MODEL_CHOICE" in
  qwen|qwen2.5|qwen2.5-3b)
    MODEL_FILE="qwen2.5-3b-instruct-q4_k_m.gguf"
    MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
    MODEL_ALIAS="qwen2.5-3b-instruct"
    ;;
  *)
    echo "Bilinmeyen model: $MODEL_CHOICE (desteklenen: qwen)" >&2
    exit 1
    ;;
esac

LLAMA_DIR="$LLAMA_ROOT/llama-$LLAMA_VERSION"
TARBALL="llama-$LLAMA_VERSION-bin-ubuntu-$LLAMA_ARCH.tar.gz"
DOWNLOAD_DIR="${TMPDIR:-/tmp}/opencode-llamacpp"
mkdir -p "$DOWNLOAD_DIR" "$LLAMA_ROOT" "$MODEL_ROOT"

if [[ ! -x "$LLAMA_DIR/llama-server" ]]; then
  echo "[1/3] llama.cpp $LLAMA_VERSION indiriliyor..."
  curl -L --fail --retry 3 \
    -o "$DOWNLOAD_DIR/$TARBALL" \
    "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_VERSION/$TARBALL"
  mkdir -p "$LLAMA_DIR"
  tar -xzf "$DOWNLOAD_DIR/$TARBALL" -C "$LLAMA_DIR" --strip-components=1
else
  echo "[1/3] llama.cpp zaten kurulu: $LLAMA_DIR"
fi

# Debian/Ubuntu minimal kurulumlarında libgomp.so.1 bulunmayabilir. sudo
# kullanmadan .deb paketini açıp yerel lib klasörüne koy.
if ! ldconfig -p 2>/dev/null | grep -q 'libgomp.so.1'; then
  if [[ ! -f "$LLAMA_DIR/lib/libgomp.so.1" ]]; then
    echo "[2/3] libgomp1 yerel olarak çıkarılıyor..."
    (
      cd "$DOWNLOAD_DIR"
      apt-get download libgomp1 >/dev/null 2>&1
      DEB="$(ls -1t libgomp1_*.deb | head -1)"
      rm -rf libgomp-extract
      dpkg-deb -x "$DEB" libgomp-extract
      mkdir -p "$LLAMA_DIR/lib"
      cp -a libgomp-extract/usr/lib/*/libgomp.so.1* "$LLAMA_DIR/lib/"
    )
  fi
else
  echo "[2/3] Sistem libgomp.so.1 bulundu."
fi

if [[ ! -s "$MODEL_ROOT/$MODEL_FILE" ]]; then
  echo "[3/3] Model indiriliyor: $MODEL_FILE (~2 GB, bağlantıya göre sürebilir)"
  curl -L --fail --retry 3 -o "$MODEL_ROOT/$MODEL_FILE.part" "$MODEL_URL"
  mv "$MODEL_ROOT/$MODEL_FILE.part" "$MODEL_ROOT/$MODEL_FILE"
else
  echo "[3/3] Model zaten indirilmiş: $MODEL_ROOT/$MODEL_FILE"
fi

cat <<EOF

Kurulum tamam.

  llama.cpp : $LLAMA_DIR
  model     : $MODEL_ROOT/$MODEL_FILE
  alias     : $MODEL_ALIAS

Sunucuyu başlatın:

  bash $ROOT/scripts/start_llamacpp.sh $MODEL_CHOICE

Ardından paperqa-local hazırdır (varsayılanlar llama.cpp'ye ayarlıdır):

  export PAPERQA_LOCAL_LLM=$MODEL_ALIAS
  export PAPERQA_LOCAL_API_BASE=http://127.0.0.1:8080/v1

OpenCode tarafında config/opencode.example.json içindeki
providers.llamacpp bölümünü kendi ~/.config/opencode/opencode.json
dosyanıza ekleyin.
EOF
