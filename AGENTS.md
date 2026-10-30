# AGENTS.md — Literatür Projesi Ajan Sözleşmesi

Bu dosya, bu projede çalışan yapay zekâ ajanları için **bağlayıcı** kuralları ve araç politikasını tanımlar. İnsanlar için giriş noktası [`README.md`](README.md) dosyasıdır.

## 1. Görev tanımı

İki iş türü vardır. Kullanıcı hangisini istediğini belirtmeden kaynak aramaya başlama.

### Görev 1 — Yeni bölüm için kaynak hattı

1. Konu, kapsam, hedef kaynak sayısı, yıl aralığı, dil kriterleri ve çıktıların yazılacağı proje klasörünü netleştir.
2. `deep_research` veya `search_literature` ile aday DOI'leri topla.
3. Gerekirse `search_all`, `search_sciencedirect`, `search_pubmed`, `search_europepmc` ile genişlet.
4. Her aday için `get_article` ve `get_links` ile metadata ve linkleri al.
5. `verify_doi_and_publisher`, `doi_provenance`, `journal_rank` ile DOI'yi, yayıncıyı ve quartile'ı doğrula.
6. Adayları `schemas/fulltext-list.schema.json` biçiminde JSON'a yaz.
7. `scripts/build_fulltext_list.py` ile `01_fulltext_listesi.html` üret.
8. Kullanıcı PDF'leri proje klasörüne koyduktan sonra:
   `paperqa_register_project` → `project_audit` → `paperqa_build_index` → `paperqa_status` → `library_status`.
9. Taslak için yalnızca `paperqa_search` + `paperqa_read_pages` / `read_paper` kanıtını kullan.
10. Teslimden önce `export_review` ile Markdown/CSV/JSON çıktısını üret.

### Görev 2 — Mevcut taslağı denetleme

1. Proje adı, PDF klasörü ve taslak dosyasını netleştir.
2. `project_audit`, `paperqa_status`, `library_status` ile projenin gerçek durumunu doğrula.
3. Taslağı oku ve her cümleyi/iddiayı ayrı kaydet.
4. Her iddia için:
   - `paperqa_search(project=..., query=...)`
   - Dönen DOI'yi `paperqa_read_pages(project=..., doi=..., page_start=..., page_end=...)` ile doğrula.
   - Gerekirse `read_paper` ile tam metni oku.
5. `verify_doi_and_publisher` ve `doi_provenance` ile DOI'nin gerçekliğini; `journal_rank` ile dergi quartile'ını doğrula.
6. `compare_studies` ve `evidence_check` yalnızca **yardımcı** tarama içindir; nihai kanıt değildir.
7. Her düzeltme için `schemas/change-card.schema.json` uyumlu kart üret.
8. Ek 2 kaynak denetimi ve iddia–kanıt matrisini `schemas/claim-evidence.schema.json` uyumlu üret.
9. `export_review` ile Markdown/CSV/JSON; insan teslimi için `chapter-report build` ile `05_bolum_raporu.html` üret.
10. Kalite kapısı 0 hata verene kadar düzelt; teslimden sonra kullanıcıya `--cleanup intermediate/all` seçeneğini sun.

## 2. Zorunlu kurallar

