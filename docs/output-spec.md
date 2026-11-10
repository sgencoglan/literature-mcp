# Çıktı Sözleşmesi

Bu belge, insan ve ajan çıktılarının dosya adlarını, biçimlerini ve zorunlu alanlarını tanımlar. Bir çıktı bu sözleşmeye uymuyorsa teslim edilmiş sayılmaz.

## Genel kurallar

- **Proje klasörü zorunludur:** Her yeni proje başında kullanıcıdan proje kökünün tam yolunu alın ve `paperqa_create_workspace` ile 01–05 akış klasörlerini açın.
- **Akış seçimi:** Klasörler açıldıktan sonra kullanıcıdan 1, 2, 3, 4 veya 5 seçmesini isteyin; seçimden önce arama veya PDF işleme yapmayın.
- **Akış klasörleri:** `01_konu_belirleme/`, `02_yazim_plani/`, `03_kaynak_kesfi/`, `04_taslak/`, `05_analiz/`. Her çıktıyı ilgili klasöre yazın; PDF'ler yalnızca ilgili akışın `fulltext/` altındadır.
- **Ana dosyalar:** Akış 1 `01_konu_belirleme/01_konu_<zaman>.html` (tür, hedef kelime, kapsam, başlık önerileri). Akış 2 `02_yazim_plani/01_yazim_plani_<zaman>.html` (alt başlık iskeleti). Akış 3 `03_kaynak_kesfi/00_atama_matrisi_<zaman>.html`, fulltext listesi ve kapsam raporu. Akış 4 bölüm metni + Ek 1 + Ek 2 + Ek 4 içeren `04_taslak/04_taslak_<zaman>.html`. Akış 5 `05_analiz/05_plan_uyumu_<zaman>.html` ve bağlam + Ek 1–4 içeren `05_analiz/05_analiz_<zaman>.html`.
- **Zaman soneki:** Üreticiler varsayılan olarak `_YYYYMMDD-HHMMSS` soneki ekler; aynı saniye içinde ikinci çıktı `-01`, `-02` alır. Sabit ad için `--no-timestamp` kullanılır. Ajanın elle yazdığı JSON veri dosyaları da zaman soneki alır.
- **Tek sürüm kuralı:** Üreticiler içerik değişmediyse yeni sürüm yazmaz; `Değişiklik yok; mevcut sürüm korundu` der. İçerik değiştiyse yeni sürümü yazar ve önceki sürümleri `<akış>/arsiv/` altına taşır. Böylece klasörde her zaman tek güncel çıktı kalır, geçmiş kaybolmaz. JSON karşılaştırmasında `generated_at`, `timestamp` gibi değişken alanlar yok sayılır.
- **Silme yasağı:** Üreticiler önceki çıktıları **silmez**; eskiler `arsiv/` altına taşınır. Sabit adlı çıktı `--no-timestamp` ile farklı içerikle yazılacaksa `--force` gerekir. Tek silme yolu, kullanıcının açıkça çağırdığı `chapter-report cleanup` komutudur (manifest tabanlı). “Eski sürümü sil / yerine yaz” istenmedikçe hiçbir dosya kaldırılmaz.
- **DOI bağlantıları:** Fulltext listesi HTML'inde tıklanabilir DOI düğmesi, tıklanabilir yayıncı düğmesi ve düz metin DOI açık adresi bulunur; DOI kopyalama düğmesi yoktur. Chapter-report HTML'lerinde DOI kopyalama düğmesi bulunur; bu amaçla tek bir denetimli gömülü betik izinlidir; başka `<script>`, `<iframe>` veya `on*` olay özniteliği kullanılamaz.
- **Arama kapsamı:** `search_all`, `search_literature` ve `deep_research` cevapları `coverage` (kaynak bazında `returned`, `unique_dois`, `high_quality`; toplam tekil DOI; `evidence_scarcity`; `query_variants`; zaman) ve her sonuçta `score` alanı taşır. Akış 3'te bu blok `scripts/build_search_coverage.py` ile `03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>.json/html` olarak yazılır.
- **PaperQA kaynakları:** `output_directory` proje köküdür. Akış 4 PDF'leri `04_taslak/fulltext/`, akış 5 PDF'leri `05_analiz/fulltext/` altındadır. Her akış ayrı proje adı, manifest ve indeks kullanır; bunlar `<proje-kökü>/.literature-mcp/` altında tutulur.

