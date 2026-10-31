# paperqa-local MCP

Proje bazlı, izole bir PaperQA2 MCP sunucusu. Her proje için ayrı PDF klasörü,
ayrı manifest CSV'si ve ayrı Tantivy indeksi kullanır.

> Bu paket bir kütüphane değil, tek dosyalık bir MCP sunucusudur. PaperQA2 ve
> bağımlılıkları ayrıca kurulmalıdır.

## Araçlar (9)

| Araç | Görev |
|---|---|
| `paperqa_create_workspace` | Seçilen proje kökünde 00–03 iş akışı klasörlerini ve 2/3 için ayrı PDF klasörlerini açar; kayıt veya seçim yapmaz |
| `paperqa_projects` | Kayıtlı projeleri ve durumlarını listeler |
| `paperqa_register_project` | PDF klasörünü kaydeder; kullanıcı proje klasörü olan `output_directory` zorunludur |
| `paperqa_build_index` | Manifestteki dosyalardan proje indeksini kurar/günceller; `rebuild` öncesi yedek alır |
| `paperqa_status` | İndeks durumunu ve manifest–indeks uyuşmazlıklarını döndürür |
| `paperqa_search` | Proje içinde semantik arama yapar (LLM çağırmaz) |
| `paperqa_read_pages` | Projedeki PDF'ten DOI + sayfa aralığı okur |
| `paperqa_llm_status` | Yerel LLM arka ucunu ve yüklü modelleri denetler |
| `paperqa_ask` | Yerel LLM ile taslak cevap üretir (kanıt değildir) |

`paperqa_search` embedding tabanlıdır; `paperqa_read_pages` PyMuPDF ile sayfa
çıkarır. Taslakta bulgular paragraf bağlamına uygun özgün cümlelerle aktarılır;
kaynak cümleleri aynen kopyalanmaz. `paperqa_ask` yalnızca taslak/özet içindir
ve bu yazım biçimini garanti etmez; her iddia PDF sayfasıyla doğrulanmalıdır.
`paperqa_llm_status` arka ucun durumunu raporlar; sunucu
kapalıysa `paperqa_ask` llama.cpp'yi otomatik başlatır ve yalnızca kendisi
başlattıysa boşta kalınca durdurur.

## Kurulum

```bash
cd packages/paperqa-local
python3 -m pip install "paperqa" mcp pymupdf httpx
```

Python 3.10+ gerekir.

## Proje klasörünü başlatma

Kullanıcıdan proje kökünün tam yolunu alın ve iş akışlarına başlamadan önce
MCP aracını çağırın:

```text
paperqa_create_workspace(
  project_directory="~/Documents/literature/example-project"
)
```

Proje adı klasör adından alınır; gerekirse `name="example-project"` ile
verilebilir.

Araç `00_konu_basligi_kesfi/`, `01_kaynak_kesfi/`, `02_bolum_taslagi/` ve `03_taslak_denetimi/`
klasörlerini; PDF'ler için `02_bolum_taslagi/fulltext/` ve
`03_taslak_denetimi/fulltext/` klasörlerini oluşturur. Var olan dosyaları silmez
veya taşımaz, PaperQA projesi kaydetmez. Her iş akışında PDF'ler `fulltext/`,
taslak dosyaları ve raporlar `taslak/` altında tutulur. Araçtan sonra kullanıcıya 0, 1, 2 veya
3. iş akışından hangisini yapmak istediğini sorun. Akış 0 konu/başlık/amaç
keşfidir; varsayılan OpenAlex, PubMed, Europe PMC, Crossref taramasını
`00_konu_basligi_kesfi/` içinde raporlar. Kullanıcı önerilen başlıklardan
birini seçtiğinde yöntem/tasarım önerisi de aynı klasöre JSON ve çevrimdışı
HTML olarak eklenir. Akış 2 veya 3 seçilince
yalnızca o akışın PDF klasörünü aracın döndürdüğü ayrı proje adıyla kaydedin.