1. **Proje izolasyonu.** `paperqa_search`, `paperqa_read_pages`, `paperqa_build_index`, `paperqa_status`, `paperqa_ask`, `project_audit`, `read_paper`, `compare_studies`, `evidence_check`, `library_status` çağrılarında `project` ver. Proje adı bilinmiyorsa önce `list_projects` / `paperqa_projects` çağır.
2. **Kanıt hiyerarşisi.** Tam metin cümlesi > abstract. `paperqa_ask` çıktısı taslaktır; kanıt olarak kullanılamaz. `evidence_check` lexical benzerliktir; entailment kanıtı değildir.
3. **Sayfa numarası.** Her alıntı için 1 tabanlı PDF sayfası ver. Sayfa yoksa iddia `not_found` sayılır.
4. **DOI biçimi.** Teslimlerde yalnızca `https://doi.org/<doi>` kullan. Yerel PDF yolu, `file://` linki veya kullanıcı klasör yolu teslim dosyasına yazılmaz.
5. **Uydurma yasağı.** DOI, yazar, yıl, dergi, sayfa, alıntı veya sonuç uydurma. Emin değilsen `not_found`, kısmi kanıt varsa `partially_supported` yaz ve kullanıcıya bildir.
6. **Dil.** Teslim Türkçedir. Kaynak cümlesi İngilizceyse özgün hâliyle ver; Türkçe çevirisini ayrı yaz. Çeviri, alıntının yerine geçmez.
7. **Kırmızı kural.** HTML'de yalnızca **değişen cümle** kırmızı işaretlenir. Paragrafın tamamı, başlık veya kaynak listesi kırmızıya boyanmaz.
8. **Beş platform.** Yalnızca Ovid LWW, ScienceDirect, SpringerLink, Wiley ve Taylor & Francis linkleri önceliklidir. Başka bir dizin sağlayıcısına bağımlılık kurma.
9. **Mevcut projelere dokunma.** Kayıtlı bir projenin PDF klasörü, manifesti, indeksi veya `analysis_json` dosyası, kullanıcı açıkça istemedikçe değiştirilmez. Yeni çalışma için yeni klasör/manifest/indeks kullan.
10. **Çıktı sözleşmesi.** Dosya adları, sütunlar ve biçimler [`docs/output-spec.md`](docs/output-spec.md) dosyasına uyar. JSON çıktıları `schemas/` altındaki şemalara uyumlu olur.
11. **Altın standart.** İnsan teslimi `05_bolum_raporu.html`'dir; `chapter-report` kalite kapısından 0 hatayla geçmeden teslim edilmez. `04_denetim_raporu.html` yalnızca denetim odaklı ara çıktıdır.
12. **Güvenli temizlik.** Üretilmiş dosyalar yalnızca `chapter-report cleanup` ile ve yalnızca `05_bolum_raporu.manifest.json` içinde listelenen dosyalar için silinir. PDF, indeks, registry ve manifest dışı dosyalar silinmez.

## 3. Araç politikası

| Araç | Ne zaman | Ne zaman değil |
|---|---|---|
| `deep_research` | Konuyu facet'lere bölüp geniş DOI taraması | Tek DOI doğrulama |
| `search_literature` | Çok kaynaklı DOI/metadata arama | Tam metin okuma |
| `search_all` / `search_sciencedirect` / `search_pubmed` / `search_europepmc` | Kaynak havuzunu genişletme | Kanıt üretme |
| `get_article` / `get_links` | Tek kayıt metadata/link | Toplu arama |
| `verify_doi_and_publisher` | DOI gerçekliği, yayıncı, PII | Konu araması |
| `doi_provenance` | DOI hangi veritabanlarında var? | Kalite/kanıt kararı |
| `journal_rank` | Dergi Q1–Q4, SJR | Makale kalitesi kanıtı |
| `project_audit` | Proje PDF'leri + DOI/metadata denetimi | Projeler arası karşılaştırma |
| `read_paper` | Tek PDF tam metni / sayfa aralığı | Abstract ile yetinme |
| `compare_studies` | Yöntem/örneklem/bulgu tablosu | Nihai kanıt |
| `evidence_check` | Hızlı lexical ön tarama | Entailment/kanıt |
| `analysis_updates` | Kayıtlı denetim verisini okuma | Yeni analiz üretme |
| `export_review` | Markdown/CSV/JSON rapor | HTML teslim (ayrıca üretilir) |
| `list_projects` / `library_status` | Proje ve PDF envanteri | Arama |
| `paperqa_projects` | Kayıtlı projeler | Arama |
| `paperqa_register_project` | Yeni PDF klasörünü proje yapma | Mevcut projeyi yeniden kaydetme (gerekmedikçe) |
| `paperqa_build_index` | Manifest → indeks | Projeler arası indeks karıştırma |
| `paperqa_status` | İndeks sağlığı | Kanıt |
| `paperqa_search` | Semantik aday cümle/DOI bulma | Nihai alıntı (sayfa doğrulanmalı) |
| `paperqa_read_pages` | Sayfa/quote doğrulama | Tüm PDF'i özetleme |
| `paperqa_ask` | Taslak/özet fikri | Kanıt, alıntı, nihai cümle |

