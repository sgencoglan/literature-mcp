# Eksik kaynak ve kapsam denetimi

Amaç, aramanın eksiksiz olduğunu ilan etmek değil; yeni adayları, olası
tekrarları, kimlik çelişkilerini, bulunamayan bilinen yayınları ve taranmamış
kaynakları görünür kılmaktır. Araç ağ çağrısı yapmaz; mevcut sonuçları denetler.

## Önerilen sıra

1. Konu başlığını kavramlara ve eş anlamlılara ayırın.
2. Tıpta PubMed/MEDLINE; psikoloji/psikiyatride ayrıca erişim varsa PsycInfo
   ve Embase ile alan taraması yapın.
3. Scholar'da **site filtresiz** sorgularla kitap/bölüm, tez ve başka
   yayıncılardaki kaynakları keşfedin.
4. İlgili derlemelerin kaynakçalarını ve temel yayınlara atıf yapan
   çalışmaları kontrol edin. Bu işlemi arama günlüğünde ayrı kaydedin.
5. Yayıncıya özel `site:` sorgularını tamamlayıcı olarak kullanın.

Tedavi/müdahale araştırmasında `--purpose intervention`, CENTRAL ve
ClinicalTrials.gov'u öncelik listesine ekler. Bunlar araştırma sorusuna göre
uyarlanacak başlangıç tercihleridir; tek ve zorunlu bir kalite sırası değildir.
Kaynakça taraması özellikle kavramsal çalışmalarda, PsycInfo psikoloji ve
davranış bağlamında önemlidir. PubMed her kitap bölümünü kapsamaz.

