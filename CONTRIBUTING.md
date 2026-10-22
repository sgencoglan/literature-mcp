# Katkı

## Geliştirme ortamı

```bash
python3 -m venv .venv
.venv/bin/pip install -e packages/sciencedirect-meta
.venv/bin/pip install -e packages/report-kit
.venv/bin/pip install jsonschema
bash scripts/validate_all.sh
```

## İlkeler

- **Kanıt LLM çıktısı değildir.** `paperqa_ask` yalnızca taslak/özet içindir.
- Her alıntı DOI + sayfa ile doğrulanır.
- Public depoya PDF, indeks, kişisel proje kaydı veya yayımlanmamış bölüm
  metni eklenmez.
- HTML teslimlerinde yerel yol, `file://` ve PDF dosya adı linki bulunmaz.
- Yeni rapor özellikleri `chapter-report` kalite kapısından geçmelidir.

## Değişiklik akışı

1. Küçük ve odaklı bir dal açın.
2. Testleri çalıştırın: `bash scripts/validate_all.sh`.
3. Örnek raporu yeniden üretin:
   `.venv/bin/chapter-report build examples/chapter-report.example.json -o examples/chapter-report.example.html --force`.
4. Değişiklik günlüğünü güncelleyin.
5. Pull request açın; CI yeşil olmalıdır.

## Rapor içeriği katkısı

Gerçek bir bölüm metni veya yayımlanmamış veri göndermeyin. Örnek katkılar
sentetik olmalı ve `examples/chapter-report.example.json` şemasına uymalıdır.