## 4. Görev 1 — kabul kriterleri

- Her adayın DOI'si `verify_doi_and_publisher` ile doğrulanmış olmalı.
- `doi_provenance` en az bir veritabanında kayıt göstermeli.
- `journal_rank` Q1–Q4 veya açık `not_found` döndürmeli.
- Fulltext HTML'de her satırda tıklanabilir DOI ve varsa yayıncı linki bulunmalı.
- HTML tek dosya, yazdırılabilir ve çevrimdışı açılabilir olmalı.
- PDF'ler geldikten sonra `paperqa_status` ile indeksin gerçekten kurulduğu doğrulanmalı.
- Taslakta her paragraf en az bir doğrulanmış kaynağa bağlanmalı; kaynaksız iddia kalmamalı.

## 5. Görev 2 — kabul kriterleri

- Her düzeltme kartında şu alanlar bulunmalı:
  `id`, `location`, `author_sentence`, `source_sentence`, `source_translation`, `source_doi`, `source_page`, `rewritten_sentence`, `note`, `evidence_status`.
- `source_sentence` birebir PDF'ten alınmış olmalı; sayfa numarası verilmeli.
- `source_translation` kaynak cümlesinin Türkçesi olmalı; yorum katılmamalı.
- `rewritten_sentence` yalnızca kanıtın desteklediği kadarını söylemeli; abartıyı kaldırmalı.
- `evidence_status`: `supported`, `partially_supported`, `contradicted`, `not_found`.
- Ek 2 kaynak denetiminde her kaynak için DOI, yayıncı, Q, atıf, erişim ve kullanım kararı bulunmalı.
- İddia–kanıt matrisinde her iddia için kaynak, sayfa, kısa kanıt, destek düzeyi ve karar bulunmalı.
- İddia–kanıt matrisinde konum (`P1 · c2`), kanıt türü ve kısa not sütunları bulunmalı.
- HTML'de düzeltilmiş cümleler kırmızı; kaynak cümlesi ve çevirisi normal renkte olmalı.
- Son teslimde DOI linkleri `https://doi.org/...`; yerel PDF linki yok.
- `05_bolum_raporu.html` `chapter-report` kalite kapısından 0 hatayla geçmeli; Ek 1 ve Ek 2 eksiksiz olmalı.

## 6. Durma ve kullanıcıya sorma koşulları

Aşağıdaki durumlarda tahmin yürütme; kullanıcıya sor:

- Proje adı/klasörü belirsizse veya `projects.json` ile uyuşmuyorsa.
- İndeks `paperqa_status` ile doğrulanamıyorsa.
- Taslak ile PDF'ler arasında ciddi kapsam farkı varsa.
- Bir iddia için tam metin bulunamıyorsa ve abstract yeterli değilse.
- DOI doğrulanamıyorsa veya birden fazla kayıt aynı DOI'yi farklı metadata ile gösteriyorsa.
- Kullanıcı yeni bir konu/kapsam isteyip hedef kaynak sayısını belirtmemişse.
- Eski proje dosyalarında değişiklik yapılması gerekiyorsa.

## 7. Çıktı yolları ve adlandırma

Çıktılar, en başta kullanıcının verdiği proje klasörüne yazılır. Kayıt
sırasında `output_directory` verilmezse `paper_directory` kullanılır;
`chapter-report build -o ...` ve `export_review(project=...)` bu yolu izler.
Proje `output_directory` altında:

