# literature-mcp

[![validate](https://github.com/sgencoglan/literature-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sgencoglan/literature-mcp/actions/workflows/ci.yml)

Kaynaklı literatür taraması ve kitap bölümü denetimi için iki yerel MCP
sunucusu, şemalar, dokümantasyon ve tek dosyalık HTML üreticileri.

> **Durum:** public v2.0.0. Depoda PDF, indeks, kişisel proje kaydı veya
> yayımlanmamış bölüm metni tutulmaz.

## Ne çözer?

İki ayrı iş akışını, aynı proje kaydı ve aynı PDF klasörlerini kullanarak
yürütür:

1. **Yeni bölüm için kaynak hattı:** DOI adayları → metadata doğrulama →
   fulltext indirme listesi (HTML) → kullanıcının indirdiği PDF'ler → izole
   yerel indeks → sayfa doğrulamalı taslak.
2. **Mevcut taslağı denetleme:** proje envanteri → iddia–kanıt eşleştirmesi →
   cümle bazlı düzeltme kartları → kaynak denetimi + iddia–kanıt matrisi →
   altın standart HTML raporu.

Temel ilke: **LLM çıktısı kanıt değildir.** Kanıt, PDF sayfasından okunan
birebir cümle ve doğrulanmış DOI'dir. `paperqa_ask` yalnızca taslak/özet
üretir; `evidence_check` yalnızca lexical ön taramadır.

## Altın standart bölüm raporu

`chapter-report`, beğenilen b1 raporunun tasarımını ve kanıt disiplinini
yeniden üretilebilir hâle getirir:

- düzeltilmiş bölüm metni; yalnızca değişen cümlelerde kırmızı zemin,
- **Ek 1:** yazar cümlesi → kaynak cümlesi (İngilizce) → Türkçe çeviri →
  yeniden yazılan cümle → “ne değişti / neden” notu,
- **Ek 2:** DOI ve Q bilgili kaynak envanteri, sayfa doğrulamalı iddia–kanıt
  matrisi, düzeltme özeti ve sınırlılıklar,
- tek dosya, gömülü CSS, yazdırma desteği, harici JS yok.

Örnek çıktı: [`examples/chapter-report.example.html`](examples/chapter-report.example.html).

```bash
python -m pip install -e packages/report-kit

# Örneği doğrula ve üret
chapter-report build examples/chapter-report.example.json \
  -o examples/chapter-report.example.html --force
```

Kalite kapısı; DOI, sayfa, birebir alıntı, Türkçe çeviri, atıf ve yerel yol
yasağını denetler. `--strict` uyarıları da hata sayar. Ayrıntılar:
[`docs/report-standard.md`](docs/report-standard.md).

### Üretilen dosyaları temizleme

`chapter-report build` bir manifest yazar. Analiz bittikten sonra yalnızca bu
manifestte listelenen üretilmiş dosyalar silinebilir:

```bash
chapter-report build rapor.json -o 05_bolum_raporu.html \
  --artifact 02_degisiklik_kartlari.json \
  --artifact 03_iddia_kanit_matrisi.csv \
  --cleanup ask
```

| Seçenek | Davranış |
|---|---|
| `keep` | Silmez (varsayılan). |
| `ask` | Onay sorar; terminal yoksa silmez. |
| `intermediate` | HTML dışındaki manifest kayıtlarını siler. |
| `all` | Manifestteki tüm üretilmiş dosyaları siler; manifest kalır. |

PDF, indeks, registry ve manifest dışındaki dosyalara dokunulmaz. `--dry-run`
yalnızca listeler; `--yes` onay sormaz.

## Bileşenler

| Bileşen | Konum | Görev |
|---|---|---|
| `sciencedirect-meta` MCP | [`packages/sciencedirect-meta`](packages/sciencedirect-meta) | 19 araç: metadata/DOI arama, DOI doğrulama, dergi quartile, yerel PDF okuma, kanıt denetimi, rapor dışa aktarma |
| `paperqa-local` MCP | [`packages/paperqa-local`](packages/paperqa-local) | 7 araç: proje kaydı, manifest, PaperQA2 indeksi, semantik arama, sayfa okuma, yerel Qwen taslağı |
| `report-kit` | [`packages/report-kit`](packages/report-kit) | Altın standart HTML raporu, kalite kapısı ve manifest tabanlı temizlik |
| Ortak proje kaydı | `projects.json` (varsayılan: `~/.literature-mcp/projects.json`) | Her projenin PDF klasörü, manifesti ve indeksi; projeler izoledir |
| Fulltext üreticisi | [`scripts/build_fulltext_list.py`](scripts/build_fulltext_list.py) | DOI adaylarını tek dosyalık, yazdırılabilir HTML'e çevirir |
| Şemalar | [`schemas/`](schemas) | Fulltext listesi, düzeltme kartı, iddia–kanıt matrisi, bölüm raporu |
| Ajan sözleşmesi | [`AGENTS.md`](AGENTS.md) | Bağlayıcı kurallar, araç politikası, kabul kriterleri |
| Araç kataloğu | [`docs/tool-catalog.json`](docs/tool-catalog.json) | 26 aracın makine okunabilir girdi/çıktı şeması |

## Kurulum

Python 3.10+ gerekir.

```bash
git clone https://github.com/sgencoglan/literature-mcp.git
cd literature-mcp

python3 -m venv .venv
.venv/bin/pip install -e packages/sciencedirect-meta
.venv/bin/pip install -e packages/report-kit
```

`paperqa-local` için PaperQA2 ve bağımlılıkları ayrıca kurulmalıdır:

```bash
.venv/bin/pip install "paperqa" mcp pymupdf
```

Yerel `paperqa_ask` kullanılacaksa Ollama ve bir model gerekir. Bu makine
sınıfı için güvenli üst sınır **3B/4B quantized** modeldir; 7B model 8 GB
RAM'li, GPU'suz bir sistemde swap'a düşer. Ayrıntılı öneri:
[`docs/ollama.md`](docs/ollama.md).

```bash
ollama pull qwen2.5:3b-instruct
```

Yerel model yalnızca taslak/özet içindir; nihai raporun kanıtı
`paperqa_search` + `paperqa_read_pages` ile sayfa düzeyinde doğrulanır.

### Veri dosyaları

SCImago 2024 CSV'si telif/lisans nedeniyle depoda tutulmaz. Bir kez indirin:

```bash
bash scripts/fetch_scimago.sh
```

Proje kaydını örnekten oluşturun:

```bash
mkdir -p ~/.literature-mcp
cp examples/projects.example.json ~/.literature-mcp/projects.json
```

Ardından `projects.json` içindeki yolları kendi PDF klasörlerinize göre
düzenleyin.

## MCP yapılandırması

İki sunucu aynı `projects.json` dosyasını okur. Örnek yapılandırma:
[`config/opencode.example.json`](config/opencode.example.json).

```json
{
  "mcp": {
    "servers": {
      "sciencedirect-meta": {
        "type": "local",
        "command": ["<repo>/.venv/bin/sciencedirect-meta-mcp"],
        "environment": {
          "LIT_PROJECTS_REGISTRY": "<home>/.literature-mcp/projects.json",
          "JOURNAL_RANK_CSV": "<repo>/packages/sciencedirect-meta/data/scimagojr_2024.csv.gz"
        }
      },
      "paperqa-local": {
        "type": "local",
        "command": ["<repo>/.venv/bin/python", "<repo>/packages/paperqa-local/paperqa_mcp.py"],
        "environment": {
          "LIT_PROJECTS_REGISTRY": "<home>/.literature-mcp/projects.json"
        }
      }
    }
  }
}
```

`<repo>` ve `<home>` alanlarını kendi mutlak yollarınızla değiştirin; bu
dosyayı public depoya commit etmeyin.

## Hızlı başlangıç

```bash
# 1) Testler
bash scripts/validate_all.sh

# 2) Örnek fulltext listesini üret
python3 scripts/build_fulltext_list.py \
  examples/fulltext-list.example.json \
  -o examples/fulltext-list.example.html

# 3) Altın standart rapor örneğini doğrula
.venv/bin/chapter-report build examples/chapter-report.example.json --check
```

## İş akışı 1 — Yeni bölüm

```text
Konu/kapsam
  → deep_research / search_literature
  → search_all / search_sciencedirect / search_pubmed / search_europepmc
  → get_article / get_links
  → verify_doi_and_publisher + doi_provenance + journal_rank
  → aday JSON (schemas/fulltext-list.schema.json)
  → scripts/build_fulltext_list.py
  → 01_fulltext_listesi.html
  → kullanıcı PDF'leri proje klasörüne indirir
  → paperqa_register_project
  → project_audit
  → paperqa_build_index
  → paperqa_status + library_status
  → paperqa_search / paperqa_read_pages / read_paper
  → bölüm taslağı + kaynakça
```

## İş akışı 2 — Mevcut taslağı denetleme

```text
Proje + taslak
  → project_audit / paperqa_status / library_status
  → taslağı cümlelere/iddialara ayır
  → her iddia için paperqa_search + paperqa_read_pages
  → verify_doi_and_publisher + doi_provenance + journal_rank
  → düzeltme kartları (schemas/change-card.schema.json)
  → Ek 2 kaynak denetimi
  → iddia–kanıt matrisi (schemas/claim-evidence.schema.json)
  → chapter-report build → 05_bolum_raporu.html
  → istenirse --cleanup intermediate/all
```

## Çıktılar

Her projenin `output_directory` klasöründe:

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
05_bolum_raporu.manifest.json
```

- HTML: insan tarafından okunur, tek dosya, yazdırılabilir.
- Markdown: düzenleme ve sürüm kontrolü.
- CSV/JSON: veri işleme ve ajanlar.
- DOI linkleri yalnızca `https://doi.org/...`; teslimlerde yerel PDF yolu veya
  `file://` linki bulunmaz.
- `05_bolum_raporu.html` altın standarttır; `04_denetim_raporu.html` yalnızca
  denetim odaklı ara çıktıdır.

## Gizlilik ve güvenlik

Depoya **konulmaması gerekenler**:

- PDF'ler ve indirilen tam metinler,
- PaperQA2 indeksleri ve embedding önbellekleri,
- kişisel `projects.json`, manifestler ve analiz dosyaları,
- yayımlanmamış bölüm metinleri ve düzeltilmiş HTML çıktıları,
- `.venv`, `.env`, API anahtarları, oturum belgeleri,
- SCImago CSV'si (lisans nedeniyle; indirme betiği kullanılır).

Sunucular PDF indirmez, ödeme duvarını veya erişim kontrolünü aşmaz. Tam
metinler kullanıcı hesabından indirilir ve yalnızca yerel olarak işlenir.

## Testler

```bash
bash scripts/validate_all.sh
```

Bu betik JSON şemalarını, Python sözdizimini, fulltext üreticisini,
`chapter-report` kalite kapısını ve iki paketin birim testlerini çalıştırır.

## Dokümantasyon

- [`AGENTS.md`](AGENTS.md) — ajanlar için bağlayıcı kurallar
- [`docs/architecture.md`](docs/architecture.md) — bileşenler ve veri akışı
- [`docs/workflows.md`](docs/workflows.md) — adım adım iş akışları
- [`docs/output-spec.md`](docs/output-spec.md) — dosya adları ve biçimler
- [`docs/report-standard.md`](docs/report-standard.md) — altın standart ve kalite kapısı
- [`docs/ollama.md`](docs/ollama.md) — yerel model seçimi ve donanım sınırı
- [`docs/tool-catalog.md`](docs/tool-catalog.md) — 26 aracın özeti
- [`docs/publishing.md`](docs/publishing.md) — public repo kontrolü

## Lisans

MIT. Ayrıntılar: [`LICENSE`](LICENSE).