- **Dil:** Teslim Türkçedir. İngilizce kaynak cümlesi özgün hâliyle verilir; Türkçesi ayrı alanda bulunur.
- **DOI:** Yalnızca `https://doi.org/<doi>` biçimi. DOI metni ayrıca `doi` alanında saklanır.
- **Yerel yol yasağı:** HTML/Markdown/CSV/JSON teslimlerinde `file://`, `/home/...`, `C:\...` veya PDF dosya adı linki bulunmaz. PDF'ler yalnızca kaynak kimliği (DOI) ile anılır.
- **Kodlama:** CSV UTF-8 BOM'lu (`utf-8-sig`); JSON UTF-8; HTML `<meta charset="utf-8">`.
- **Tarih:** ISO 8601 (`2026-10-20`) veya ISO 8601 saatli (`2026-10-20T14:30:00+03:00`).
- **Sayfa:** 1 tabanlı PDF sayfa numarası. Aralık `page_start`–`page_end` olarak verilir.
- **Alıntı:** Kısa tutulur (genellikle 1–3 cümle); telif hakkı ve bağlam korunur.
- **Kırmızı:** Yeniden düzenlenen cümle. İlk taslakta olmayan anlamlı MCP eklemeleri mavi/yeşil gösterilir. Paragrafın tamamı, başlık, kaynakça veya tablo kırmızıya boyanmaz.

## Dosya adları

Proje kökü `paperqa_create_workspace` tarafından başlatılır. İş akışları
`01_konu_belirleme/`, `02_yazim_plani/`, `03_kaynak_kesfi/`, `04_taslak/`,
`05_analiz/` altına yazılır;
PDF'ler ilgili akışın `fulltext/` altındadır; çıktılar doğrudan akış klasörüne yazılır (`taslak/` alt klasörü kaldırıldı). Akış 4 ve 5'in manifesti ve
indeksi `.literature-mcp/` altında birbirinden ayrı tutulur.

Her akışın ana ve ek çıktıları ilgili alt klasörde tutulur. Yeni proje
kaydında `output_directory` kullanıcı tarafından seçilen proje köküdür.
Aşağıdaki tabloda `<zaman>`, `_YYYYMMDD-HHMMSS` sonekini temsil eder.
Üreticiler bu soneki varsayılan olarak ekler; `--no-timestamp` sabit ad
verir. Ajanın elle yazdığı JSON da zaman soneki almalıdır.

