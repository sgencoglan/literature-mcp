# Örnekler

Bu klasördeki tüm kayıtlar **kurgusaldır**. DOI'ler `10.5555/...` aralığında
yer tutucudur; gerçek yayınlara çözülmez. Amaç, şemaların ve HTML çıktısının
biçimini göstermektir.

| Dosya | Şema |
|---|---|
| `fulltext-list.example.json` | `schemas/fulltext-list.schema.json` |
| `topic-discovery.example.json` | `schemas/topic-discovery.schema.json` |
| `topic-discovery.example.html` | JSON örneğinden üretilen konu/başlık keşfi raporu |
| `study-design.example.json` | `schemas/study-design.schema.json` |
| `study-design.example.html` | Seçilen başlık için örnek yöntem/tasarım raporu |
| `change-card.example.json` | `schemas/change-card.schema.json` |
| `claim-evidence.example.json` | `schemas/claim-evidence.schema.json` |
| `chapter-report.example.json` | `schemas/chapter-report.schema.json` |
| `chapter-report.example.html` / `.md` | Aynı veriden üretilen örnek çıktılar |
| `search-coverage.example.json` | `schemas/search-coverage.schema.json` |
| `search-coverage.example.html` / `.md` | JSON örneğinden üretilen arama kapsam raporları |
| `projects.example.json` | Proje kaydı (şema dışı örnek) |

HTML örneğini yeniden üretmek için (örnekler sabit adlıdır):

```bash
python3 scripts/build_topic_discovery.py \
  examples/topic-discovery.example.json \
  -o examples/topic-discovery.example.html --no-timestamp --force

python3 scripts/build_study_design.py \
  examples/study-design.example.json \
  -o examples/study-design.example.html --no-timestamp --force

python3 scripts/build_fulltext_list.py \
  examples/fulltext-list.example.json \
  -o examples/fulltext-list.example.html --no-timestamp --force

# Arama kapsam örneği (sabit adlı; render doğrudan çağrılır)
python3 - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from build_search_coverage import render, render_markdown
data = json.loads(Path("examples/search-coverage.example.json").read_text(encoding="utf-8"))
Path("examples/search-coverage.example.html").write_text(render(data), encoding="utf-8")
Path("examples/search-coverage.example.md").write_text(render_markdown(data), encoding="utf-8")
PY
```

Altın standart bölüm raporu örneği:

```bash
.venv/bin/chapter-report build examples/chapter-report.example.json \
  -o examples/chapter-report.example.html \
  --markdown examples/chapter-report.example.md \
  --manifest examples/chapter-report.example.manifest.json \
  --no-timestamp --force
```

Üretim çıktıları varsayılan olarak `_YYYYMMDD-HHMMSS` soneki alır; örnek
dosyaları sabit tutmak için yukarıdaki komutlarda `--no-timestamp` kullanılır.
