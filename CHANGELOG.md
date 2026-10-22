# Değişiklik Günlüğü

## v2.2.0 — 2026-10-22

### Eklendi

- Kalite kapısı, her değişiklik kartındaki DOI'nin kaynak envanterinde
  bulunmasını zorunlu tutar; envanterde olmayan DOI raporu düşürür.
- Bu çapraz kontrol için birim testi eklendi.

### Değişti

- `docs/report-standard.md` ve `packages/report-kit/README.md` yeni DOI
  envanteri kuralına göre güncellendi.

## v2.1.0 — 2026-10-22

### Eklendi

- `chapter-report --markdown`: HTML ile aynı veriden üretilen düzenleme katmanı.
- Markdown çıktısı manifestte `markdown` türüyle izlenir; `--cleanup intermediate`
  HTML ve Markdown'ı korur, yalnızca CSV/JSON ara dosyalarını siler.
- Silinmiş manifest dosyaları temizlikte hata vermek yerine atlanır.

### Değişti

- Örnek rapor `examples/chapter-report.example.md` ile genişletildi.
- README, output-spec, report-standard, workflows ve AGENTS Markdown eşlik
  dosyasına göre güncellendi.

## v2.0.0 — 2026-10-22

### Eklendi

- `packages/report-kit`: altın standart bölüm raporu üreteci (`chapter-report`).
- Tek dosyalık HTML şablonu: düzeltilmiş metin, Ek 1 değişiklik kartları,
  Ek 2 kaynak denetimi ve iddia–kanıt matrisi.
- `schemas/chapter-report.schema.json` ve sentetik
  `examples/chapter-report.example.json` / `.html`.
- Kalite kapısı: DOI, sayfa, birebir alıntı, Türkçe çeviri, atıf, yerel yol
  yasağı ve HTML dengesi denetimi.
- Manifest tabanlı güvenli temizlik: `--cleanup keep|ask|intermediate|all`,
  `--dry-run`, `--yes`, hash doğrulaması ve path traversal koruması.
- `docs/report-standard.md`, `docs/ollama.md`.
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `VERSION`.

### Değişti

- README public v2 kurulumu, altın standart rapor ve temizlik akışıyla
  güncellendi.
- `AGENTS.md`, `docs/output-spec.md`, `docs/workflows.md`,
  `docs/architecture.md` yeni rapora göre güncellendi.
- Yerel model önerisi 1.5B'den 3B'ye yükseltildi; 7B'nin bu donanım sınıfında
  uygun olmadığı belgelendi.

### Korundu

- `sciencedirect-meta` 19 araç, `paperqa-local` 7 araç.
- Proje izolasyonu, DOI/sayfa doğrulaması ve `paperqa_ask` yasağı.
- MIT lisansı ve public depoda PDF/indeks/kişisel veri bulunmaması.