| Dosya | Biçim | Kime | İçerik |
|---|---|---|---|
| `01_konu_belirleme/01_konu_<zaman>.json` | JSON | Ajan | Tür (`genre`), hedef kelime, kapsam içi/dışı, hedef kitle, başlık önerileri, seçilen başlık ve tarama kaydı |
| `01_konu_belirleme/01_konu_<zaman>.html` | HTML | İnsan | Önerileri ve arama kapsamını gösteren çevrimdışı rapor |
| `01_konu_belirleme/01_yontem_tasarimi_<zaman>.json` | JSON | Ajan | Yalnızca `ampirik_makale` seçildiyse: desen, örneklem, ölçüm, analiz, etik |
| `01_konu_belirleme/01_yontem_tasarimi_<zaman>.html` | HTML | İnsan | Aynı tasarımın karar noktaları ve sınırlılıkları |
| `02_yazim_plani/01_yazim_plani_<zaman>.json` | JSON | Ajan | Alt başlık iskeleti, amaç, hedef kelime, kanıt ihtiyacı, `plan_status` |
| `02_yazim_plani/01_yazim_plani_<zaman>.html` | HTML | İnsan | Her alt başlık için kart: amaç, kelime, kanıt türü, atanmış kaynak, boşluk |
| `03_kaynak_kesfi/00_atama_matrisi_<zaman>.json` | JSON | Ajan | Alt başlık → DOI ataması, eşleşme skoru, karşılanmayan kanıt ihtiyaçları |
| `03_kaynak_kesfi/00_atama_matrisi_<zaman>.html` | HTML | İnsan | Atama tablosu; boşluk işaretli alt başlıklar |
| `03_kaynak_kesfi/00_kaynak_listeleri_<zaman>.html` | HTML | İnsan | Aynı klasördeki kaynak listelerine giriş sayfası |
| `03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json` | JSON | Ajan | `schemas/fulltext-list.schema.json` uyumlu aday listesi |
| `03_kaynak_kesfi/01_fulltext_listesi_<zaman>.html` | HTML | İnsan | DOI/yayıncı düğmeleri, kısa düz `doi`, gerekçe, kalite skoru, otomatik işaretlenen indirildi kutuları |
| `03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>.json/html/md` | JSON+HTML+MD | Ajan + insan | Kaynak kapsamı, `coverage`, `evidence_scarcity`, seçilenler |
| `03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>_karsilastirma.json/html` | JSON+HTML | Ajan + insan | İki query setinin kapsam farkı |
| `03_kaynak_kesfi/oa_indirme_raporu_<zaman>.json` | JSON | Ajan | Açık erişim indirme özeti; e-posta maskelenir |
| `04_taslak/04_taslak_<zaman>.json` | JSON | Ajan | Taslak metin + Ek 1/2/4 için chapter-report girdisi |
| `04_taslak/04_taslak_<zaman>.md` | Markdown | İnsan + ajan | Taslağın düzenlenebilir sürümü |
| `04_taslak/04_taslak_<zaman>.html` | HTML | İnsan | Taslak metni + Ek 1 + iddia–kanıt matrisi + Ek 4 |
| `04_taslak/04_taslak_<zaman>.manifest.json` | JSON | Ajan | Üretilen dosyaların temizlik manifesti |
| `04_taslak/fulltext_aktarim_<zaman>.json` | JSON | Ajan | Akış 3 → 4 PDF aktarım raporu |
| `05_analiz/05_plan_uyumu_<zaman>.json/html` | JSON+HTML | Ajan + insan | Plan uyumu: yazılmayan başlık, kelime sapması, plansız bölüm, kullanılmayan atama |
| `05_analiz/05_analiz_<zaman>.html` | HTML | İnsan | **Altın standart:** düzeltilmiş metin + bağlam + Ek 1–4 |
| `05_analiz/05_analiz_<zaman>.md` | Markdown | İnsan + ajan | Aynı raporun düzenlenebilir eşlik dosyası |
| `05_analiz/05_analiz_<zaman>.manifest.json` | JSON | Ajan | Üretilen dosyaların hash'li temizlik manifesti |

Birden çok araştırmanın listeleri aynı `03_kaynak_kesfi/` klasöründe tutulur; ayrı araştırma kök klasörlerine dağıtılmaz. Her dosya adı sıra numarası ve araştırma kısa adını içerir. `scripts/build_fulltext_index.py` tüm liste çiftlerinden `00_kaynak_listeleri_<zaman>.html` üretir. Aynı ada sahip dosya varsa üzerine yazmadan önce kullanıcıya sor.

## 01 — Konu belirleme

Şema: [`../schemas/topic-discovery.schema.json`](../schemas/topic-discovery.schema.json).
Varsayılan veri tabanları OpenAlex, PubMed, Europe PMC ve Crossref'tir. JSON,
her veri tabanı için sorgu, durum, bulunan kayıt sayısı ve varsa uyarıyı;
her öneri için başlık, araştırma sorusu, genel/özel amaçlar, hedef grup,
önerilen desen, olası boşluk türü, en yakın çalışmalar, yapılabilirlik ve
sıralama gerekçesini taşır. `novelty_signal` yalnızca ön taramada görülen
boşluk sinyalini belirtir; kesin özgünlük iddiası değildir.

Akış 1 ayrıca ürün sözleşmesini sabitler: `genre` (`kitap_bolumu`,
`uygulama_rehberi`, `derleme_makale`, `ampirik_makale`), `target_total_words`,
`audience`, `scope_in`, `scope_out` ve seçim sonrası `selected_title`.
`genre` ve `target_total_words` olmadan üretici doğrulama hatası verir; bu
alanlar doldurulmadan akış 2 başlamaz.

`scripts/build_topic_discovery.py`, JSON'u tek dosyalık çevrimdışı HTML'e
çevirir. Arama başarısızlıkları ve kapsam dışı kalabilecek alan-özel veri
tabanları raporda görünür olmalıdır.

Kullanıcı bir başlık seçtikten sonra yöntem/tasarım dosyaları
[`../schemas/study-design.schema.json`](../schemas/study-design.schema.json)
şemasına uyar. `scripts/build_study_design.py` tasarım JSON'unu çevrimdışı
HTML'e çevirir. Kullanıcı/araştırma ekibi onayına kadar `design_status`
`proposed` kalır.