### llama.cpp (önerilen)

```bash
# Depo kökünden; sudo gerekmez
bash scripts/setup_llamacpp.sh          # Qwen2.5-3B-Instruct Q4_K_M
```

Sunucuyu elle başlatmak gerekmez: `paperqa_ask` çağrıldığında MCP sunucuyu
başlatır, model hazır olana kadar bekler ve son istekten
`PAPERQA_AUTO_STOP_IDLE` saniye sonra durdurur. Elle başlatılan sunucuya
dokunmaz.

```bash
# İsteğe bağlı elle başlatma
bash scripts/start_llamacpp.sh qwen
```

Ardından ortam değişkenleri (varsayılanlar zaten llama.cpp'ye ayarlıdır):

```bash
export PAPERQA_LOCAL_LLM=qwen2.5-3b-instruct
export PAPERQA_LOCAL_API_BASE=http://127.0.0.1:8080/v1
export PAPERQA_AUTO_START=1
export PAPERQA_AUTO_STOP_IDLE=300
```

Ayrıntılar: [`../../docs/local-llm.md`](../../docs/local-llm.md).

7B ve üzeri modeller 8 GB RAM'li, GPU'suz sistemlerde önerilmez.

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
      "output_directory": "~/Documents/papers/example",
      "analysis_json": null
    }
  }
}
```

Yeni proje için tercih edilen yol `paperqa_register_project` aracıdır:

```text
paperqa_register_project(
  name="example-project",
  paper_directory="~/Documents/literature/example-project/pdf",
  output_directory="~/Documents/literature/example-project",
  title="Example literature project"
)
```

`output_directory` zorunludur ve kullanıcının seçtiği proje klasörünü belirtir.
Manifest ve indeks bu klasörün `.literature-mcp/` altına yazılır. Bu araç
manifesti üretir; DOI'si olmayan dosyalar varsayılan olarak manifeste alınmaz. Ardından
`paperqa_build_index(project="example-project")` çalıştırılır.

## Proje izolasyonu

- Her projenin kendi `paper_directory`, `manifest`, `index_directory`,
  `index_name` ve `output_directory` değeri vardır. Yeni proje kaydında
  `output_directory` zorunludur; ana çıktılar burada, manifest ve indeks
  `.literature-mcp/` altında tutulur.
- İndeks üyeliği **manifest** tarafından belirlenir; klasöre sonradan bırakılan
  bir PDF, manifeste eklenmedikçe indekse girmez.
- `paperqa_search`, `paperqa_read_pages`, `paperqa_build_index`,
  `paperqa_status` ve `paperqa_ask` çağrılarında `project` verilmelidir.
- Proje adı bilinmiyorsa önce `paperqa_projects` çağrılır.
- Manifest yolları proje klasörüne göre çözülür; mutlak yol, `..` kaçışı ve
  çift kayıt reddedilir.
- Kayıt sırasında aynı DOI'ye çözülen yinelenen dosyalar manifeste alınmaz;
  `skipped_duplicate_doi` alanında raporlanır.
- `paperqa_build_index(rebuild=True)` eski indeksi silmeden önce `.bak-*`
  klasörüne taşır; kurulum çöker veya bazı dosyalar başarısız olursa eski
  indeks yedekte tutulur (`previous_index_backup`).
- Proje yeniden kaydedilince veya indeks kurulunca proje ayarları ve bellek
  içi doküman önbelleği temizlenir.
- Aynı veya iç içe indeks yolu kullanan projeler reddedilir; bir projenin
  `rebuild` işlemi başka projenin indeksini silemez.
- `paperqa_status` manifest ile indeks arasındaki eksik/fazla dosyaları
  `missing_from_index` ve `index_only_files` alanlarıyla raporlar.
- `paperqa_read_pages` tek çağrıda en fazla 50 sayfa okur; daha uzun aralıklar
  parçalanmalıdır.

## Ortam değişkenleri

| Değişken | Varsayılan | Görev |
|---|---|---|
| `LIT_PROJECTS_REGISTRY` | `~/.literature-mcp/projects.json` | Ortak proje kaydı |
| `PAPERQA_INDEX_ROOT` | `~/.literature-mcp/indexes` | Varsayılan indeks kökü |
| `PAPERQA_PROJECTS_ROOT` | `~/.literature-mcp/projects` | Varsayılan manifest kökü |
| `PAPERQA_LOCAL_LLM` | `qwen2.5-3b-instruct` | Model adı/alias |
| `PAPERQA_LOCAL_API_BASE` | `http://127.0.0.1:8080/v1` | OpenAI uyumlu uç nokta |
| `PAPERQA_LOCAL_API_KEY` | boş | Gerekirse API anahtarı |
| `PAPERQA_LOCAL_MAX_TOKENS` | `400` | Cevap başına token sınırı |
| `PAPERQA_LOCAL_TEMPERATURE` | `0.1` | Örnekleme sıcaklığı |
| `PAPERQA_LOCAL_TIMEOUT` | `600` | LiteLLM istek zaman aşımı (sn) |
| `PAPERQA_AUTO_START` | `1` | `paperqa_ask` için llama.cpp otomatik başlatma |
| `PAPERQA_AUTO_STOP_IDLE` | `300` | Otomatik durdurma için boşta süresi (sn); `0` kapatır |
| `PAPERQA_LLAMA_START_TIMEOUT` | `120` | Otomatik başlatma bekleme süresi (sn) |
| `PAPERQA_LLAMA_MIN_FREE_MB` | `1200` | Gereken en az boş RAM (MB); `0` denetimi kapatır |
| `PAPERQA_LLAMACPP_MODEL` | `qwen` | Başlatma betiğine verilen model seçimi |
| `PAPERQA_LLAMACPP_SCRIPT` | `scripts/start_llamacpp.sh` | Başlatma betiği yolu |
| `PAPERQA_LLAMACPP_LOG` | `/tmp/opencode/llama-server-auto.log` | Otomatik sunucu günlüğü |
| `PAPERQA_LLAMACPP_PIDFILE` | `~/.literature-mcp/llama-server.pid` | Sahiplik/pid dosyası |
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
          "PAPERQA_PROJECTS_ROOT": "/home/you/.literature-mcp/projects",
          "PAPERQA_LOCAL_LLM": "qwen2.5-3b-instruct",
          "PAPERQA_LOCAL_API_BASE": "http://127.0.0.1:8080/v1"
        }
      }
    }
  }
}
```

Tam iki sunuculu örnek (OpenCode `providers.llamacpp` dâhil):
[`../../config/opencode.example.json`](../../config/opencode.example.json).

## Sınırlar

- PDF indirmez; yalnızca kullanıcının yerel klasöründeki dosyaları okur.
- `paperqa_ask` yerel modelle (varsayılan 3B) çalışır; atıf ve sayfa hatası
  yapabilir. Kanıt olarak kullanılamaz.
- Otomatik başlatma RAM eşiğinin altında çalışmaz; `paperqa_ask` açık hata
  döndürür. Sunucu yalnızca MCP'nin başlattığı durumda otomatik durdurulur.
- İndeksleme CPU'da yavaş olabilir; büyük projelerde disk alanı gerekir.
- İndeksler ve PDF'ler depoya commit edilmez.

## Test

```bash
PYTHONPATH=packages/paperqa-local \
  python3 -m unittest discover -s packages/paperqa-local/tests -v
```

Testler ağır PaperQA2/llama.cpp bağımlılıkları olmadan çalışır; model ve
indeks dosyaları CI'ya taşınmaz.

## Lisans

MIT. Ayrıntılar: [`../../LICENSE`](../../LICENSE).
