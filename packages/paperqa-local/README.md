# paperqa-local MCP

Proje bazlı, izole bir PaperQA2 MCP sunucusu. Her proje için ayrı PDF klasörü,
ayrı manifest CSV'si ve ayrı Tantivy indeksi kullanır.

> Bu paket bir kütüphane değil, tek dosyalık bir MCP sunucusudur. PaperQA2 ve
> bağımlılıkları ayrıca kurulmalıdır.

## Araçlar (7)

| Araç | Görev |
|---|---|
| `paperqa_projects` | Kayıtlı projeleri ve durumlarını listeler |
| `paperqa_register_project` | PDF klasörünü proje olarak kaydeder, manifest üretir |
| `paperqa_build_index` | Manifestteki dosyalardan proje indeksini kurar/günceller |
| `paperqa_status` | Proje indeksinin dosya/parça durumunu döndürür |
| `paperqa_search` | Proje içinde semantik arama yapar (LLM çağırmaz) |
| `paperqa_read_pages` | Projedeki PDF'ten DOI + sayfa aralığı okur |
| `paperqa_ask` | Yerel Qwen ile taslak cevap üretir (kanıt değildir) |

`paperqa_search` embedding tabanlıdır; `paperqa_read_pages` PyMuPDF ile sayfa
çıkarır. `paperqa_ask` yalnızca taslak/özet içindir; her cümle PDF sayfasıyla
doğrulanmalıdır.

## Kurulum

```bash
cd packages/paperqa-local
python3 -m pip install "paperqa" mcp pymupdf httpx
```

Python 3.10+ gerekir. Yerel model için Ollama:

```bash
ollama pull qwen2.5:1.5b-instruct
```

Model adı `paperqa_mcp.py` içinde `LOCAL_LLM` olarak tanımlıdır; farklı bir
model kullanacaksanız bu sabiti değiştirin.

## Proje kaydı

Varsayılan kayıt dosyası `~/.literature-mcp/projects.json`. Örnek:

[`../../examples/projects.example.json`](../../examples/projects.example.json)

```json
{
  "schema": 1,
  "projects": {
    "example-project": {
      "title": "Example literature project",
      "paper_directory": "~/Documents/papers/example",
      "include_subdirectories": false,
      "manifest": "~/.literature-mcp/projects/example-project/manifest.csv",
      "index_directory": "~/.literature-mcp/indexes",
      "index_name": "example-project",
      "output_directory": "~/.literature-mcp/outputs/example-project",
      "analysis_json": null
    }
  }
}
```

Yeni proje için tercih edilen yol `paperqa_register_project` aracıdır:

```text
paperqa_register_project(
  name="example-project",
  paper_directory="~/Documents/papers/example",
  title="Example literature project"
)
```

Bu araç manifesti üretir; DOI'si olmayan dosyalar varsayılan olarak manifeste
alınmaz. Ardından `paperqa_build_index(project="example-project")` çalıştırılır.

## Proje izolasyonu

- Her projenin kendi `paper_directory`, `manifest`, `index_directory` ve
  `index_name` değeri vardır.
- İndeks üyeliği **manifest** tarafından belirlenir; klasöre sonradan bırakılan
  bir PDF, manifeste eklenmedikçe indekse girmez.
- `paperqa_search`, `paperqa_read_pages`, `paperqa_build_index` ve
  `paperqa_status` çağrılarında `project` verilmelidir.
- Proje adı bilinmiyorsa önce `paperqa_projects` çağrılır.

## Ortam değişkenleri

| Değişken | Varsayılan | Görev |
|---|---|---|
| `LIT_PROJECTS_REGISTRY` | `~/.literature-mcp/projects.json` | Ortak proje kaydı |
| `PAPERQA_INDEX_ROOT` | `~/.literature-mcp/indexes` | Varsayılan indeks kökü |
| `PAPERQA_PROJECTS_ROOT` | `~/.literature-mcp/projects` | Varsayılan manifest kökü |
| `CROSSREF_MAILTO` | `research@example.org` | Crossref polite-pool iletişimi |

`LIT_PROJECTS_REGISTRY`, `sciencedirect-meta` ile aynı dosyayı göstermelidir;
böylece `project_audit` ve `paperqa_status` aynı projeyi görür.

## MCP yapılandırması

```json
{
  "mcp": {
    "servers": {
      "paperqa-local": {
        "type": "local",
        "command": [
          "/path/to/venv/bin/python",
          "/path/to/literature-mcp/packages/paperqa-local/paperqa_mcp.py"
        ],
        "environment": {
          "LIT_PROJECTS_REGISTRY": "/home/you/.literature-mcp/projects.json",
          "PAPERQA_INDEX_ROOT": "/home/you/.literature-mcp/indexes",
          "PAPERQA_PROJECTS_ROOT": "/home/you/.literature-mcp/projects"
        }
      }
    }
  }
}
```

Tam iki sunuculu örnek:
[`../../config/opencode.example.json`](../../config/opencode.example.json).

## Sınırlar

- PDF indirmez; yalnızca kullanıcının yerel klasöründeki dosyaları okur.
- `paperqa_ask` 1.5B modelle çalışır; atıf ve sayfa hatası yapabilir. Kanıt
  olarak kullanılamaz.
- İndeksleme CPU'da yavaş olabilir; büyük projelerde disk alanı gerekir.
- İndeksler ve PDF'ler depoya commit edilmez.

## Test

```bash
python3 -m py_compile packages/paperqa-local/paperqa_mcp.py
```

Tam test için PaperQA2 kurulu bir ortamda MCP araçlarını çağırın; bu depo
ağır model/indeks dosyalarını CI'ya taşımaz.

## Lisans

MIT. Ayrıntılar: [`../../LICENSE`](../../LICENSE).