## 02 — Yazım planı

Şema: [`../schemas/writing-plan.schema.json`](../schemas/writing-plan.schema.json).
Girdi, akış 1'de onaylanmış başlık + tür + hedef kelime sayısıdır. Çıktı
`02_yazim_plani/01_yazim_plani_<zaman>.json` ve `.html` dosyalarıdır.

Her alt başlık kaydı şunları taşır:

| Alan | Zorunlu | Açıklama |
|---|---|---|
| `id` | evet | `S1`, `S2`, ... |
| `heading` | evet | Alt başlık metni |
| `purpose` | evet | Bu alt başlığın savunacağı tek işlev |
| `target_words` | evet | Hedef kelime (en az 50) |
| `evidence_needs` | evet | `design` + `min_count` listesi |
| `assigned_dois` | hayır | Akış 3 doldurur |
| `gap_note` | hayır | Karşılanamayan kanıt ihtiyacının gerekçesi |
| `status` | hayır | `planned`, `covered`, `gap` |

Kabul edilen tasarım kodları: `systematic_review`, `meta_analysis`, `rct`,
`quasi_experimental`, `cohort`, `cross_sectional`, `qualitative`,
`policy_document`, `any`. `target_words` toplamı `target_total_words`'a
±%10 içinde olmalıdır.

HTML'de her alt başlık bir karttır: amaç, hedef kelime, gereken kanıt türü,
atanmış kaynaklar ve varsa boşluk notu. `plan_status` kullanıcı onayına kadar
`draft` kalır; `approved` olmadan akış 3 başlamaz.

```bash
python3 scripts/build_writing_plan.py plan.json \
  -o <proje-kökü>/02_yazim_plani/01_yazim_plani.html
python3 scripts/build_writing_plan.py plan.json --check
```

## 03 — Kaynak keşfi ve fulltext listesi

### HTML yapısı

1. **Başlık:** proje adı, bölüm başlığı, arama sorusu, oluşturma tarihi.
2. **Özet kartları:** toplam kaynak, açık erişim, Q1, indirilen, kalan.
3. **Araç çubuğu:** metin filtresi, yazdır/PDF, işaretleri temizle.
4. **Tablo:** her satırda:
   - indirildi kutusu
   - öncelik (A/B/C)
   - yazar, yıl, başlık, kısa gerekçe
   - dergi, Q
   - atıf sayısı
   - erişim (açık erişim / kurum erişimi)
   - DOI düğmesi, düz metin DOI açık adresi, yayıncı düğmesi, varsa OA PDF açık adresi
5. **Alt bilgi:** DOI/yayıncı düğmeleri ile OA PDF açık adreslerinin davranışı; açık erişimli PDF'lerin `scripts/download_open_access.py` ile indirilebileceği; kapalı erişimlilerin kullanıcı hesabından indirildiği.

Tek dosya olmalı; harici CSS/JS/font kullanılmaz. Gömülü betik yalnızca
filtre, yazdırma ve "indirildi" durumu içindir; DOI kopyalama betiği
fulltext listesinde yoktur. `@media print`
ile yazdırma düzeni bozulmamalı. "İndirildi" durumu `localStorage` ile
saklanır; tarayıcı desteklemiyorsa sessizce devam eder. PDF'i `fulltext/`
klasörlerinde bulunan kaynaklar sayfa açılışında otomatik işaretlenir ve
"işaretleri temizle" bu işaretleri korur.

### Arama kapsamı ve skor

`search_all`, `search_literature` ve `deep_research` her sonuca bir `score`
ekler: 0.35 anlamsal alaka + 0.25 `log10(atıf+1)/4` + 0.15 güncellik +
0.15 SCImago quartile + 0.10 çalışma türü. Preprint (arXiv) kayıtları
`is_preprint=true` alır ve skoru 0.85 ile çarpılır. Yüksek kalite eşiği
0.60'tır ve çalışma türü bileşeni en az 0.40 olmalıdır.