Dayanak: [Cochrane arama rehberi](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04),
[NIH literatür kaynakları](https://www.nihlibrary.nih.gov/services/evidence-synthesis/find-literature),
[Scholar arama ve kapsam açıklaması](https://scholar.google.com/intl/en/scholar/help.html).
Scholar'da `site:` yalnızca yayının birincil sürümünü esas alır.

## Komut satırı

Kavram haritası ve kaynak havuzu hazır olduğunda:

```bash
python3 scripts/build_literature_audit.py \
  --framework /path/to/workspace/01_konu_belirleme/02_kavram_haritasi_TIMESTAMP.json \
  --baseline /path/to/workspace/03_kaynak_kesfi/pool.json \
  --additional /path/to/workspace/03_kaynak_kesfi/scholar-results.ris \
  --known-items /path/to/workspace/03_kaynak_kesfi/known-items.json \
  --search-log /path/to/workspace/03_kaynak_kesfi/search-log.json \
  --domain psychology --purpose overview \
  -o /path/to/workspace/03_kaynak_kesfi
```

`--additional` birden çok kez verilebilir. `--known-items`, `--additional`
ve `--search-log` isteğe bağlıdır. `--check` dosya üretmeden özet döndürür.
Çıktı `02_kaynak_kapsam_denetimi_<zaman>.json/html` olur; eski raporlar korunur.
Kayıt havuzu, kişisel indeks, PDF veya kaynak listesi değiştirilmez.

## Scholar sonuçlarını aktarma

Scholar'dan veya kullandığınız kaynak yöneticisinden aldığınız **RIS**
dosyalarını içe aktarabilirsiniz. Otomatik Scholar taraması, CAPTCHA çözme
veya sorgu çalıştırma yoktur. Arama bağlantıları `not_run` olarak başlar.
İçe aktarılan dosyanın Scholar'dan geldiği kendiliğinden doğrulanmaz.

Alternatif biçimler:

- JSON: doğrudan kayıt listesi veya `records`, `results`, `candidates`
  listeli nesne. Mevcut MCP sonuçları da kullanılabilir.
- CSV: `title`, `doi`, `pmid`, `year`, `abstract`, `source` sütunları.
  En az bir tanımlayıcı/başlık bulunmalı. UTF-8 ve BOM desteklenir.
- RIS: `TI`/`T1`, `DO`, `PY`/`Y1`, `AB`/`N2`, `TY` okunur. RIS
  devam satırları birleştirilir. Kaynak adı yoksa `unspecified` kalır.

Örnek kayıt:

```json
{"title": "Kaynağın gerçek başlığı", "doi": "", "pmid": "", "year": 2024, "abstract": "", "source": "scholar"}
```

## Bilinen önemli yayınlarla kontrol

Bağımsız olarak bildiğiniz, kapsama uygun temel yayınları kontrol listesine
ekleyin. Yalnızca aramada zaten bulduklarınızı seçmek, kontrolü zayıflatır.

Eşleşme kararları:

| Karar | Anlamı |
|---|---|
| `confirmed` | DOI veya PMID değerleri eşleşti; canlı kayıt doğrulaması yapılmadı |
| `title_candidate` | Normalleştirilmiş başlık eşleşti; yıl/kimlik farkını kontrol edin |
| `identifier_conflict` | Bir kimlik eşleşirken diğeri çelişiyor; otomatik birleşmez |
| `not_found` | Verilen havuzlarda eşleşmedi; dünyadaki literatürde yok demek değildir |

Başlık eşleşmesi tek başına bilinen kaynağı bulma oranına dahil edilmez.
Kontrol listesi boşsa oran `null` olur. Bu oran genel literatür duyarlılığı
veya eksiksizlik yüzdesi değildir. `completeness` daima `not_established` kalır.

## Öncelikli inceleme ve kavram boşlukları

Yeni adaylar arasında, başlangıçta eksik bilinen yayınla kimlik eşleşenler ve
kavram boşluğuyla sözcüksel eşleşenler önce incelenir. Geri çekilme durumu
girdide `is_retracted: true` ise ayrıca işaretlenir; bu bilgi otomatik
sorgulanmaz. İnceleme sırası kalite puanı değildir.

Kavram taraması İngilizce terimleri ve eş anlamlıları kullanır. Başlık/özette
sözcük geçmesi, yayının o konuyu yeterince ele aldığını veya bir iddiayı
desteklediğini göstermez. Konu uygunluğu ve yöntem kalitesi insan/ajan
tarafından ayrıca değerlendirilir. Yeni adayların tümü `not_assessed` kalır.

## Gerçek arama günlüğü

```json
[
  {
    "source": "pubmed",
    "query": "Gerçekte çalıştırılan sorgu",
    "status": "not_run",
    "searched_at": null,
    "screening_status": "not_reported",
    "note": "Şablon; tamamlanan işlemle güncelleyin"
  }
]
```

`ok` veya `partial` için gerçek sorgu ve `searched_at` zorunludur.
Desteklenen durumlar: `ok`, `partial`, `error`, `rate_limited`, `not_run`,
`unavailable`. `ok`, sorgu işleminin başarı durumudur; bütün sonuçların
incelendiği veya araştırmanın tamamlandığı anlamına gelmez. İnceleme
durumu `screening_status` alanında ayrıca tutulur.

Kaynak adları: `pubmed`, `psycinfo`, `embase`, `central`, `scholar`,
`citation_chaining`, `clinicaltrials`, `openalex`, `crossref`, `europepmc`,
`scopus`, `webofscience`. Bir kaynakta başarılı ve başarısız sorgular
birlikte varsa genel durum `partial` olur; hatalar gizlenmez.

## Sentetik örneği çalıştırma

Aşağıdaki dosyalardaki başlık ve DOI'ler test içindir; gerçek yayın değildir:

```bash
python3 scripts/build_literature_audit.py \
  --framework examples/concept-framework.example.json \
  --baseline examples/audit-pool.example.json \
  --additional examples/audit-additional.example.ris \
  --known-items examples/audit-known.example.json \
  --search-log examples/audit-search-log.example.json \
  -o /tmp/literature-audit-demo
```

Örnekte bir kayıt havuzda vardır, bir yeni aday bulunur ve iki bilinen yayından
biri eşleşir. Aramalar yapılmış sayılmaz. JSON sözleşmesi
[`literature-audit.schema.json`](../schemas/literature-audit.schema.json)
ile tanımlıdır.
