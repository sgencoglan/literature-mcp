#!/usr/bin/env bash
# Bu depodaki JSON, Python, şema ve birim testlerini doğrular.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
cd "$ROOT"

fail=0
note() { printf '\n== %s ==\n' "$1"; }
bad() { printf 'HATA: %s\n' "$1" >&2; fail=1; }

note "JSON sözdizimi"
while IFS= read -r -d '' f; do
  if ! "$PY" -m json.tool "$f" >/dev/null 2>&1; then
    bad "geçersiz JSON: $f"
  fi
done < <(find . \( -path ./.git -o -path ./.venv -o -path '*/__pycache__' \) -prune -o -name '*.json' -print0)

note "Kişisel veri / eski proje izi"
if grep -RIn --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  -E '/home/[s]alih|okul-[r]iskleri|school-[r]isk|Downloads/[m]akaleler' .; then
  bad "depoda kişisel yol veya eski proje adı var"
else
  echo "Temiz."
fi

note "Python sözdizimi"
if ! "$PY" -m compileall -q scripts packages/sciencedirect-meta/src packages/paperqa-local packages/report-kit/src; then
  bad "Python derleme hatası"
fi

note "JSON şemaları"
if "$PY" -c 'import jsonschema' 2>/dev/null; then
  "$PY" - <<'PY' || fail=1
import json
from pathlib import Path

from jsonschema import Draft202012Validator

root = Path(".")
pairs = [
    ("schemas/fulltext-list.schema.json", "examples/fulltext-list.example.json"),
    ("schemas/change-card.schema.json", "examples/change-card.example.json"),
    ("schemas/claim-evidence.schema.json", "examples/claim-evidence.example.json"),
    ("schemas/chapter-report.schema.json", "examples/chapter-report.example.json"),
]
failed = False
for schema_path, example_path in pairs:
    schema = json.loads((root / schema_path).read_text(encoding="utf-8"))
    example = json.loads((root / example_path).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(example), key=lambda e: list(e.path))
    if errors:
        failed = True
        for err in errors:
            print(f"{example_path}: {err.message}")
    else:
        print(f"OK: {example_path}")
raise SystemExit(1 if failed else 0)
PY
else
  echo "jsonschema kurulu değil; şema doğrulaması atlandı (pip install jsonschema)."
fi

note "sciencedirect-meta birim testleri"
if ! PYTHONPATH="$ROOT/packages/sciencedirect-meta/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PY" -m unittest discover -s packages/sciencedirect-meta/tests -v; then
  bad "birim testleri başarısız"
fi

note "report-kit birim testleri"
if ! PYTHONPATH="$ROOT/packages/report-kit/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PY" -m unittest discover -s packages/report-kit/tests -v; then
  bad "report-kit testleri başarısız"
fi

note "chapter-report kalite kapısı"
if ! PYTHONPATH="$ROOT/packages/report-kit/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PY" -m report_kit build examples/chapter-report.example.json --check; then
  bad "chapter-report örneği doğrulanamadı"
fi

if ! PYTHONPATH="$ROOT/packages/report-kit/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PY" - <<'PY'
import json
from pathlib import Path
from report_kit.render import render_report

data = json.loads(Path("examples/chapter-report.example.json").read_text(encoding="utf-8"))
expected = Path("examples/chapter-report.example.html").read_text(encoding="utf-8")
actual = render_report(data)
if actual != expected:
    raise SystemExit("examples/chapter-report.example.html güncel değil; yeniden üretin")
print("OK: chapter-report örneği güncel")
PY
then
  bad "chapter-report örnek HTML'i kaynakla uyuşmuyor"
fi

note "Fulltext üreticisi"
if ! "$PY" scripts/build_fulltext_list.py examples/fulltext-list.example.json --check; then
  bad "fulltext örneği doğrulanamadı"
fi

note "Git izleme kontrolü"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  tracked="$(git ls-files)"
  if printf '%s\n' "$tracked" | grep -E '(^|/)(\.venv|indexes|outputs)/|\.(pdf|pdf\.gz)$|(^|/)projects\.json$|analysis_updates\.json$' >/dev/null; then
    bad "git tarafından izlenen PDF/indeks/kişisel veri var"
    printf '%s\n' "$tracked" | grep -E '(^|/)(\.venv|indexes|outputs)/|\.(pdf|pdf\.gz)$|(^|/)projects\.json$|analysis_updates\.json$' >&2
  else
    echo "Temiz."
  fi
fi

if (( fail )); then
  echo
  echo "DOĞRULAMA BAŞARISIZ" >&2
  exit 1
fi

echo
echo "DOĞRULAMA TAMAM"