`coverage` bloğu şu alanları taşır: `sources_queried`, `per_source`
(`returned`, `unique_dois`, `high_quality`, `status`, `note`,
`requested_limit`, `duration_ms`), `skipped_sources`, `warnings`,
`total_unique_dois`, `high_quality_total`, `evidence_scarcity`,
`evidence_scarcity_message`, `closest_studies`, `publisher_distribution`,
`query_expansion`, `evidence_density`, `query_variants`, `timestamp`.
Yüksek kaliteli sonuç sayısı 5'in altındaysa `evidence_scarcity=true` olur;
mesaj en yakın 5 çalışmayı DOI ve yılıyla listeler ve “Araştırma boşluğu
olasılığı yüksektir” uyarısını ekler. `query_expansion` orijinal sorguyu,
genişletilmiş sorguları, MeSH terimlerini, dil dönüşümünü ve notları;
`evidence_density` Q1, son 5 yıl, RCT / sistematik derleme / meta-analiz,
klinik çalışma ve preprint sayılarını, katı yüksek-kalite sayısını(`high_quality_strict_total`: Q1/Q2 + en az 10 atıf + RCT/SR/MA) ve son 3 yıl
`trend` sinyalini taşır. `publisher_distribution`
platform dağılımını ve açık erişim/preprint/PDF oranlarını; `warnings` ile
`skipped_sources` ise hata, hız limiti ve sorgulanmayan kaynakları görünür
kılar. Blok, akış 3'te
`scripts/build_search_coverage.py` ile JSON + HTML + Markdown raporuna
dönüştürülür. `--compare` iki query setinin kapsam farkını üretir.
Şema: [`../schemas/search-coverage.schema.json`](../schemas/search-coverage.schema.json).
`--fulltext-list <json>` verildiğinde rapor seçilmiş DOI'leri bilir ve normal
sonuç tablosunda sıra numarasının yanına yeşil `seçildi` etiketi koyar. Ayrı
bir "seçilen makaleler" tablosu üretilmez.

### Açık erişim PDF indirme

`scripts/download_open_access.py <liste.json>` Unpaywall'ı (önce) ve
OpenAlex'i (yedek) sorgular. Yalnızca herkese açık `http(s)` PDF bağlantıları
denenir; ödeme duvarı veya erişim kontrolü aşılmaz. Varsayılan hedef otomatik
oluşturulan `03_kaynak_kesfi/fulltext/` klasörüdür; `--workflow 4` ile
`04_taslak/fulltext/`, `--workflow 5` ile
`05_analiz/fulltext/` seçilir. İndirme raporu her akışta doğrudan o akışın
klasörüne `oa_indirme_raporu_<zaman>.json` olarak yazılır; e-posta maskelenir.
`--dry-run` yalnızca OA durumunu bildirir, `--update-json` kaynak listesine
`oa_pdf_url`, `oa_source`, `oa_license`, `oa_checked_at`, `oa_downloaded` ve
`oa_local_file` alanlarını ekler.
Unpaywall için `setup.txt` içindeki `email` zorunludur.

### JSON alanları

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `project` | string | evet | Proje adı |
| `title` | string | evet | Bölüm/liste başlığı |
| `query` | string | evet | Arama sorusu |
| `generated_at` | string | hayır | Tarih |
| `target_count` | integer | hayır | Hedef kaynak sayısı |
| `notes` | string | hayır | Seçim ölçütleri, dışlananlar |
| `candidates` | array | evet | Aday kayıtlar |

Aday alanları:

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `doi` | string | evet | `10.` ile başlar |
| `title` | string | evet | Makale başlığı |
| `authors` | string | evet | `Yazar, A.; Yazar, B.` |
| `year` | integer | evet | Yayın yılı |
| `journal` | string | evet | Dergi adı |
| `quartile` | enum | hayır | `Q1`–`Q4`, `-` |
| `citations` | integer/null | hayır | Atıf sayısı |
| `open_access` | boolean | hayır | Açık erişim |
| `publisher` | enum | evet | Beş platform veya `Diğer` |
| `publisher_url` | string/null | hayır | Yayıncı sayfası |
| `oa_pdf_url` | string/null | hayır | OA PDF |
| `oa_downloaded` | boolean | hayır | PDF `fulltext/` klasörüne indirildiyse `true` |
| `oa_local_file` | string | hayır | İndirilen PDF'in dosya adı (yol değil) |
| `oa_source` | string/null | hayır | Unpaywall/OpenAlex |
| `oa_license` | string/null | hayır | Lisans bilgisi |
| `oa_host_type` | string/null | hayır | Yayıncı/arşiv türü |
| `oa_checked_at` | string | hayır | OA kontrol zamanı |
| `priority` | enum | evet | `A`, `B`, `C` |
| `access` | string | hayır | `Açık erişim`, `Kurum erişimi`, `Erişim yok` |
| `rationale` | string | evet | Neden seçildi |
| `project_relevance` | string | evet | Bu çalışmada hangi bölüm/amaç için kullanılabileceği |
| `supports` | string[] | evet | Tam metin/özet/metaveri dayanağının destekleyebileceği önermeler |
| `does_not_support` | string[] | evet | Kaynaktan çıkarılamayacak sonuçlar |
| `limits` | string[] | evet | Tasarım, örneklem ve kapsam sınırlılıkları |
| `assessment_basis` | enum | evet | `metadata`, `abstract`, `fulltext`, `fulltext_pages`; PDF kanıtı sayfa doğrulaması gerektirir |

