#!/usr/bin/env bash
# SCImago 2024 CSV'sini yerel veri klasörüne indirir.
# Veri seti telif/lisans nedeniyle depoda tutulmaz.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/packages/sciencedirect-meta/data/scimagojr_2024.csv.gz"
URL="${SCIMAGO_URL:-https://raw.githubusercontent.com/WandLZhang/scimagojr_2024/main/scimagojr_2024.csv}"

mkdir -p "$(dirname "$DEST")"

if [[ -s "$DEST" ]]; then
  echo "Zaten var: $DEST"
  exit 0
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

echo "İndiriliyor: $URL"
raw="$tmpdir/scimago.csv"
if ! curl -fL --retry 3 --connect-timeout 20 -o "$raw" "$URL"; then
  echo "İndirme başarısız. SCIMAGO_URL ile başka bir ayna/URL verin." >&2
  echo "Kaynak: https://www.scimagojr.com/journalrank.php" >&2
  exit 1
fi

if [[ "$URL" == *.gz ]]; then
  gzip -t "$raw"
  cp "$raw" "$tmpdir/scimago.csv.gz"
else
  gzip -c "$raw" > "$tmpdir/scimago.csv.gz"
  gzip -t "$tmpdir/scimago.csv.gz"
fi

mv "$tmpdir/scimago.csv.gz" "$DEST"
echo "Yazıldı: $DEST"
