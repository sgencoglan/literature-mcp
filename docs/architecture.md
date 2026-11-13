# Mimari

Bu belge, literatür hattının bileşenlerini, veri akışını ve sınırlarını tanımlar. İnsanlar için özet: dört iş akışı iki MCP sunucusunu, ortak proje kaydını, rapor üreteçlerini ve dosya tabanlı çıktıları kullanır.

## Python modülleri

`sciencedirect-meta` paketi tek dosyalık bir yığın değil, sorumluluk bazlı
modüllerden oluşur. `local_research.py` yalnızca **cephe (facade)**tir: her
eski adı yeniden dışa aktarır, böylece `local_research.read_paper` gibi
çağrılar değişmez.

```text
packages/sciencedirect-meta/src/sciencedirect_meta/
├── server.py          # HTTP katmanı: polite_get, kimlik, DOI/PII, tek kaynak aramaları
├── pipeline.py        # tüm kaynakları birleştiren tek arama motoru
├── rate_limit.py      # host başına hız limiti tablosu (MCP + betikler ortak)
├── sources.py         # Semantic Scholar, arXiv, ClinicalTrials + kapsam/skor
├── bootstrap.py       # setup.txt keşfi, öncelik ve güvenlik kontrolü
├── unified.py         # iki modülü tek MCP sunucusunda birleştirir
├── local_research.py  # cephe: geriye dönük uyumlu yeniden dışa aktarım
├── _common.py         # ayarlar, sabitler, küçük metin yardımcıları
├── _projects.py       # proje kaydı + kapsam (izolasyon)
├── _crossref.py       # Crossref arama + DOI provenance
├── _journals.py       # SCImago quartile (yerel CSV)
├── _library.py        # PDF tarama/eşleştirme, okuma, denetim
├── _search.py         # search_literature, DOI doğrulama, deep_research
├── _evidence.py       # çalışma karşılaştırma, lexical kanıt, rapor dışa aktarma
└── _mcp_tools.py      # MCP araç şemaları ve yönlendirme
```

Ayarlar (`PAPER_LIBRARY_DIR`, `JOURNAL_RANK_PATH`, `LIT_PROJECTS_REGISTRY` …)
tek yerde, `_common` içinde tutulur. Cephe üzerinden okuma/yazma doğrudan
oraya yönlendirilir; böylece `local_research.PAPER_LIBRARY_DIR = ...` ataması
araçların gerçekten kullandığı değeri değiştirir.

## Bileşenler

```text
┌─────────────────────────────────────────────────────────────────────┐
│                           OpenCode (ajan)                           │
│  README.md / AGENTS.md / docs/ / schemas/                          │
└───────────────┬───────────────────────────────┬─────────────────────┘
                │ MCP                           │ MCP
┌───────────────▼───────────────┐   ┌───────────▼─────────────────────┐
│ sciencedirect-meta (25 araç)  │   │ paperqa-local (10 araç)         │
│ • DOI/metadata arama          │   │ • proje kaydı + manifest        │
│ • DOI doğrulama, provenance   │   │ • PaperQA2 indeksi              │
│ • journal quartile (SCImago)  │   │ • semantik arama (LLM'siz)      │
│ • yerel PDF okuma/denetim     │   │ • sayfa okuma (LLM'siz)         │
│ • rapor dışa aktarma (MD/CSV) │   │ • yerel LLM taslağı + durum     │
└───────────────┬───────────────┘   └───────────┬─────────────────────┘
                │ ortak registry                 │ ortak registry
        ┌───────▼────────────────────────────────▼───────┐
        │    ~/.literature-mcp/projects.json            │
        │  her proje: paper_directory + manifest +        │
        │  index_name/index_directory + output_directory │
        └───────┬───────────────────────────┬────────────┘
                │                           │
      ┌─────────▼─────────┐       ┌─────────▼─────────────┐
      │ PDF klasörleri     │       │ PaperQA2 indeksleri   │
      │ (kullanıcı indirir)│       │ indexes/<proje>       │
      └─────────┬─────────┘       └─────────┬─────────────┘
                │                           │
                └───────────┬───────────────┘
                            │
              ┌─────────────▼─────────────┐
              │ Çıktılar (output_directory)│
              │ HTML / MD / CSV / JSON     │
              └────────────────────────────┘
```

### sciencedirect-meta