Şema: [`../schemas/fulltext-list.schema.json`](../schemas/fulltext-list.schema.json).

## 04 — Taslak ve düzeltme kartları

### CSV sütunları

| Sütun | Açıklama |
|---|---|
| `id` | `D1`, `D2`, ... |
| `location` | Bölüm/paragraf/cümle |
| `author_sentence` | Yazarın özgün cümlesi |
| `source_sentence` | PDF'ten birebir alıntı |
| `source_translation` | Kaynak cümlesinin Türkçesi |
| `source_doi` | DOI |
| `source_page` | Sayfa numarası |
| `rewritten_sentence` | Paragrafta doğrudan kullanılabilecek, bağlama uygun yeniden yazım; kanıt boşluğunu açıklayan denetçi notu değil |
| `note` | Gerekçe, sınırlılık, dikkat |
| `evidence_status` | `supported`, `partially_supported`, `contradicted`, `not_found` |

### JSON alanları

`schemas/change-card.schema.json` ile aynı. Ek alanlar:

- `source_quote_original`: çok dilli kaynaklarda özgün metin (opsiyonel)
- `source_url`: yalnızca `https://doi.org/...`
- `reviewer_note`: insan denetçi notu (opsiyonel)

### HTML kart düzeni

Her kart:

```text
D1 · Giriş, 2. paragraf
Yazar cümlesi: ...
Kaynak cümlesi (s. 4): "..."
Türkçesi: ...
Yeniden yazılan cümle: ...        ← kırmızı
Not: ...
Durum: supported
```

`rewritten_sentence` kırmızıyla işaretlenir. İlk taslakta bulunmayan ve anlam taşıyan eklemeler `rewritten_segments[].added_by_mcp=true` ile mavi/yeşil gösterilir. Tam metin `intro.paragraphs[].segments` içinde de aynı eklemeler işaretlenir. Renk lejantı zorunludur. Kaynak cümlesi ve çevirisi normal renkte kalır. Salt dilbilgisi/parafraz farkları yeni bilgi eklemesi sayılmaz.

## 05 — Analiz raporu

Akış 5 iki denetimi birleştirir: plan uyumu (`05_plan_uyumu_<zaman>.json/html`)
ve kanıt denetimi. Plan uyumu raporu yazılmayan alt başlıkları, ±%25 kelime
sapmasını, planda olmayan bölümleri ve kullanılmayan atamaları gösterir.
Kanıt denetimi aşağıdaki üç çıktıyı üretir.

### Kaynak denetimi (Ek 2)

#### CSV sütunları

| Sütun | Açıklama |
|---|---|
| `no` | Sıra |
| `doi` | DOI |
| `authors_year` | `Yazar (Yıl)` |
| `title` | Başlık |
| `journal` | Dergi |
| `publisher` | Yayıncı/platform |
| `quartile` | Q1–Q4 / `-` |
| `citations` | Atıf sayısı |
| `open_access` | `evet` / `hayır` |
| `access_note` | Erişim notu |
| `role` | `çekirdek`, `destek`, `bağlam`, `dışla` |
| `limitation` | Sınırlılık |
| `verified` | `evet` / `hayır` |

#### Kurallar

- Her DOI `verify_doi_and_publisher` ile doğrulanır.
- `project_audit`/`journal_rank` çıktısı yoksa `-` yazılır; uydurma yapılmaz.
- `role` kararı gerekçelendirilir; "iyi görünüyor" gibi gerekçesiz karar verilmez.
- Aynı DOI birden çok kez listelenmez.

