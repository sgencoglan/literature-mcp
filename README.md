# literature-mcp

[![validate](https://github.com/sgencoglan/literature-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sgencoglan/literature-mcp/actions/workflows/ci.yml)

Kaynaklı literatür taraması, kanıta dayalı bölüm taslağı ve mevcut taslak denetimi için iki yerel MCP sunucusu, şemalar ve HTML üreticileri.

> **Sürüm:** v2.8.0. Son public sürüm v2.7.1. Depoda PDF, indeks,
> kişisel proje kaydı veya yayımlanmamış bölüm metni tutulmaz.

## Ne çözer?

Kullanıcı önce proje klasörünün yolunu verir. `paperqa_create_workspace` bu
klasörde 01–05 iş akışı klasörlerini açar; ardından MCP hangi akışın yapılacağını
sorar. Yalnızca seçimden sonra ilgili arama veya dosya işleme başlar. PDF,
manifest ve indeks proje kökünde kalır.

Başlangıç sırası: proje kökünü al → `paperqa_create_workspace` ile dört akış
klasörünü aç → kullanıcıya “0 Konu/başlık keşfi, 1 Kaynak keşfi, 2 PDF’lerden
bölüm taslağı, 3 Mevcut taslağı denetleme” seçeneklerini sor → seçilen akışın
girdilerini işle.

0. **Konu, çalışma başlığı ve amaç keşfi:** varsayılan olarak yedi kaynağın
   tümü (OpenAlex, Semantic Scholar, PubMed, Europe PMC, Crossref, arXiv,
   ClinicalTrials.gov) taranır; konu sinyalleri ve en yakın çalışmalar bu
   sonuçlardan çıkarılır → olası araştırma boşluklarına dayalı başlık/amaç önerilerini sırala →
   `01_konu_belirleme/` içine JSON ve tek dosyalık HTML raporu yaz →
   kullanıcı bir başlığı seçince varsayımları açık yöntem/tasarım önerisini
   aynı klasöre JSON ve HTML olarak kaydet.

Şema ve HTML üreticisi: [`topic-discovery.schema.json`](schemas/topic-discovery.schema.json),
[`build_topic_discovery.py`](scripts/build_topic_discovery.py).
Seçilen başlık için tasarım çıktısı: [`study-design.schema.json`](schemas/study-design.schema.json),
[`build_study_design.py`](scripts/build_study_design.py).

1. **Konu belirleme:** Başlık önerileri → kullanıcı başlığı, **ürün türünü**
   (kitap bölümü / uygulama rehberi / derleme makale / ampirik makale) ve hedef
   kelime sayısını seçer → `01_konu_belirleme/01_konu_<zaman>.html`.
2. **Yazım planı:** Onaylı tür ve uzunluğa göre alt başlık iskeleti; her başlık
   için amaç, hedef kelime ve gereken kanıt türü →
   `02_yazim_plani/01_yazim_plani_<zaman>.html`. Kullanıcı onaylamadan
   sonraki akış başlamaz.
3. **Plana göre kaynak keşfi:** Her alt başlık için hedefli arama → atama
   matrisi (alt başlık → DOI) → boşluk analizi → yalnızca atanmış PDF'lerin
   indirilmesi → `03_kaynak_kesfi/`.
4. **Taslak yazma:** PDF'ler → PaperQA indeksi → sayfa doğrulamalı yazım →
   `04_taslak/04_taslak_<zaman>.html`.
5. **Taslak analizi:** Plan uyumu (yazılmayan başlık, kelime sapması, plansız
   bölüm) + iddia–kanıt denetimi + bağlam değerlendirmesi →
   `05_analiz/05_analiz_<zaman>.html`.

Temel ilke: **LLM çıktısı kanıt değildir.** Kanıt, PDF sayfasından okunan
birebir cümle ve doğrulanmış DOI'dir. `paperqa_ask` yalnızca taslak/özet
üretir; `evidence_check` yalnızca lexical ön taramadır.

Üretilen HTML, Markdown, manifest ve rapor dosyaları varsayılan olarak
`_YYYYMMDD-HHMMSS` soneki alır; aynı komut tekrar çalıştırıldığında önceki
çıktı ezilmez. Yeni çalıştırma **eskisini silmez**, yalnızca yeni bir sürüm
ekler. Sabit ad gerekiyorsa üreticilere `--no-timestamp` verin; aynı ad zaten
varsa `--force` olmadan yazılmaz.
Kaynak listesi HTML'inde tıklanabilir DOI ve yayıncı düğmeleri ile düz metin
DOI açık adresi bulunur; indirilen PDF'ler otomatik işaretlenir. Bölüm raporu
HTML'inde DOI'yi panoya kopyalayan düğme korunur. Açık erişimli PDF'ler
`scripts/download_open_access.py` ile varsayılan olarak
`03_kaynak_kesfi/fulltext/` klasörüne indirilebilir.

## Altın standart bölüm raporu

`chapter-report`, beğenilen b1 raporunun tasarımını ve kanıt disiplinini
yeniden üretilebilir hâle getirir:

- düzeltilmiş bölüm metni; yeniden düzenlenen cümlelerde kırmızı, ilk taslakta olmayan anlamlı MCP eklemelerinde mavi/yeşil zemin,
- paragraf ve makale bağlamı değerlendirmesi; Ek 3'te DOI/metaverisi doğrulanmış kaynak adayları, Ek 4'te kaynak katkısı ve sınırları,
- **Ek 1:** yazar cümlesi → kaynak cümlesi (İngilizce) → Türkçe çeviri →
  yeniden yazılan cümle → “ne değişti / neden” notu,
- **Ek 2:** DOI ve Q bilgili kaynak envanteri, sayfa doğrulamalı iddia–kanıt
  matrisi, düzeltme özeti ve sınırlılıklar,
- tek dosya, gömülü CSS, yazdırma desteği, harici JS/CDN yok; yalnızca DOI
  kopyalama düğmesi için tek, denetimli gömülü betik.

Örnek çıktı: [`examples/chapter-report.example.html`](examples/chapter-report.example.html) ve [`examples/chapter-report.example.md`](examples/chapter-report.example.md).

```bash
python -m pip install -e packages/report-kit

# Örneği doğrula ve üret (örnek dosya sabit adlıdır)
chapter-report build examples/chapter-report.example.json \
  -o examples/chapter-report.example.html --no-timestamp --force
```

Kalite kapısı; DOI, sayfa, birebir alıntı, Türkçe çeviri, atıf ve yerel yol
yasağını denetler. `--strict` uyarıları da hata sayar. Ayrıntılar:
[`docs/report-standard.md`](docs/report-standard.md).

### Üretilen dosyaları temizleme

`chapter-report build` bir manifest yazar. Analiz bittikten sonra yalnızca bu
manifestte listelenen üretilmiş dosyalar silinebilir:

```bash
chapter-report build rapor.json -o 05_analiz.html \
  --markdown 05_analiz.md \
  --artifact 02_degisiklik_kartlari.json \
  --artifact 03_iddia_kanit_matrisi.csv \
  --cleanup ask
```

Üretici, verilen adların sonuna varsayılan olarak `_YYYYMMDD-HHMMSS` ekler ve
manifest adını da buna göre yazar; sabit ad için `--no-timestamp` kullanın.

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
| `sciencedirect-meta` MCP | [`packages/sciencedirect-meta`](packages/sciencedirect-meta) | 22 araç: metadata/DOI arama (OpenAlex, Semantic Scholar, PubMed, Europe PMC, Crossref, arXiv, ClinicalTrials.gov), kapsam/kanıt sinyali, DOI doğrulama, dergi quartile, yerel PDF okuma, kanıt denetimi, rapor dışa aktarma |
| `paperqa-local` MCP | [`packages/paperqa-local`](packages/paperqa-local) | 10 araç: proje klasörlerini başlatma, fulltext aktarımı, kayıt, manifest, PaperQA2 indeksi, semantik arama, sayfa okuma, LLM durumu, yerel taslak |
| `report-kit` | [`packages/report-kit`](packages/report-kit) | Altın standart HTML raporu, kalite kapısı ve manifest tabanlı temizlik |
| Ortak proje kaydı | `projects.json` (varsayılan: `~/.literature-mcp/projects.json`) | Her projenin PDF klasörü, manifesti ve indeksi; projeler izoledir |
| Fulltext üreticisi | [`scripts/build_fulltext_list.py`](scripts/build_fulltext_list.py) | DOI adaylarını tek dosyalık, yazdırılabilir HTML'e çevirir; DOI/yayıncı düğmeleri ekler, indirilen PDF'leri otomatik işaretler |
| Açık erişim indiricisi | [`scripts/download_open_access.py`](scripts/download_open_access.py) | Unpaywall/OpenAlex üzerinden yalnızca açık erişimli PDF'leri varsayılan olarak `03_kaynak_kesfi/fulltext/` klasörüne indirir |
| PaperQA kurulumu | [`scripts/setup_paperqa.sh`](scripts/setup_paperqa.sh) | CPU-only PyTorch, PaperQA2 ve `sentence-transformers` kurar; `--check` ile doğrular |
| Çıktı adlandırma | [`scripts/output_naming.py`](scripts/output_naming.py) | `_YYYYMMDD-HHMMSS` sonekini üretir; çakışmada `-01`, `-02` ekler |
| Şemalar | [`schemas/`](schemas) | Fulltext listesi, düzeltme kartı, iddia–kanıt matrisi, bölüm raporu |
| Ajan sözleşmesi | [`AGENTS.md`](AGENTS.md) | Bağlayıcı kurallar, araç politikası, kabul kriterleri |
| Araç kataloğu | [`docs/tool-catalog.json`](docs/tool-catalog.json) | 31 aracın makine okunabilir girdi/çıktı şeması |

## Kurulum

Python 3.10+ gerekir.

```bash
git clone https://github.com/sgencoglan/literature-mcp.git
cd literature-mcp

python3 -m venv .venv
.venv/bin/pip install -e packages/sciencedirect-meta
.venv/bin/pip install -e packages/report-kit
```

### Kimlik bilgileri ve API anahtarları

Anahtarlar zorunlu değildir; araçlar anahtarsız da çalışır. Önerilen asgari
kurulum, iletişim e-postasını (`mailto`) tanımlamaktır:

| Servis | Anahtar gerekli mi? | Not |
|---|---|---|
| OpenAlex | Hayır | `mailto` önerilir; anahtar hız limitini yükseltir. |
| PubMed / NCBI E-utilities | Hayır | Anahtarsız 3 istek/sn; anahtarla 10 istek/sn. |
| Europe PMC | Hayır | Anahtar kullanmaz. |
| Crossref | Hayır | `mailto` önerilir. |
| Unpaywall | Hayır; e-posta zorunlu | `setup.txt` içindeki `email` kullanılır. |
| Yerel `paperqa_ask` | Hayır | llama.cpp kullanır; bulut API anahtarı gerekmez. |

Kurulumdan sonra:

```bash
python3 scripts/setup_credentials.py
```

Betik önce proje kökündeki `setup.txt` dosyasını arar; varsa bilgileri
otomatik alır, yoksa sırasıyla iletişim e-postasını (Crossref/NCBI/OpenAlex),
OpenAlex API anahtarını, PubMed/NCBI API anahtarını ve isteğe bağlı Semantic
Scholar API anahtarını sorar. Bilgiler yalnızca
OpenCode yapılandırmasındaki `mcp.servers.sciencedirect-meta.environment`
bölümüne yazılır; dosya izni `600` yapılır ve eski dosya yedeklenir. Sırlar
depoya kaydedilmez.

MCP sunucusu ayrıca **kendi başına** `setup.txt` dosyasını süreç başında okur
(`sciencedirect_meta.bootstrap`): proje kökünde, kayıtlı projelerin
`output_directory`/`paper_directory` yakınında veya çalışma dizininin üst
klasörlerinde arar. Böylece editörden başlatıldığında anahtarlar için ayrıca
ortam değişkeni tanımlamak gerekmez. Var olan ortam değişkeni her zaman
dosyadaki değerden önceliklidir. Aramayı sabitlemek için `LIT_SETUP_FILE`
veya `LIT_PROJECT_ROOT` kullanılabilir.

Arama araçları (`search_all`, `search_literature`, `deep_research`) ayrıca
`project_directory` parametresi alır. Bu parametre verildiğinde **o proje
klasöründeki `setup.txt`** yeniden okunur ve API anahtarları ile iletişim
e-postası bu çağrıda kullanılır; başka bir projenin anahtarı geçerli projenin
anahtarını ezmez. `project_directory` verilmezse kayıtlı `project` adının
`output_directory` değeri, o da yoksa `LIT_PROJECT_ROOT` kullanılır. Yanıttaki
`setup_file` alanı hangi dosyanın etkin olduğunu gösterir.

`setup.txt` biçimi:

```text
# literature-mcp kurulum bilgileri
# Crossref, NCBI, OpenAlex ve Unpaywall için ortak iletişim adresi
email=you@example.org
# OpenAlex API anahtarı (isteğe bağlı)
openalex_key=...
# PubMed/NCBI API anahtarı (isteğe bağlı)
pubmed_key=...
# Semantic Scholar API anahtarı (isteğe bağlı; 1 istek/sn kişisel kota)
semantic_scholar_key=...
```

Semantic Scholar anahtarsız ortak havuzda sık `429` verir. Anahtar varsa
istemci istekleri **1/sn** sınırına uyacak şekilde sıraya koyar (2 sn aralık),
`429` durumunda `Retry-After` kadar bekler ve kaynağı kısa süre (8 sn) devre
dışı bırakır. Anahtar yoksa bekleme 120 sn'dir.

Unpaywall anahtar istemez; `email` alanını kullanır. İsterseniz aynı adresi
`unpaywall_email` adıyla da yazabilirsiniz. Anahtar adları büyük/küçük harfe
duyarsızdır; `e-posta`, `openalex_api_key`, `ncbi_key` gibi eş anlamlılar da
kabul edilir. Örnek dosya:
[`examples/setup.example.txt`](examples/setup.example.txt). Açık yolla okumak için:

```bash
python3 scripts/setup_credentials.py --project /path/to/project
python3 scripts/setup_credentials.py --from-file /path/to/setup.txt
```

`setup.txt` düz metin sır içerir; `chmod 600 setup.txt` uygulayın ve sürüm
kontrolüne eklemeyin. Anahtarları yalnızca bu dosyada tutmak yeterlidir;
MCP sunucusu süreç başında dosyayı kendisi okur. İsterseniz aramayı
sabitlemek için `LIT_SETUP_FILE=/yol/setup.txt` ortam değişkenini verin.
Durumu görmek için:

```bash
python3 scripts/setup_credentials.py --check
```

İnteraktif soru istemiyorsanız bayraklarla çalıştırın:

```bash
python3 scripts/setup_credentials.py --non-interactive \
  --email you@example.org \
  --openalex-key "$OPENALEX_API_KEY" \
  --pubmed-key "$PUBMED_API_KEY"
```

`paperqa-local` indeksi için PyTorch, `sentence-transformers` ve PaperQA2
gerekir. CUDA paketlerini indirmemek için CPU-only kurulum betiğini kullanın:

```bash
bash scripts/setup_paperqa.sh

# Kurulumu doğrula (torch CUDA'sız mı, tüm importlar hazır mı?)
bash scripts/setup_paperqa.sh --check
```

Betik önce `https://download.pytorch.org/whl/cpu` indeksinden CPU PyTorch
kurar; ardından PaperQA2, `sentence-transformers`, MCP ve PyMuPDF'i kurar.
Elle kurulum için bağımlılık listesi:
[`requirements-paperqa.txt`](requirements-paperqa.txt). İlk indeks kurulumunda
`st-multi-qa-MiniLM-L6-cos-v1` embedding modeli indirilir.

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

### Açık erişimli PDF'leri indirmeKaynak listesindeki açık erişimli PDF'leri Unpaywall (önce) ve OpenAlex
(yedek) üzerinden indirin. Varsayılan hedef, otomatik oluşturulan
`03_kaynak_kesfi/fulltext/` klasörüdür:

```bash
# Akış 3 (varsayılan): 03_kaynak_kesfi/fulltext/
python3 scripts/download_open_access.py \
  <proje-kökü>/03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json

# Akış 4: 04_taslak/fulltext/
python3 scripts/download_open_access.py \
  <proje-kökü>/03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json --workflow 4

# Akış 5: 05_analiz/fulltext/
python3 scripts/download_open_access.py \
  <proje-kökü>/03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json --workflow 5

# Yalnızca denetim: hangi DOI'lerde OA PDF var?
python3 scripts/download_open_access.py adaylar.json --dry-run

# Kaynak listesi JSON'una OA alanlarını da yaz
python3 scripts/download_open_access.py adaylar.json --update-json
```

Betik yalnızca herkese açık `http(s)` PDF bağlantılarını dener; ödeme duvarını
veya erişim kontrolünü aşmaz. Unpaywall için `setup.txt` içindeki `email`
kullanılır (`--email` ile de verilebilir). İndirme raporu her akışta doğrudan
o akışın klasörüne `oa_indirme_raporu_<zaman>.json` olarak yazılır; e-posta
raporda maskelenir. Doğrudan PDF bağlantısı olmayan açılış sayfalarında
`citation_pdf_url` / PDF bağlantısı bir kez çözülmeye çalışılır.

### Arama kapsamı ve kanıt sınırlılığı

`search_all`, `search_literature` ve `deep_research` cevapları artık her sonuç
için bir `score`, her arama için bir `coverage` bloğu ve bir
`evidence_scarcity` sinyali döndürür.

**Varsayılan tarama kapsamı:** üç araç da yedi kaynağın tümünü sorgular
(OpenAlex, Semantic Scholar, PubMed, Europe PMC, Crossref, arXiv,
ClinicalTrials.gov) ve `priority_only` varsayılan olarak `false` olduğu için
tüm yayıncılar döner. `sources=[...]` ile kaynak kümesi, `priority_only=true`
ile yalnızca beş öncelikli platform daraltılabilir. Her kaynak için
`coverage.per_source` içindeki `status` (`ok`/`error`/`rate_limited`) ve
`notes` alanları hangi veritabanının gerçekten tarandığını gösterir; sessizce
atlanan kaynak olmaz.

**Hız limitleri:** istekler servis başına sıraya konur (OpenAlex anahtarsız
~2/sn, anahtarla ~10/sn; NCBI anahtarsız ~3/sn, anahtarla ~10/sn; Europe PMC
ve Crossref ~5–8/sn; arXiv 3 sn). 429 alındığında `Retry-After` kadar beklenir,
yeniden denenir ve kaynak yine sınırlıysa yalnızca o kaynak için
`rate_limited` durumu raporlanır; diğer kaynaklar ve tool çağrısı hata
döndürmez. Aynı çalıştırmadaki kalan facet'ler devre dışı kaynağı tekrar
zorlamaz.

- `score`: 0.35 anlamsal alaka + 0.25 log ölçekli atıf + 0.15 güncellik +
  0.15 SCImago quartile + 0.10 çalışma türü. Preprint skoru 0.85 ile çarpılır.
- `coverage.query_expansion`: orijinal sorgu, genişletilmiş sorgular, MeSH
  terimleri, dil dönüşümü, kullanılan dönüşümler ve notlar. Ajan bu kaydı
  `query_expansion` parametresiyle açıkça verebilir; verilmezse orijinal sorgu
  ve `query_variants` üzerinden türetilir.
- `coverage.per_source`: kaynak başına dönen kayıt, tekil DOI ve yüksek
  kaliteli sonuç sayısı; ayrıca `status` (ok/error/rate_limited), `note`,
  `requested_limit`, `duration_ms` ve `rate_limited`.
- `coverage.skipped_sources` + `coverage.warnings`: sorgulanmayan kaynaklar ve
  hata/hız limiti/atlama uyarıları.
- `coverage.publisher_distribution`: ScienceDirect, Ovid LWW, SpringerLink,
  Wiley, Taylor & Francis, diğer ve bilinmeyen dağılımı; açık erişim, preprint
  ve PDF bağlantısı oranları.
- `coverage.evidence_density`: toplam kayıt, yüksek kalite, katı yüksek kalite
  (Q1/Q2 + atıf + RCT/SR/MA), Q1 sayısı/oranı, son 5 yıl sayısı/oranı, RCT,
  sistematik derleme/meta-analiz, klinik çalışma, preprint, çalışma türü
  dağılımı ve son 3 yıl `trend` (yön + yıllık sayılar).
- `evidence_scarcity`: yüksek kaliteli sonuç sayısı 5'in altındaysa `true`;
  mesaj en yakın 5 çalışmayı DOI ve yılıyla listeler ve “Araştırma boşluğu
  olasılığı yüksektir” uyarısını ekler.
- `coverage.evidence_density.high_quality_strict_total`: Q1/Q2 + en az 10 atıf
  + RCT/sistematik derleme koşulunu sağlayan katı yüksek-kalite sayısı.
- `coverage.evidence_density.trend`: son 3 yılın yıllık yayın sayısı, eğim ve
  `artıyor` / `azalıyor` / `sabit` / `belirsiz` yönü.

Karşılaştırmalı tarama ve Markdown çıktısı:

```bash
# İki query setinin kapsam farkı (JSON + HTML)
python3 scripts/build_search_coverage.py arama_b.json \
  -o <proje-kökü>/03_kaynak_kesfi \
  --compare arama_a.json --compare-label "Set A"

# Seçilen makaleleri sonuç tablosunda "seçildi" etiketiyle işaretle
python3 scripts/build_search_coverage.py arama.json \
  -o <proje-kökü>/03_kaynak_kesfi \
  --fulltext-list <proje-kökü>/03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json

# Markdown çıktısını kapat / özeti stdout'a bas
python3 scripts/build_search_coverage.py arama.json --no-markdown
python3 scripts/build_search_coverage.py arama.json --auto-report
```

Aynı bloğu `03_kaynak_kesfi/` içine JSON + HTML rapor olarak yazın:

```bash
# Arama cevabını (coverage alanıyla) dosyaya kaydedin, sonra:
python3 scripts/build_search_coverage.py arama.json \
  -o <proje-kökü>/03_kaynak_kesfi

# Yalnızca doğrula
python3 scripts/build_search_coverage.py arama.json --check
```

Çıktılar `01_arama_kapsam_raporu_<zaman>.json`, `.html` ve `.md` olur; HTML
tek dosyadır, yazdırılabilir ve kaynak bazında kapsamı şeffaf biçimde gösterir.
`--compare <ikinci.json>` iki query setinin kapsam farkını
`..._karsilastirma.json/html` olarak yazar; `--no-markdown` Markdown çıktısını
kapatır, `--auto-report` özeti stdout'a basar.

### Akış 2'ye geçerken fulltext aktarımı

İş akışı 3'te `03_kaynak_kesfi/fulltext/` altına inen açık erişimli PDF'ler,
iş akışı 4 ve 5'te ayrı bir klasörde gerekir. Aktarım aracı bunu kendisi yapar:

```bash
# Planı göster (hiçbir dosya değişmez)
python3 scripts/promote_fulltext.py <proje-kökü> --to 4 --dry-run

# Kopyala + DOI adına çevir (varsayılan)
python3 scripts/promote_fulltext.py <proje-kökü> --to 4

# Taşı (kaynak klasör boşalsın)
python3 scripts/promote_fulltext.py <proje-kökü> --to 4 --move
```

Aynı işlem MCP aracıyla da yapılır:
`paperqa_promote_fulltext(project_directory=..., target_workflow="4")`.

- Dosya adı DOI'den üretilir, özel karakterler atılır: `10.4073/csr.2011.4`
  → `10.4073csr.2011.4.pdf`.
- DOI önce dosya adından, sonra PDF'in ilk iki sayfasından, sonra akış 1
  listesindeki başlık eşleşmesinden çözülür. Kullanıcının kendi indirdiği
  adlandırılmamış PDF'ler de aynı kuralla düzeltilir.
- Hiçbir dosya **silinmez**; hedefte aynı DOI varsa atlanır.

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
          "JOURNAL_RANK_CSV": "<repo>/packages/sciencedirect-meta/data/scimagojr_2024.csv.gz",
          "CROSSREF_MAILTO": "<email>",
          "OPENALEX_API_KEY": "<openalex-api-key>",
          "PUBMED_API_KEY": "<pubmed-api-key>",
          "SEMANTIC_SCHOLAR_API_KEY": "<semantic-scholar-api-key>",
          "NCBI_EMAIL": "<email>"
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

## İş akışı 3 — Plana göre kaynak keşfi

### Öncesi: İş akışı 1 ve 2

Konu henüz net değilse 0. akışta OpenAlex, PubMed, Europe PMC ve Crossref
taranır; sorgu kapsamı ve veri tabanı durumları kaydedilir. Olası çalışma
başlıkları, araştırma soruları, amaçlar, yakın çalışmalar ve uygulanabilirlik
gerekçeleriyle sıralanır. Özgünlük, bu taramada görülen boşluk sinyali olarak
ifade edilir; kesin yenilik iddiası değildir. Raporlar
`01_konu_belirleme/01_konu_belirleme.html` ve `.json` olarak yazılır.
Seçilen önerinin ardından yöntem/tasarım önerisi
`01_konu_belirleme/01_yontem_tasarimi.html` ve `.json` olarak hazırlanır.
Varsayımlar, örneklem hesabı, ölçüm aracı sınırlılıkları ve etik noktalar
görünür tutulur; öneri kullanıcı/araştırma ekibi onaylayana kadar
kesinleştirilmez. Onaylanan başlık ve tasarım akış 1'in arama çerçevesine
aktarılabilir.

Başlamadan önce kullanıcıdan proje klasörünün yolunu alın. Bu klasör yoksa
kullanıcının verdiği tam yolda oluşturun; mevcut çalışma dizinini veya rastgele
geçici bir klasörü çıktı konumu olarak seçmeyin.

Ardından `paperqa_create_workspace(project_directory)` çağrısıyla proje
kökünde `01_konu_belirleme/`, `02_yazim_plani/`, `03_kaynak_kesfi/`, `04_taslak/` ve `05_analiz/`
klasörlerini oluşturun. Proje adı klasör adından alınır; istenirse `name`
parametresiyle açıkça verilebilir. Ardından kullanıcıya 1, 2, 3, 4 veya 5. iş
akışını seçmesini sorun; seçimden önce kaynak araması ya da PDF işleme yapmayın.

```text
<proje-kökü>/
├── 01_konu_belirleme/     # Akış 1: başlık, tür, kapsam
├── 02_yazim_plani/        # Akış 2: alt başlık iskeleti
├── 03_kaynak_kesfi/       # Akış 3: arama, atama, OA PDF'ler
├── 04_taslak/             # Akış 4: taslak + fulltext/
├── 05_analiz/             # Akış 5: plan uyumu + kanıt analizi
└── .literature-mcp/       # Manifest ve yerel indeks
```

```text
Konu/araştırma çerçevesi
  → search_literature (OpenAlex + Semantic Scholar + PubMed + Europe PMC + Crossref)
  → en yakın çalışmalar, olası boşluklar ve yapılabilirlik değerlendirmesi
  → coverage + score + evidence_scarcity
  → sıralı başlık + araştırma sorusu + amaç önerileri
  → schemas/topic-discovery.schema.json
  → scripts/build_topic_discovery.py
  → <proje-kökü>/01_konu_belirleme/01_konu_<zaman>.html
  → kullanıcı önerilerden birini seçer
  → schemas/study-design.schema.json
  → scripts/build_study_design.py
  → <proje-kökü>/01_konu_belirleme/01_yontem_tasarimi_<zaman>.html

Onaylanmış başlık + tür + hedef kelime
  → alt başlık iskeleti (S1…Sn) + kanıt ihtiyacı
  → schemas/writing-plan.schema.json
  → scripts/build_writing_plan.py
  → <proje-kökü>/02_yazim_plani/01_yazim_plani_<zaman>.html
  → kullanıcı iskeleti onaylar (plan_status=approved)

Plan
  → alt başlık başına hedefli sorgular
  → deep_research / search_literature
  → coverage + score + evidence_scarcity
  → scripts/build_assignment_matrix.py --update-plan
  → <proje-kökü>/03_kaynak_kesfi/00_atama_matrisi_<zaman>.html
  → boşluk varsa kullanıcıya sor
  → scripts/build_fulltext_list.py + build_search_coverage.py + build_fulltext_index.py
  → scripts/download_open_access.py (yalnızca atanmış DOI'ler)
```

## İş akışı 4 — Taslak yazma

PDF'leri `<proje-klasörü>/04_taslak/fulltext/` içine koyun veya akış 3'ten
`python3 scripts/promote_fulltext.py <proje-kökü> --to 4` ile aktarın. Taslak
çıktıları doğrudan `04_taslak/` altında tutulur (ayrı `taslak/` alt klasörü yok). Aynı
`chapter-report` şablonu taslak HTML'inde bölüm metnini, Ek 1 kaynak–taslak
eşleştirmelerini ve Ek 2 iddia–kanıt matrisini verir.

```text
Kullanıcı PDF'leri `<proje-kökü>/04_taslak/fulltext/` klasörüne indirir
  → paperqa_register_project
  → project_audit
  → paperqa_build_index
  → paperqa_status + library_status
  → paperqa_search / paperqa_read_pages / read_paper
  → <proje-kökü>/04_taslak/04_taslak_<zaman>.json
  → chapter-report build
  → <proje-kökü>/04_taslak/04_taslak_<zaman>.html + .md
```

## İş akışı 5 — Taslak analizi

Denetlenen taslak ve rapor çıktıları doğrudan
`<proje-kökü>/05_analiz/` içinde tutulur. Kullanıcı denetlenecek taslağı da
bu klasöre koyar. Ana rapor `05_analiz_<zaman>.html` dosyasıdır.

```text
Kullanıcı taslağı 05_analiz/ içine, PDF'leri
05_analiz/fulltext/ içine koyar
  → ayrı PaperQA proje kaydı (workflow_project_names.analysis)
  → project_audit / paperqa_status / library_status
  → taslağı cümlelere/iddialara ayır
  → her iddia için paperqa_search + paperqa_read_pages
  → verify_doi_and_publisher + doi_provenance + journal_rank
  → düzeltme kartları (schemas/change-card.schema.json)
  → Ek 2 kaynak denetimi
  → iddia–kanıt matrisi (schemas/claim-evidence.schema.json)
  → chapter-report build → <proje-kökü>/05_analiz/05_analiz_<zaman>.html
  → istenirse --cleanup intermediate/all
```

## Çıktılar

Ana ve ek çıktılar ilgili iş akışı klasöründedir. Manifest ve indeks proje
kökündeki `.literature-mcp/` klasörüne yazılır. Üreticiler varsayılan olarak
`_YYYYMMDD-HHMMSS` soneki ekler; aşağıdaki adlar soneksiz gösterilmiştir:

```text
03_kaynak_kesfi/00_atama_matrisi_<zaman>.json
03_kaynak_kesfi/00_atama_matrisi_<zaman>.html
03_kaynak_kesfi/00_kaynak_listeleri_<zaman>.html
03_kaynak_kesfi/01_fulltext_listesi_<zaman>.html (tek araştırma)
03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json
03_kaynak_kesfi/01_<arastirma-kisa-adi>_fulltext_listesi_<zaman>.html (çoklu araştırma)
03_kaynak_kesfi/01_<arastirma-kisa-adi>_fulltext_listesi_<zaman>.json
03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>.json/.html/.md
04_taslak/04_taslak_<zaman>.json
04_taslak/04_taslak_<zaman>.html
04_taslak/04_taslak_<zaman>.md
04_taslak/04_taslak_<zaman>.manifest.json
04_taslak/oa_indirme_raporu_<zaman>.json
05_analiz/05_plan_uyumu_<zaman>.json/.html
05_analiz/02_degisiklik_kartlari_<zaman>.csv
05_analiz/02_degisiklik_kartlari_<zaman>.json
05_analiz/03_kaynak_denetimi_<zaman>.csv
05_analiz/03_iddia_kanit_matrisi_<zaman>.csv
05_analiz/05_analiz_<zaman>.html
05_analiz/05_analiz_<zaman>.md
05_analiz/05_analiz_<zaman>.manifest.json
```

- HTML: insan tarafından okunur, tek dosya, yazdırılabilir; bölüm raporunda
  DOI kopyalama düğmesi içerir (fulltext listesinde DOI/yayıncı düğmeleri ve
  düz metin DOI açık adresi bulunur).
- Markdown: düzenleme ve sürüm kontrolü; HTML ile aynı veriden üretilir.
- CSV/JSON: veri işleme ve ajanlar.
- DOI linkleri yalnızca `https://doi.org/...`; teslimlerde yerel PDF yolu veya
  `file://` linki bulunmaz.
- `05_analiz_<zaman>.html` altın standarttır;
  `05_analiz_<zaman>.json/md` denetim verisini ve düzenlenebilir eşlik dosyasını taşır.

## Gizlilik ve güvenlik

Depoya **konulmaması gerekenler**:

- PDF'ler ve indirilen tam metinler,
- PaperQA2 indeksleri ve embedding önbellekleri,
- kişisel `projects.json`, manifestler ve analiz dosyaları,
- yayımlanmamış bölüm metinleri ve düzeltilmiş HTML çıktıları,
- `.venv`, `.env`, API anahtarları, oturum belgeleri,
- SCImago CSV'si (lisans nedeniyle; indirme betiği kullanılır).

`scripts/download_open_access.py` yalnızca Unpaywall/OpenAlex'in açıkça
sunduğu herkese açık PDF'leri indirir; ödeme duvarını veya erişim kontrolünü
aşmaz. Kapalı erişimli tam metinler kullanıcı hesabından indirilir ve tüm
PDF'ler yalnızca yerel olarak işlenir.

## Testler

```bash
bash scripts/validate_all.sh
```

Bu betik JSON şemalarını, Python sözdizimini, yazım korumasını (PaperQA),
fulltext üreticisini, `chapter-report` kalite kapısını, iki paketin ve
`scripts/` yardımcılarının birim testlerini çalıştırır. PaperQA bağımlılıklarını
ayrıca doğrulamak için `bash scripts/setup_paperqa.sh --check` kullanın.

## Dokümantasyon

- [`AGENTS.md`](AGENTS.md) — ajanlar için bağlayıcı kurallar
- [`docs/architecture.md`](docs/architecture.md) — bileşenler ve veri akışı
- [`docs/workflows.md`](docs/workflows.md) — adım adım iş akışları
- [`docs/output-spec.md`](docs/output-spec.md) — dosya adları ve biçimler
- [`docs/report-standard.md`](docs/report-standard.md) — altın standart ve kalite kapısı
- [`docs/local-llm.md`](docs/local-llm.md) — llama.cpp kurulumu, model ve donanım sınırı
- [`docs/tool-catalog.md`](docs/tool-catalog.md) — 31 aracın özeti
- [`docs/publishing.md`](docs/publishing.md) — public repo kontrolü

## Lisans

MIT. Ayrıntılar: [`LICENSE`](LICENSE).