- **9 DOI/link aracı:** `search_sciencedirect`, `search_pubmed`, `search_europepmc`, `search_semantic_scholar`, `search_arxiv`, `search_clinicaltrials`, `search_all`, `get_article`, `get_links`.
- **13 araştırma/yerel araç:** `list_projects`, `project_audit`, `search_literature`, `deep_research`, `verify_doi_and_publisher`, `doi_provenance`, `journal_rank`, `read_paper`, `compare_studies`, `evidence_check`, `export_review`, `analysis_updates`, `library_status`.
- Açık metadata kaynaklarını kullanır (OpenAlex, Semantic Scholar, PubMed, Europe PMC, Crossref, arXiv, ClinicalTrials.gov). ScienceDirect sitesine istek atmaz; Elsevier PII linklerini Crossref üzerinden çözer.
- `search_all`, `search_literature` ve `deep_research` cevapları relevance/quality `score`, kaynak bazlı `coverage` ve `evidence_scarcity` alanlarını taşır. Coverage raporu `scripts/build_search_coverage.py` ile `03_kaynak_kesfi/01_arama_kapsam_raporu_*` olarak yazılır.
- Dış kaynak hataları diğer kaynakları etkilemez; her kaynak kendi `sources_status`/`coverage` satırında raporlanır.
- LLM çağırmaz. Tüm çıktılar deterministiktir; ağ erişimi kesildiğinde yerel araçlar (`read_paper`, `journal_rank`, `analysis_updates`, `library_status`, `export_review`) çalışmaya devam eder.
- Dergi quartile verisi yerel `data/scimagojr_2024.csv.gz` dosyasından okunur;
  dosya `scripts/fetch_scimago.sh` ile indirilir.

### paperqa-local

- **10 araç:** `paperqa_create_workspace`, `paperqa_promote_fulltext`, `paperqa_projects`, `paperqa_register_project`, `paperqa_build_index`, `paperqa_status`, `paperqa_search`, `paperqa_read_pages`, `paperqa_llm_status`, `paperqa_ask`.
- `paperqa_search` ve `paperqa_read_pages` LLM çağırmaz; embedding tabanlı arama ve PyMuPDF sayfa çıkarımı yapar.
- `paperqa_ask` yerel llama.cpp sunucusunu kullanır. Varsayılan model Qwen2.5-3B-Instruct Q4_K_M'dir. CPU'da yavaştır ve 3B model bile atıf hatası yapabilir; çıktısı **taslaktır**, kanıt değildir. 7B model bu donanım sınıfında önerilmez.
- `paperqa_ask`, sunucu kapalıysa llama.cpp'yi otomatik başlatır (`PAPERQA_AUTO_START=1`), model hazır olana kadar bekler ve yalnızca kendi başlattığı sunucuyu `PAPERQA_AUTO_STOP_IDLE` saniye sonra durdurur. Elle başlatılan sunucuya dokunmaz; çökme sonrası kalan sunucu pid dosyasından sahiplenilir.
- `paperqa_llm_status` arka ucun erişilebilirliğini, yüklü modelleri ve otomatik yaşam döngüsü durumunu (`auto_start`, `auto_stop_idle_seconds`, `managed`, `managed_pid`) raporlar; sunucuyu başlatmaz.
- `paperqa_create_workspace`, seçilen proje kökünde 01–05 akış klasörlerini açar. `paperqa_register_project` proje kökü olan `output_directory` yolunu zorunlu ister. `export_review(project=...)` ve rapor üretimi bu kökü kullanır.
- İndeks üyeliği manifest ile sabittir. Klasöre sonradan bırakılan PDF, manifeste eklenmedikçe indekse girmez.
- Manifest yolları proje klasörüne göre doğrulanır; mutlak yol, `..` kaçışı ve çift kayıt reddedilir. `paperqa_status` manifest–indeks uyuşmazlıklarını ve `healthy` durumunu raporlar. Aynı veya iç içe indeks yolu kullanan projeler reddedilir.
- `paperqa_build_index(rebuild=True)` eski indeksi `.bak-*` klasörüne taşır; çökme durumunda geri getirir, kısmi başarısızlıkta yedeği korur.

### report-kit

- **1 CLI:** `chapter-report`.
- Düzeltilmiş bölüm metni + Ek 1 + Ek 2 + Ek 4'ü; iş akışı 3'te ayrıca bağlam değerlendirmesi + Ek 3 kaynak önerilerini tek dosyalık HTML'e yazar.
- `scripts/build_topic_discovery.py`, JSON tarama kaydı ve sıralı araştırma önerilerini çevrimdışı HTML'e çevirir.
- Kalite kapısı: DOI/sayfa/alıntı/çeviri zorunluluğu, yerel yol yasağı, HTML dengesi.
  Chapter-report HTML'lerinde DOI kopyalama düğmesi için tek, denetimli gömülü
  betik izinlidir; diğer `<script>`, `<iframe>` ve `on*` öznitelikleri reddedilir.
  Fulltext listesi HTML'inde DOI kopyalama düğmesi yoktur; onun yerine
  tıklanabilir DOI/yayıncı düğmeleri ve düz metin DOI açık adresi bulunur.