### İddia–kanıt matrisi

#### CSV sütunları

| Sütun | Açıklama |
|---|---|
| `claim_id` | `C1`, `C2`, ... |
| `claim` | İddia |
| `source_doi` | Kaynak DOI |
| `source_page` | Sayfa |
| `evidence_quote` | Kısa alıntı |
| `evidence_translation` | Türkçesi |
| `support` | `full`, `partial`, `none`, `contradicts` |
| `strength` | `strong`, `moderate`, `weak` |
| `decision` | `keep`, `revise`, `delete`, `add_source` |
| `note` | Not |

#### Kurallar

- Her satırda en az bir DOI ve sayfa bulunur; `none`/`not_found` istisnadır ve açıkça yazılır.
- `support=full` için alıntı iddiayı doğrudan desteklemelidir; yakın konu yeterli değildir.
- `contradicts` varsa iddia kararı `revise` veya `delete` olur.
- `strength` yalnızca kanıtın türüne göre verilir; dergi Q'su tek başına `strong` yapmaz.

### Denetim raporu

#### HTML bölümleri

1. Kapak: proje, taslak, tarih, kapsam.
2. Yönetici özeti: kaç kart, kaç kaynak, kaç iddia, kaç `not_found`.
3. Düzeltme kartları (yeniden düzenlenen cümleler kırmızı; anlamlı MCP eklemeleri mavi/yeşil).
4. Ek 2 kaynak denetimi tablosu.
5. İddia–kanıt matrisi.
6. Kaynakça: yalnızca DOI linkleri.
7. Ek: yöntem, arama tarihleri, dışlama ölçütleri.

#### Markdown

Aynı bölümler; tablolar Markdown olarak. HTML'e özel renkler Markdown'da `**değişen cümle**` veya `<mark>` ile belirtilebilir; teslimde kırmızı kuralı HTML için geçerlidir.

#### JSON

Üst düzey anahtarlar:

```json
{
  "schema": 1,
  "project": "...",
  "title": "...",
  "generated_at": "...",
  "summary": {...},
  "change_cards": [...],
  "source_audit": [...],
  "claim_matrix": [...],
  "references": [...]
}
```

### Altın standart analiz raporu

`05_analiz_<zaman>.html` teslimde tercih edilen rapordur; düzeltilmiş metin,
bağlam değerlendirmesi ve Ek 1–4'ü birleştirir. Ara denetim raporu
`05_analiz_<zaman>.json/md` eşlik dosyalarıyla birlikte üretilir. Her iki HTML
de DOI kopyalama düğmesi içerir; chapter-report'ta bu amaçla tek bir denetimli
gömülü betik dışında betik kullanılmaz.

#### Bölümler

1. Düzeltilmiş bölüm metni; yeniden düzenlenen ifadeler kırmızı, MCP'nin
   eklediği anlamlı ifadeler mavi/yeşil.
2. Ek 1 — değişiklik kartları: yazar cümlesi, kaynak cümlesi (İngilizce),
   Türkçe çeviri, yeniden yazılan cümle, “ne değişti / neden” notu ve durum
   rozeti.
3. Ek 2 — kaynak envanteri (rol + sınırlılık sütunları), konum + kanıt türü +
   not sütunlu iddia–kanıt matrisi, düzeltme özeti, sınırlılıklar ve opsiyonel
   sonraki adımlar.
4. İş akışı 5 için bağlam değerlendirmesi: paragraf işlevi, cümle/paragraf
   uyumu, geçişler ve makale/bölüm bağlamı.
5. **Ek 3 — Bağlama uygun kaynak önerileri:** ilgili iddia/konum, doğrulanmış
   DOI/metaveri ve uygunluk gerekçesi. Tam metni incelenmeyen adaylar kanıt
   olarak sunulmaz; öneri yoksa nedeni yazılır.
6. **Ek 4 — Bu çalışmada kaynakların katkısı ve sınırları:** her DOI için
   proje ile ilgisi, neyi desteklediği/neye dayanak olmadığı, sınırlılıklar ve
   değerlendirme temeli (metadata/abstract/fulltext/fulltext_pages).
7. Opsiyonel kaynakça; yalnızca DOI linkleri.
8. Opsiyonel kaynak politikası kutusu (`notice`) ve footer.

### JSON alanları

