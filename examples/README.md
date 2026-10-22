# Örnekler

Bu klasördeki tüm kayıtlar **kurgusaldır**. DOI'ler `10.5555/...` aralığında
yer tutucudur; gerçek yayınlara çözülmez. Amaç, şemaların ve HTML çıktısının
biçimini göstermektir.

| Dosya | Şema |
|---|---|
| `fulltext-list.example.json` | `schemas/fulltext-list.schema.json` |
| `change-card.example.json` | `schemas/change-card.schema.json` |
| `claim-evidence.example.json` | `schemas/claim-evidence.schema.json` |
| `chapter-report.example.json` | `schemas/chapter-report.schema.json` |
| `projects.example.json` | Proje kaydı (şema dışı örnek) |

HTML örneğini yeniden üretmek için:

```bash
python3 scripts/build_fulltext_list.py \
  examples/fulltext-list.example.json \
  -o examples/fulltext-list.example.html
```

Altın standart bölüm raporu örneği:

```bash
.venv/bin/chapter-report build examples/chapter-report.example.json \
  -o examples/chapter-report.example.html --force
```
