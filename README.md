# literature-mcp

[![validate](https://github.com/sgencoglan/literature-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sgencoglan/literature-mcp/actions/workflows/ci.yml)

Kaynaklı literatür taraması, kanıta dayalı bölüm taslağı ve mevcut taslak denetimi için iki yerel MCP sunucusu, şemalar ve HTML üreticileri.

> **Sürüm:** v2.4.0. Son public sürüm v2.3.0. Depoda PDF, indeks,
> kişisel proje kaydı veya yayımlanmamış bölüm metni tutulmaz.

## Ne çözer?

Kullanıcı önce proje klasörünün yolunu verir. `paperqa_create_workspace` bu
klasörde üç iş akışı klasörünü açar; ardından MCP hangi akışın yapılacağını
sorar. Yalnızca seçimden sonra ilgili arama veya dosya işleme başlar. PDF,
manifest ve indeks proje kökünde kalır.

Başlangıç sırası: proje kökünü al → `paperqa_create_workspace` ile üç klasörü
aç → kullanıcıya “1 Kaynak keşfi, 2 PDF’lerden bölüm taslağı, 3 Mevcut
taslağı denetleme” seçeneklerini sor → seçilen akışın girdilerini işle.

1. **Kaynak keşfi ve PDF listesi:** Literatür taraması → DOI ve yayıncı
   doğrulama → `01_kaynak_kesfi/` içine fulltext indirme listesi (HTML).
2. **PDF'lerden kanıta dayalı taslak:** Kullanıcı PDF'leri
   `02_bolum_taslagi/fulltext/` içine koyar → MCP bunları kaydeder ve izole indeksler
   → bulguları paragraf bağlamına uygun özgün
   Türkçe cümlelerle aktaran, sayfa doğrulamalı `02_bolum_taslagi.md` ve
   yazdırılabilir `02_bolum_taslagi/taslak/02_bolum_taslagi.html`.
3. **Mevcut taslağı denetleme:** kullanıcının `03_taslak_denetimi/taslak/` içine
   koyduğu taslak ve `03_taslak_denetimi/fulltext/` içindeki tam metin PDF'leri →
   iddia–kanıt eşleştirmesi →
   cümle bazlı düzeltme kartları → kaynak denetimi + iddia–kanıt matrisi →
   `03_taslak_denetimi/taslak/` içine altın standart HTML raporu.

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

Örnek çıktı: [`examples/chapter-report.example.html`](examples/chapter-report.example.html) ve [`examples/chapter-report.example.md`](examples/chapter-report.example.md).

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
  --markdown 05_bolum_raporu.md \
  --artifact 02_degisiklik_kartlari.json \
  --artifact 03_iddia_kanit_matrisi.csv \
  --cleanup ask
```

| Seçenek | Davranış |
|---|---|
| `keep` | Silmez (varsayılan). |
| `ask` | Onay sorar; terminal yoksa silmez. |
| `intermediate` | HTML ve Markdown dışındaki manifest kayıtlarını siler. |
| `all` | Manifestteki tüm üretilmiş dosyaları siler; manifest kalır. |

PDF, indeks, registry ve manifest dışındaki dosyalara dokunulmaz. `--dry-run`
yalnızca listeler; `--yes` onay sormaz.

## Bileşenler

| Bileşen | Konum | Görev |
|---|---|---|
| `sciencedirect-meta` MCP | [`packages/sciencedirect-meta`](packages/sciencedirect-meta) | 19 araç: metadata/DOI arama, DOI doğrulama, dergi quartile, yerel PDF okuma, kanıt denetimi, rapor dışa aktarma |
| `paperqa-local` MCP | [`packages/paperqa-local`](packages/paperqa-local) | 9 araç: proje klasörlerini başlatma, kayıt, manifest, PaperQA2 indeksi, semantik arama, sayfa okuma, LLM durumu, yerel taslak |
| `report-kit` | [`packages/report-kit`](packages/report-kit) | Altın standart HTML raporu, kalite kapısı ve manifest tabanlı temizlik |
| Ortak proje kaydı | `projects.json` (varsayılan: `~/.literature-mcp/projects.json`) | Her projenin PDF klasörü, manifesti ve indeksi; projeler izoledir |
| Fulltext üreticisi | [`scripts/build_fulltext_list.py`](scripts/build_fulltext_list.py) | DOI adaylarını tek dosyalık, yazdırılabilir HTML'e çevirir |
| Şemalar | [`schemas/`](schemas) | Fulltext listesi, düzeltme kartı, iddia–kanıt matrisi, bölüm raporu |
| Ajan sözleşmesi | [`AGENTS.md`](AGENTS.md) | Bağlayıcı kurallar, araç politikası, kabul kriterleri |
| Araç kataloğu | [`docs/tool-catalog.json`](docs/tool-catalog.json) | 28 aracın makine okunabilir girdi/çıktı şeması |

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

Yerel `paperqa_ask` için tek desteklenen arka uç **llama.cpp**'dir. Bu makine sınıfı
için güvenli üst sınır **3B/4B quantized** modeldir; 7B model 8 GB RAM'li,
GPU'suz bir sistemde swap'a düşer. Ayrıntılı kurulum:
[`docs/local-llm.md`](docs/local-llm.md).

```bash
# llama.cpp + Qwen2.5-3B-Instruct Q4_K_M (sudo gerekmez)
bash scripts/setup_llamacpp.sh

# paperqa-local varsayılan olarak llama.cpp'yi kullanır
export PAPERQA_LOCAL_LLM=qwen2.5-3b-instruct
export PAPERQA_LOCAL_API_BASE=http://127.0.0.1:8080/v1
```

Sunucuyu elle başlatmak gerekmez: `paperqa_ask` çağrıldığında MCP llama.cpp'yi
otomatik başlatır ve yalnızca kendi başlattığı sunucuyu
`PAPERQA_AUTO_STOP_IDLE` (varsayılan 300 sn) sonra durdurur. Elle başlatmak
isterseniz `bash scripts/start_llamacpp.sh qwen` kullanın; MCP bu sunucuya
dokunmaz.

Yerel model yalnızca taslak/özet içindir; nihai raporun kanıtı
`paperqa_search` + `paperqa_read_pages` ile sayfa düzeyinde doğrulanır.
Taslakta kaynak cümleleri kopyalanmaz; bulgular bağlama uygun biçimde yeniden
ifade edilir. `paperqa_ask` bu yazım biçimini garanti etmez.

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
          "LIT_PROJECTS_REGISTRY": "<home>/.literature-mcp/projects.json",
          "PAPERQA_LOCAL_LLM": "qwen2.5-3b-instruct",
          "PAPERQA_LOCAL_API_BASE": "http://127.0.0.1:8080/v1"
        }
      }
    }
  }
}
```

Örnek dosyada ayrıca OpenCode `/models` altında görünen `providers.llamacpp`
bölümü vardır. `<repo>` ve `<home>` alanlarını kendi mutlak yollarınızla
değiştirin; bu dosyayı public depoya commit etmeyin.

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

## İş akışı 1 — Kaynak keşfi ve PDF listesi

Başlamadan önce kullanıcıdan proje klasörünün yolunu alın. Bu klasör yoksa
kullanıcının verdiği tam yolda oluşturun; mevcut çalışma dizinini veya rastgele
geçici bir klasörü çıktı konumu olarak seçmeyin.

Ardından `paperqa_create_workspace(project_directory)` çağrısıyla proje
kökünde `01_kaynak_kesfi/`, `02_bolum_taslagi/` ve `03_taslak_denetimi/`
klasörlerini oluşturun. Proje adı klasör adından alınır; istenirse `name`
parametresiyle açıkça verilebilir. Ardından kullanıcıya 1, 2 veya 3. iş
akışını seçmesini sorun; seçimden önce kaynak araması ya da PDF işleme yapmayın.

```text
<proje-kökü>/
├── 01_kaynak_kesfi/       # İş akışı 1
├── 02_bolum_taslagi/      # PDF'ler fulltext/, çıktılar taslak/ altında
├── 03_taslak_denetimi/    # Taslak taslak/, PDF'ler fulltext/ altında
└── .literature-mcp/       # Manifest ve yerel indeks
```

```text
Konu/kapsam
  → deep_research / search_literature
  → search_all / search_sciencedirect / search_pubmed / search_europepmc
  → get_article / get_links
  → verify_doi_and_publisher + doi_provenance + journal_rank
  → aday JSON (schemas/fulltext-list.schema.json)
  → scripts/build_fulltext_list.py
  → <proje-kökü>/01_kaynak_kesfi/01_fulltext_listesi.html
```

## İş akışı 2 — PDF'lerden kanıta dayalı taslak

PDF'leri `<proje-klasörü>/02_bolum_taslagi/fulltext/` içine koyun; taslak
çıktıları `02_bolum_taslagi/taslak/` altında tutulur. Aynı
`chapter-report` şablonu taslak HTML'inde bölüm metnini, Ek 1 kaynak–taslak
eşleştirmelerini ve Ek 2 iddia–kanıt matrisini verir.

```text
Kullanıcı PDF'leri `<proje-kökü>/02_bolum_taslagi/fulltext/` klasörüne indirir
  → paperqa_register_project
  → project_audit
  → paperqa_build_index
  → paperqa_status + library_status
  → paperqa_search / paperqa_read_pages / read_paper
  → <proje-kökü>/02_bolum_taslagi/taslak/02_bolum_taslagi.json
  → chapter-report build
  → <proje-kökü>/02_bolum_taslagi/taslak/02_bolum_taslagi.html + .md
```

## İş akışı 3 — Mevcut taslağı denetleme

Denetlenen taslak ve rapor çıktıları
`<proje-kökü>/03_taslak_denetimi/taslak/` içinde tutulur. Kullanıcı
denetlenecek taslağı da bu alt klasöre koyar. Ana rapor
`05_bolum_raporu.html` dosyasıdır.

```text
Kullanıcı taslağı 03_taslak_denetimi/taslak/ içine, PDF'leri
03_taslak_denetimi/fulltext/ içine koyar
  → ayrı PaperQA proje kaydı (workflow_project_names.audit)
  → project_audit / paperqa_status / library_status
  → taslağı cümlelere/iddialara ayır
  → her iddia için paperqa_search + paperqa_read_pages
  → verify_doi_and_publisher + doi_provenance + journal_rank
  → düzeltme kartları (schemas/change-card.schema.json)
  → Ek 2 kaynak denetimi
  → iddia–kanıt matrisi (schemas/claim-evidence.schema.json)
  → chapter-report build → <proje-kökü>/03_taslak_denetimi/taslak/05_bolum_raporu.html
  → istenirse --cleanup intermediate/all
```

## Çıktılar

Ana ve ek çıktılar ilgili iş akışı klasöründedir. Manifest ve indeks proje
kökündeki `.literature-mcp/` klasörüne yazılır:

```text
01_kaynak_kesfi/01_fulltext_listesi.html
01_kaynak_kesfi/01_fulltext_listesi.json
02_bolum_taslagi/taslak/02_bolum_taslagi.json
02_bolum_taslagi/taslak/02_bolum_taslagi.html
02_bolum_taslagi/taslak/02_bolum_taslagi.md
03_taslak_denetimi/taslak/02_degisiklik_kartlari.csv
03_taslak_denetimi/taslak/02_degisiklik_kartlari.json
03_taslak_denetimi/taslak/03_kaynak_denetimi.csv
03_taslak_denetimi/taslak/03_iddia_kanit_matrisi.csv
03_taslak_denetimi/taslak/04_denetim_raporu.html
03_taslak_denetimi/taslak/04_denetim_raporu.md
03_taslak_denetimi/taslak/05_bolum_raporu.html
03_taslak_denetimi/taslak/05_bolum_raporu.md
03_taslak_denetimi/taslak/05_bolum_raporu.manifest.json
```

- HTML: insan tarafından okunur, tek dosya, yazdırılabilir.
- Markdown: düzenleme ve sürüm kontrolü; HTML ile aynı veriden üretilir.
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
- [`docs/local-llm.md`](docs/local-llm.md) — llama.cpp kurulumu, model ve donanım sınırı
- [`docs/tool-catalog.md`](docs/tool-catalog.md) — 28 aracın özeti
- [`docs/publishing.md`](docs/publishing.md) — public repo kontrolü

## Lisans

MIT. Ayrıntılar: [`LICENSE`](LICENSE).