Şema: [`../schemas/chapter-report.schema.json`](../schemas/chapter-report.schema.json).
Üst düzey anahtarlar:

```json
{
  "schema": 2,
  "project": "...",
  "title": "...",
  "generated_at": "...",
  "summary": {"change_cards": 3, "sources": 3, "claims": 4, "not_found": 1},
  "notice": {"title": "Kaynak politikası", "text": "..."},
  "intro": {"heading": "...", "paragraphs": [...]},
  "change_cards": [...],
  "source_audit": [...],
  "claim_matrix": [...],
  "context_review": {...},
  "source_recommendations": [...],
  "source_recommendations_note": "...",
  "source_contributions": [...],
  "correction_summary": [...],
  "limitations": [...],
  "next_steps": [...],
  "references": [...]
}
```

`claim_matrix` kayıtları `location` (`P1 · c2`), `evidence_type` (kesitsel,
meta-analiz, amaç beyanı vb.) ve `note` alanlarını taşır. Bu alanlar kalite
kapısında öneri olarak denetlenir; `--strict` ile zorunlu olur.

### Üretim ve kalite kapısı

```bash
# Varsayılan: _YYYYMMDD-HHMMSS sonekli çıktı
chapter-report build rapor.json -o 05_analiz.html --check
chapter-report build rapor.json -o 05_analiz.html \
  --markdown 05_analiz.md

# Sabit ad gerekiyorsa
chapter-report build rapor.json -o 05_analiz.html \
  --markdown 05_analiz.md --no-timestamp --force
```

Zorunlu alanlar, DOI biçimi, sayfa/kanıt, yerel yol yasağı, HTML dengesi ve
izin verilen tek DOI kopyalama betiği denetlenir. Ayrıntılar:
[`report-standard.md`](report-standard.md).

### Temizlik

`05_analiz_<zaman>.manifest.json` yalnızca üretilen dosyaları listeler.
Analiz sonunda:

```bash
chapter-report cleanup --manifest 05_analiz_<zaman>.manifest.json \
  --scope intermediate --yes
```

`intermediate` HTML ve Markdown'ı korur; `all` ikisini de siler; manifest kalır.
PDF, indeks ve registry dosyaları manifest dışında olduğu için silinmez.

## Kalite kontrol

- [ ] Tüm DOI'ler `https://doi.org/...` biçiminde.
- [ ] Yerel PDF yolu / `file://` yok.
- [ ] Her alıntıda DOI + sayfa var.
- [ ] Yeniden düzenlenen cümleler kırmızı; ilk taslakta olmayan anlamlı MCP eklemeleri mavi/yeşil ve lejantlı.
- [ ] `paperqa_ask` çıktısı kanıt olarak kullanılmadı.
- [ ] CSV UTF-8 BOM'lu, başlıklar doğru.
- [ ] JSON şemaya uyuyor.
- [ ] Proje izolasyonu korundu.
- [ ] Eski proje dosyaları değişmedi.
- [ ] Üretilen dosya adları `_YYYYMMDD-HHMMSS` soneki içeriyor; önceki çıktı ezilmedi.
- [ ] Kaynak listesi HTML'inde tıklanabilir DOI/yayıncı düğmeleri ve düz metin DOI açık adresi var; DOI kopyalama düğmesi yok.
- [ ] Bölüm raporu HTML'lerinde DOI kopyalama düğmesi var; chapter-report'ta başka betik yok.
- [ ] Arama cevabındaki `coverage` ve `evidence_scarcity` incelendi; `01_arama_kapsam_raporu_<zaman>.json/html` yazıldı.
- [ ] Ürün türü ve hedef kelime sayısı soruldu; yazım planı onaylandı (`plan_status: approved`).
- [ ] Atama matrisi üretildi; karşılanmayan `min_count` için boşluk gerekçesi yazıldı.
- [ ] Açık erişim PDF'leri yalnızca herkese açık bağlantılardan ve yalnızca atanmış DOI'ler için indirildi; hedef `03_kaynak_kesfi/fulltext/`, rapor aynı klasörde.
- [ ] Plan uyumu raporu `05_analiz/05_plan_uyumu_<zaman>.html` üretildi ve sapmalar açıklandı.
- [ ] `05_analiz_<zaman>.html` kalite kapısından 0 hatayla geçti.
- [ ] Temizlik yalnızca manifestteki dosyalara uygulandı.