```text
01_fulltext_listesi.html
01_fulltext_listesi.json
02_degisiklik_kartlari.csv
02_degisiklik_kartlari.json
03_kaynak_denetimi.csv
03_iddia_kanit_matrisi.csv
04_denetim_raporu.html
04_denetim_raporu.md
05_bolum_raporu.html
05_bolum_raporu.md
05_bolum_raporu.manifest.json
```

Proje adı dosya adına eklenmek istenirse başta verilir: `<proje-adi>_01_fulltext_listesi.html`. Aynı ada sahip eski dosya varsa üzerine yazmadan önce kullanıcıya sor.

## 8. Doğrulama kontrol listesi

Teslimden önce:

- [ ] `paperqa_status` doğru projeyi ve beklenen dosya sayısını gösteriyor.
- [ ] Her DOI `verify_doi_and_publisher` ile doğrulandı.
- [ ] Her alıntı `paperqa_read_pages` ile sayfa numarasıyla teyit edildi.
- [ ] `paperqa_ask` çıktısı hiçbir yerde kanıt olarak kullanılmadı.
- [ ] HTML'de yalnızca değişen cümleler kırmızı.
- [ ] Yerel PDF yolu / `file://` linki yok.
- [ ] DOI linkleri `https://doi.org/...`.
- [ ] CSV UTF-8 (BOM'lu) ve başlık satırı doğru.
- [ ] JSON şemaya uyuyor.
- [ ] `05_bolum_raporu.html` kalite kapısından 0 hatayla geçti.
- [ ] Temizlik yalnızca manifestteki dosyalara uygulandı.
- [ ] Proje izolasyonu ihlal edilmedi; başka proje dosyası okunmadı.
- [ ] Eski proje dosyaları değiştirilmedi.

## 9. Depo durumu ve proje kaydı

- Bu depo **kod ve dokümantasyon** deposudur; PDF, indeks, manifest veya kişisel
  analiz dosyası içermez.
- Depo v2.3.0 sürümüne hazırlanmaktadır; son public sürüm v2.2.0'dır.
  Yayımlanmamış bölüm metni ve gerçek proje çıktıları depoya konmaz.
- Canlı MCP: `sciencedirect-meta` 19 araç, `paperqa-local` 8 araç.
- Kayıtlı projeler kullanıcıya özeldir ve `projects.json` içinde tutulur
  (varsayılan: `~/.literature-mcp/projects.json`). Depoda yalnızca
  `examples/projects.example.json` örneği bulunur.
- Yeni proje açmadan önce `paperqa_register_project` ile kayıt yap; mevcut bir
  projeye sonradan PDF ekleme. Yeni PDF'ler yeni proje veya yeni manifest
  gerektirir.
- `analysis_updates` yalnızca `analysis_json` tanımlı projelerde çalışır;
  tanımsızsa açık hata döndürmesi beklenen davranıştır.

## 10. Hızlı komutlar

```bash
# MCP testleri
PYTHONPATH=packages/sciencedirect-meta/src \
  .venv/bin/python -m unittest discover -s packages/sciencedirect-meta/tests -v

# Tüm doğrulamalar
bash scripts/validate_all.sh

# Fulltext HTML üretimi
python3 scripts/build_fulltext_list.py input.json -o 01_fulltext_listesi.html

# Altın standart rapor: doğrula + üret + temizlik seçeneği
.venv/bin/chapter-report build rapor.json -o 05_bolum_raporu.html --check
.venv/bin/chapter-report build rapor.json -o 05_bolum_raporu.html \
  --markdown 05_bolum_raporu.md
.venv/bin/chapter-report cleanup --manifest 05_bolum_raporu.manifest.json \
  --scope intermediate --dry-run

# Örnek
python3 scripts/build_fulltext_list.py \
  examples/fulltext-list.example.json \
  -o examples/fulltext-list.example.html
```

Araçların tam listesi ve girdi/çıktı şemaları: [`docs/tool-catalog.json`](docs/tool-catalog.json).