- Manifest tabanlı temizlik: yalnızca üretilmiş dosyaları siler; PDF/indeks/registry'ye dokunmaz.
- Tasarım tek CSS dosyasındadır: `packages/report-kit/src/report_kit/templates/chapter-report.css`.
- HTML/Markdown/manifest adları varsayılan olarak `_YYYYMMDD-HHMMSS` zaman
  soneki alır; `--no-timestamp` sabit ad üretir.

### Ortak proje kaydı

`projects.json` her proje için şu alanları taşır:

| Alan | Anlam |
|---|---|
| `title`, `description` | İnsan/ajan için proje bağlamı |
| `paper_directory` | PDF klasörü |
| `include_subdirectories` | Alt klasörler taranacak mı? |
| `manifest` | Manifest CSV yolu |
| `index_directory`, `index_name` | PaperQA2 indeks konumu |
| `output_directory` | Kullanıcının seçtiği proje klasörü; yeni kayıt için zorunlu |
| `analysis_json` | Varsa kayıtlı analiz dosyası; yoksa `null` |

İki MCP sunucusu da aynı registry'yi okur (`LIT_PROJECTS_REGISTRY` ile değiştirilebilir). Böylece `project_audit` ile `paperqa_status` aynı projeyi görür.

## Veri akışı

### Başlangıç ve akış 1 — Konu belirleme

Kullanıcı proje kökünü verir; `paperqa_create_workspace` 01–05 akış klasörlerini
oluşturur. Ajan ardından 1–5 seçimini sorar ve yalnızca seçilen akışı başlatır.
Akış 1 başlık/amaç önerilerini üretir; ürün türü ve hedef kelime sayısı burada
sabitlenir.

```text
Araştırma konusu
   │
   ├─ search_literature
   │      └─ OpenAlex + Semantic Scholar + PubMed + Europe PMC + Crossref
   │         (arXiv ve ClinicalTrials.gov `sources` ile isteğe bağlı)
   │      └─ coverage + score + evidence_scarcity
   ├─ olası boşluklar + başlık/amaç önerileri
   │      └─ 01_konu_belirleme/01_konu_<zaman>.json/.html
   ├─ kullanıcı başlık + tür + hedef kelime seçer
   │      └─ (ampirik makale) yöntem/tasarım
   │             └─ 01_konu_belirleme/01_yontem_tasarimi_<zaman>.json/.html
   └─ kapı: başlık ve tür onaylanmadan akış 2 başlamaz
```

### Akış 2 — Yazım planı

Onaylı tür ve uzunluğa göre alt başlık iskeleti kurulur. Her alt başlık için
amaç, hedef kelime ve gereken kanıt türü yazılır. Bu akış kaynak seçmez;
yalnızca iskeletin gerçekçiliğini doğrulayacak hafif tarama yapar.

```text
Onaylı başlık + tür + hedef kelime
   │
   ├─ alt başlıklar S1…Sn + purpose + target_words
   ├─ evidence_needs (tasarım + min_count)
   ├─ scripts/build_writing_plan.py
   │      └─ 02_yazim_plani/01_yazim_plani_<zaman>.json/.html
   └─ kapı: kullanıcı onayı (plan_status=approved)
```

### Akış 3 — Plana göre kaynak keşfi ve fulltext seçimi

Her alt başlık için hedefli sorgular üretilir; aday havuzu tek yerde toplanır.
Atama matrisi alt başlık → DOI eşlemesini kurar ve karşılanamayan kanıt
ihtiyaçlarını boşluk olarak raporlar. Yalnızca atanmış DOI'lerin PDF'leri
indirilir.

```text
Onaylı plan
   │
   ├─ alt başlık başına 2–4 sorgu → deep_research / search_literature
   │      └─ coverage + score + evidence_scarcity
   ├─ scripts/build_assignment_matrix.py --update-plan
   │      ├─ 03_kaynak_kesfi/00_atama_matrisi_<zaman>.json/.html
   │      └─ plana assigned_dois/status/gap_note geri yazılır
   ├─ boşluk varsa kullanıcıya sor (kapsam daralt / gerekçeli kabul)
   ├─ get_article / get_links + verify_doi_and_publisher / doi_provenance / journal_rank
   ├─ scripts/build_fulltext_list.py
   │      └─ 03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json/.html
   ├─ scripts/build_search_coverage.py --fulltext-list ... --auto-report
   │      └─ 03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>.json/.html/.md
   ├─ scripts/build_fulltext_index.py
   │      └─ 03_kaynak_kesfi/00_kaynak_listeleri_<zaman>.html
   └─ scripts/download_open_access.py (yalnızca atanmış DOI'ler)
          └─ 03_kaynak_kesfi/fulltext/<doi-adi>.pdf
```

### Akış 4 — Taslak yazma

PDF'ler akış 3'ten `04_taslak/fulltext/` altına aktarılır (DOI adına çevrilir),
PaperQA projesi kaydedilir ve indekslenir. Her paragraf sayfa doğrulamalı bir
kaynağa bağlanır.

