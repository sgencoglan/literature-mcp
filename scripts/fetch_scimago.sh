#!/usr/bin/env bash
# SCImago 2024 CSV'sini yerel veri klasörüne indirir.
# Veri seti telif/lisans nedeniyle depoda tutulmaz.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/packages/sciencedirect-meta/data/scimagojr_2024.csv.gz"
URL="${SCIMAGO_URL:-https://raw.githubusercontent.com/WandLZhang/scimagojr_2024/main/scimagojr_2024.csv.gz}"

mkdir -p "$(dirname "$DEST")"

if [[ -s "$DEST" ]]; then
  echo "Zaten var: $DEST"
  exit 0
fi

echo "İndiriliyor: $URL"
tmp="$(mktemp "$DEST.tmp.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

if ! curl -fL --retry 3 --connect-timeout 20 -o "$tmp" "$URL"; then
  echo "İndirme başarısız. SCIMAGO_URL ile başka bir ayna/URL verin." >&2
  echo "Kaynak: https://www.scimagojr.com/journalrank.php" >&2
  exit 1
fi

gzip -t "$tmp"
mv "$tmp" "$DEST"
echo "Yazıldı: $DEST"
