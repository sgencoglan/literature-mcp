# Mimari

Bu belge, literatür hattının bileşenlerini, veri akışını ve sınırlarını tanımlar. İnsanlar için özet: üç iş akışı iki MCP sunucusunu, ortak proje kaydını, altın standart rapor üretecini ve dosya tabanlı çıktıları kullanır.

## Bileşenler

```text
┌─────────────────────────────────────────────────────────────────────┐
│                           OpenCode (ajan)                           │
│  README.md / AGENTS.md / docs/ / schemas/                          │
└───────────────┬───────────────────────────────┬─────────────────────┘
                │ MCP                           │ MCP
┌───────────────▼───────────────┐   ┌───────────▼─────────────────────┐
│ sciencedirect-meta (19 araç)  │   │ paperqa-local (9 araç)          │
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

- **6 DOI/link aracı:** `search_sciencedirect`, `search_pubmed`, `search_europepmc`, `search_all`, `get_article`, `get_links`.
- **13 araştırma/yerel araç:** `list_projects`, `project_audit`, `search_literature`, `deep_research`, `verify_doi_and_publisher`, `doi_provenance`, `journal_rank`, `read_paper`, `compare_studies`, `evidence_check`, `export_review`, `analysis_updates`, `library_status`.
- Açık metadata kaynaklarını kullanır (OpenAlex, PubMed, Europe PMC, Crossref). ScienceDirect sitesine istek atmaz; Elsevier PII linklerini Crossref üzerinden çözer.
- LLM çağırmaz. Tüm çıktılar deterministiktir; ağ erişimi kesildiğinde yerel araçlar (`read_paper`, `journal_rank`, `analysis_updates`, `library_status`, `export_review`) çalışmaya devam eder.
- Dergi quartile verisi yerel `data/scimagojr_2024.csv.gz` dosyasından okunur;
  dosya `scripts/fetch_scimago.sh` ile indirilir.

### paperqa-local

- **9 araç:** `paperqa_create_workspace`, `paperqa_projects`, `paperqa_register_project`, `paperqa_build_index`, `paperqa_status`, `paperqa_search`, `paperqa_read_pages`, `paperqa_llm_status`, `paperqa_ask`.
- `paperqa_search` ve `paperqa_read_pages` LLM çağırmaz; embedding tabanlı arama ve PyMuPDF sayfa çıkarımı yapar.
- `paperqa_ask` yerel llama.cpp sunucusunu kullanır. Varsayılan model Qwen2.5-3B-Instruct Q4_K_M'dir. CPU'da yavaştır ve 3B model bile atıf hatası yapabilir; çıktısı **taslaktır**, kanıt değildir. 7B model bu donanım sınıfında önerilmez.
- `paperqa_ask`, sunucu kapalıysa llama.cpp'yi otomatik başlatır (`PAPERQA_AUTO_START=1`), model hazır olana kadar bekler ve yalnızca kendi başlattığı sunucuyu `PAPERQA_AUTO_STOP_IDLE` saniye sonra durdurur. Elle başlatılan sunucuya dokunmaz; çökme sonrası kalan sunucu pid dosyasından sahiplenilir.
- `paperqa_llm_status` arka ucun erişilebilirliğini, yüklü modelleri ve otomatik yaşam döngüsü durumunu (`auto_start`, `auto_stop_idle_seconds`, `managed`, `managed_pid`) raporlar; sunucuyu başlatmaz.
- `paperqa_create_workspace`, seçilen proje kökünde üç akış klasörü açar. `paperqa_register_project` proje kökü olan `output_directory` yolunu zorunlu ister. `export_review(project=...)` ve rapor üretimi bu kökü kullanır.
- İndeks üyeliği manifest ile sabittir. Klasöre sonradan bırakılan PDF, manifeste eklenmedikçe indekse girmez.
- Manifest yolları proje klasörüne göre doğrulanır; mutlak yol, `..` kaçışı ve çift kayıt reddedilir. `paperqa_status` manifest–indeks uyuşmazlıklarını ve `healthy` durumunu raporlar. Aynı veya iç içe indeks yolu kullanan projeler reddedilir.
- `paperqa_build_index(rebuild=True)` eski indeksi `.bak-*` klasörüne taşır; çökme durumunda geri getirir, kısmi başarısızlıkta yedeği korur.

### report-kit

- **1 CLI:** `chapter-report`.
- Düzeltilmiş bölüm metni + Ek 1 + Ek 2'yi tek dosyalık HTML'e yazar.
- Kalite kapısı: DOI/sayfa/alıntı/çeviri zorunluluğu, yerel yol yasağı, HTML dengesi.
- Manifest tabanlı temizlik: yalnızca üretilmiş dosyaları siler; PDF/indeks/registry'ye dokunmaz.
- Tasarım tek CSS dosyasındadır: `packages/report-kit/src/report_kit/templates/chapter-report.css`.

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

### Başlangıç ve iş akışı 1 — Kaynak keşfi ve PDF listesi

Kullanıcı proje kökünü verir; `paperqa_create_workspace` üç akış klasörünü
oluşturur. Ajan ardından 1/2/3 seçimini sorar ve yalnızca seçilen akışı
başlatır. Akış 1 kaynak listesi `01_kaynak_kesfi/` içine yazılır.

```text
Soru/kapsam
   │
   ├─ deep_research / search_literature
   │      └─ OpenAlex + PubMed + Europe PMC + Crossref
   │
   ├─ get_article / get_links
   │      └─ metadata + öncelikli linkler + DOI
   │
   ├─ verify_doi_and_publisher / doi_provenance / journal_rank
   │      └─ DOI gerçek mi, yayıncı kim, Q kaç?
   │
   ├─ aday JSON (schemas/fulltext-list.schema.json)
   │      └─ scripts/build_fulltext_list.py
   │             └─ 01_kaynak_kesfi/01_fulltext_listesi.html (insan)