```text
03_kaynak_kesfi/fulltext/ → scripts/promote_fulltext.py --to 4
   │      └─ 04_taslak/fulltext/<doi-adi>.pdf
   ├─ paperqa_register_project → manifest.csv
   ├─ project_audit → DOI/metadata/atıf denetimi
   ├─ paperqa_build_index → indexes/<proje>
   ├─ paperqa_status + library_status → doğrulama
   ├─ paperqa_search + paperqa_read_pages / read_paper
   └─ chapter-report build
          └─ 04_taslak/04_taslak_<zaman>.json/.md/.html/.manifest.json
```

### Akış 5 — Taslak analizi

İki denetim birlikte çalışır: plan uyumu ve kanıt denetimi. Plan uyumu,
taslağın akış 2 iskeletine ne kadar uyduğunu ölçer; kanıt denetimi her iddiayı
sayfa doğrulamalı kaynağa bağlar.

```text
02_yazim_plani/01_yazim_plani_<zaman>.json + 04_taslak/04_taslak_<zaman>.json
   │
   ├─ scripts/check_plan_compliance.py --strict
   │      └─ 05_analiz/05_plan_uyumu_<zaman>.json/.html
   │         (yazılmayan başlık, kelime sapması, plansız bölüm, kullanılmayan atama)
   │
   ├─ her iddia: paperqa_search + paperqa_read_pages
   ├─ verify_doi_and_publisher / doi_provenance / journal_rank
   ├─ compare_studies / evidence_check (yardımcı)
   ├─ düzeltme kartları (schemas/change-card.schema.json)
   ├─ Ek 2 kaynak denetimi + iddia–kanıt matrisi (schemas/claim-evidence.schema.json)
   ├─ chapter-report kalite kapısı (schemas/chapter-report.schema.json)
   └─ 05_analiz/05_analiz_<zaman>.html/.md/.manifest.json
```

Not: taslak kullanıcıdan geldiyse plan olmayabilir; bu durumda yalnızca kanıt
denetimi çalışır ve plandan söz edilmez.

## Sınırlar ve güvenlik

- **PDF indirilmez.** Ödeme duvarı, erişim kontrolü veya bot koruması aşılmaz. Tam metinler kullanıcı hesabından indirilir.
- **LLM kanıt değildir.** `paperqa_ask` ve `evidence_check` yalnızca yardımcıdır. Nihai her alıntı PDF sayfasıyla doğrulanır.
- **Proje izolasyonu.** Bir projenin indeksi, manifesti veya PDF klasörü başka projeyle paylaşılmaz. `project` parametresi zorunludur.
- **Beş yayıncı platformu.** Ovid LWW, ScienceDirect, SpringerLink, Wiley, Taylor & Francis. Harici bir dizin/atıf veritabanına bağımlılık yoktur.
- **Ağ yoksa.** Yerel araçlar çalışır; ağ gerektiren aramalar açık hata döndürür.
- **Telif hakkı.** Tam metin cümleleri yalnızca denetim amacıyla kısa alıntılar hâlinde kullanılır; uzun bölümler kopyalanmaz.

## Depolama

| Veri | Konum |
|---|---|
| Proje registry | `~/.literature-mcp/projects.json` (`LIT_PROJECTS_REGISTRY` ile değiştirilebilir) |
| Manifestler | `~/.literature-mcp/projects/<ad>/manifest.csv` |
| İndeksler | `~/.literature-mcp/indexes/<index_name>` |
| PDF'ler | `paper_directory` (projeye göre) |
| Raporlar | `output_directory` |
| SCImago verisi | `packages/sciencedirect-meta/data/scimagojr_2024.csv.gz` (indirme betiğiyle) |
| Kayıtlı analiz | Projenin `analysis_json` alanı; tanımsızsa `analysis_updates` hata verir |

## Genişletme notları

- Yeni bir metadata kaynağı eklenirse `search_all`/`search_literature` içindeki birleştirme, `publisher_allowed` mantığı ve `coverage.per_source` sayımı korunmalıdır. Kaynak hataları `sources_status` içinde raporlanır, diğer kaynakları durdurmaz.
- Ranking değişikliği yapılırsa `sources.score_result` ve `docs/output-spec.md` birlikte güncellenir; `coverage` yüksek kalite eşiği aynı yerden okunur.
- Yeni bir proje türü için `projects.json`'a kayıt eklemek yeterlidir; ardından `paperqa_register_project` ve `paperqa_build_index` çalıştırılır.
- Yeni bir çıktı biçimi eklenirse `docs/output-spec.md` ve ilgili JSON şeması güncellenir; ajan sözleşmesi `AGENTS.md` aynı değişikliği yansıtmalıdır.
