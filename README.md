# literature-mcp

Kaynaklı literatür taraması ve kitap bölümü denetimi için iki yerel MCP
sunucusu, şemalar, dokümantasyon ve tek dosyalık HTML üreticileri.

> **Durum:** özel (private) çalışma deposu. Yayına açmadan önce
> [`docs/publishing.md`](docs/publishing.md) kontrol listesini uygulayın.

## Ne çözer?

İki ayrı iş akışını, aynı proje kaydı ve aynı PDF klasörlerini kullanarak
yürütür:

1. **Yeni bölüm için kaynak hattı:** DOI adayları → metadata doğrulama →
   fulltext indirme listesi (HTML) → kullanıcının indirdiği PDF'ler → izole
   yerel indeks → sayfa doğrulamalı taslak.
2. **Mevcut taslağı denetleme:** proje envanteri → iddia–kanıt eşleştirmesi →
   cümle bazlı düzeltme kartları → kaynak denetimi + iddia–kanıt matrisi →
   HTML raporu.

Temel ilke: **LLM çıktısı kanıt değildir.** Kanıt, PDF sayfasından okunan
birebir cümle ve doğrulanmış DOI'dir. `paperqa_ask` yalnızca taslak/özet
üretir; `evidence_check` yalnızca lexical ön taramadır.

## Bileşenler

| Bileşen | Konum | Görev |
|---|---|---|
| `sciencedirect-meta` MCP | [`packages/sciencedirect-meta`](packages/sciencedirect-meta) | 19 araç: metadata/DOI arama, DOI doğrulama, dergi quartile, yerel PDF okuma, kanıt denetimi, rapor dışa aktarma |
| `paperqa-local` MCP | [`packages/paperqa-local`](packages/paperqa-local) | 7 araç: proje kaydı, manifest, PaperQA2 indeksi, semantik arama, sayfa okuma, yerel Qwen taslağı |
| Ortak proje kaydı | `projects.json` (varsayılan: `~/.literature-mcp/projects.json`) | Her projenin PDF klasörü, manifesti ve indeksi; projeler izoledir |
| Fulltext üreticisi | [`scripts/build_fulltext_list.py`](scripts/build_fulltext_list.py) | DOI adaylarını tek dosyalık, yazdırılabilir HTML'e çevirir |
| Şemalar | [`schemas/`](schemas) | Fulltext listesi, düzeltme kartı, iddia–kanıt matrisi |
| Ajan sözleşmesi | [`AGENTS.md`](AGENTS.md) | Bağlayıcı kurallar, araç politikası, kabul kriterleri |
| Araç kataloğu | [`docs/tool-catalog.json`](docs/tool-catalog.json) | 26 aracın makine okunabilir girdi/çıktı şeması |

## Kurulum

Python 3.10+ gerekir.

```bash
git clone <private-repo-url> literature-mcp
cd literature-mcp

python3 -m venv .venv
.venv/bin/pip install -e packages/sciencedirect-meta
```

`paperqa-local` için PaperQA2 ve bağımlılıkları ayrıca kurulmalıdır:

```bash
.venv/bin/pip install "paperqa" mcp pymupdf
```

Yerel `paperqa_ask` kullanılacaksa Ollama ve bir model gerekir:

```bash
ollama pull qwen2.5:1.5b-instruct
```

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
        "command": ["/path/to/literature-mcp/.venv/bin/sciencedirect-meta-mcp"],
        "environment": {
          "LIT_PROJECTS_REGISTRY": "/home/you/.literature-mcp/projects.json",
          "JOURNAL_RANK_CSV": "/path/to/literature-mcp/packages/sciencedirect-meta/data/scimagojr_2024.csv.gz"
        }
      },
      "paperqa-local": {
        "type": "local",
        "command": ["/path/to/literature-mcp/.venv/bin/python", "/path/to/literature-mcp/packages/paperqa-local/paperqa_mcp.py"],
        "environment": {
          "LIT_PROJECTS_REGISTRY": "/home/you/.literature-mcp/projects.json"
        }
      }
    }
  }
}
```

## Hızlı başlangıç

```bash
# 1) Testler
bash scripts/validate_all.sh

# 2) Örnek fulltext listesini üret
python3 scripts/build_fulltext_list.py \
  examples/fulltext-list.example.json \
  -o examples/fulltext-list.example.html

# 3) Araç kataloğunu yenile (iki paket de kuruluysa)
bash scripts/dump_tool_catalog.sh
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
  → 04_denetim_raporu.html + MD + CSV + JSON
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
```

- HTML: insan tarafından okunur, tek dosya, yazdırılabilir.
- Markdown: düzenleme ve sürüm kontrolü.
- CSV/JSON: veri işleme ve ajanlar.
- DOI linkleri yalnızca `https://doi.org/...`; teslimlerde yerel PDF yolu veya
  `file://` linki bulunmaz.

## Gizlilik ve güvenlik

Depoya **konulmaması gerekenler**:

- PDF'ler ve indirilen tam metinler,
- PaperQA2 indeksleri ve embedding önbellekleri,
- kişisel `projects.json`, manifestler ve analiz dosyaları,
- `.venv`, `.env`, API anahtarları, oturum belgeleri,
- SCImago CSV'si (lisans nedeniyle; indirme betiği kullanılır).

Sunucular PDF indirmez, ödeme duvarını veya erişim kontrolünü aşmaz. Tam
metinler kullanıcı hesabından indirilir ve yalnızca yerel olarak işlenir.

## Testler

```bash
bash scripts/validate_all.sh
```

Bu betik JSON şemalarını, Python sözdizimini, fulltext üreticisini ve
`sciencedirect-meta` birim testlerini çalıştırır. Ayrıntılı test:

```bash
PYTHONPATH=packages/sciencedirect-meta/src \
  .venv/bin/python -m unittest discover -s packages/sciencedirect-meta/tests -v
```

## Dokümantasyon

- [`AGENTS.md`](AGENTS.md) — ajanlar için bağlayıcı kurallar
- [`docs/architecture.md`](docs/architecture.md) — bileşenler ve veri akışı
- [`docs/workflows.md`](docs/workflows.md) — adım adım iş akışları
- [`docs/output-spec.md`](docs/output-spec.md) — dosya adları ve biçimler
- [`docs/tool-catalog.md`](docs/tool-catalog.md) — 26 aracın özeti
- [`docs/publishing.md`](docs/publishing.md) — public repoya geçiş kontrolü

## Lisans

MIT. Ayrıntılar: [`LICENSE`](LICENSE).