```

### İş akışı 2 — PDF'lerden kanıta dayalı taslak

Akış 2 PDF'leri `<proje-klasörü>/02_bolum_taslagi/fulltext/` altında, taslak
dosyaları `02_bolum_taslagi/taslak/` altında tutulur. Akış 3 girdileri ise
`03_taslak_denetimi/taslak/` ve `03_taslak_denetimi/fulltext/` altındadır. İki akış ayrı
PaperQA proje adı, manifest ve indeks kullanır. HTML aynı chapter-report şablonunu kullanır
ve Ek 1 ile Ek 2 iddia–kanıt matrisini içerir. Manifest ve indeks proje
kökündeki `.literature-mcp/` altındadır.

```text
Kullanıcı PDF'leri akışın fulltext/ klasörüne koyar → paper_directory
   │
   ├─ paperqa_register_project → manifest.csv
   ├─ project_audit → DOI/metadata/atıf denetimi
   ├─ paperqa_build_index → indexes/<proje>
   ├─ paperqa_status + library_status → doğrulama
   │
   └─ paperqa_search + paperqa_read_pages / read_paper
          └─ bölüm taslağı + kaynakça
                 └─ export_review (MD/CSV/JSON)
```

### İş akışı 3 — Mevcut taslağı denetleme

Raporun ana teslimi `03_taslak_denetimi/taslak/05_bolum_raporu.html` olur.

```text
Kullanıcının taslağı (`03_taslak_denetimi/taslak/`) + PDF'ler
(`03_taslak_denetimi/fulltext/`)
   │
   ├─ project_audit / paperqa_status / library_status
   │      └─ gerçek dosya ve indeks durumu
   │
   ├─ taslağı cümlelere/iddialara ayır
   │
   ├─ her iddia:
   │      ├─ paperqa_search(project, query)
   │      ├─ paperqa_read_pages(project, doi, sayfa)
   │      └─ gerekirse read_paper
   │
   ├─ verify_doi_and_publisher / doi_provenance / journal_rank
   │
   ├─ compare_studies / evidence_check (yardımcı)
   │
   ├─ düzeltme kartları
   │      └─ schemas/change-card.schema.json
   │
   ├─ Ek 2 kaynak denetimi
   ├─ iddia–kanıt matrisi
   │      └─ schemas/claim-evidence.schema.json
   │
   ├─ chapter-report kalite kapısı
   │      └─ schemas/chapter-report.schema.json
   │
   └─ 05_bolum_raporu.html + manifest
```

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

- Yeni bir metadata kaynağı eklenirse `search_all` içindeki birleştirme ve `publisher_allowed` mantığı korunmalıdır.
- Yeni bir proje türü için `projects.json`'a kayıt eklemek yeterlidir; ardından `paperqa_register_project` ve `paperqa_build_index` çalıştırılır.
- Yeni bir çıktı biçimi eklenirse `docs/output-spec.md` ve ilgili JSON şeması güncellenir; ajan sözleşmesi `AGENTS.md` aynı değişikliği yansıtmalıdır.
