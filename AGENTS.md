# AGENTS.md — Literatür Projesi Ajan Sözleşmesi

Bu dosya, bu projede çalışan yapay zekâ ajanları için **bağlayıcı** kuralları ve araç politikasını tanımlar. İnsanlar için giriş noktası [`README.md`](README.md) dosyasıdır.

## 1. Görev tanımı

Her yeni proje kullanıcı proje kökünü verince başlar; önce `<proje-kökü>/setup.txt` dosyasını kontrol et (kural 15), sonra `paperqa_create_workspace` beş akış klasörünü açar. Ardından kullanıcıya **1–5 arasındaki iş akışlarından** hangisini istediğini sor. Seçim gelmeden arama veya PDF işleme yapma.

```text
1. Konu belirleme        → 01_konu_belirleme
2. Yazım planı           → 02_yazim_plani
3. Kaynak keşfi + seçim  → 03_kaynak_kesfi
4. Taslak yazma          → 04_taslak
5. Taslak analizi        → 05_analiz
```

**Zincir kuralı:** plan onayı yoksa kaynak indirilmez; atama yoksa taslak yazılmaz; analiz yapılmadan teslim edilmez. Beş akışın detayı [`docs/workflows.md`](docs/workflows.md) dosyasındadır.

### İş akışı 1 — Konu belirleme

1. Kullanıcının konu çerçevesini, hedef grubu/bağlamı, ilgili sonuçları ve uygulanabilirlik kısıtlarını netleştir.
2. **Ürün türünü sor** (varsayılan yok): `kitap_bolumu`, `uygulama_rehberi`, `derleme_makale`, `ampirik_makale`. Aynı adımda `target_total_words` al. Tür ve uzunluk sabitlenmeden akış 2'ye geçme.
2b. **Kavram haritasını kur (zorunlu).** Başlığı doğrudan aramaya verme; önce
   kavram haritasına çevir. Türkçe başlık İngilizce veritabanlarıyla eşleşmez;
   `--query-en` ile İngilizce karşılığını ver:

```bash
python3 scripts/build_concept_map.py <proje-kökü> --phase 1 \
  --query-en "..." --domain education
```

   `candidates` tablosu başlık+özet metninden çıkarılan adaylardır ve genel
   alana göre ayırt edicilikle sıralanır. **Aday doğru kavram değildir,
   hipotezdir.** Her adayı sorgu olarak çalıştır; bölümün asıl konusunu getiren
   terimi anchor seç. Doğrulanmış listeyi `00_kavram_tohumu.json` olarak yaz ve
   `--concept-seed` ile yeniden üret.

   MeSH yalnızca `--domain medical` veya `psychology` projelerde `--mesh` ile
   uygulanır. Eğitim alanyazını PubMed'de indekslenmez; aynı terim orada başka
   bir alanın terimi olabilir. Tıp/psikoloji projesinde tohum dosyasına
   `context_terms` yaz (projenin doğrulanmış İngilizce bağlam terimleri); MeSH projeksiyonu
   bu bağlama daraltılır. Bağlam verilmezse terim başka alanın MeSH'ini getirir.

   **Kaynaklı çerçeve:** `framework` alanında kapsam boyutları, kaynak
   kimliği/pasajı, tanımlar ve arama planı bulunur. Ajan başlığı kavramsal
   boyutlara ayırıp `concept-seed` dosyasına yazar; kod kendi başına dil modeli
   çağırmaz veya Türkçe başlığı çevirmez. Model önerisi `proposed` kalır.
   `mesh_entries` NLM RDF sözlüğündeki tam etiket eşleşmesidir;
   `related_mesh` PubMed birlikte-görülmesidir, eş anlamlı sayılmaz.
   Tıp/psikolojide aday keşfinin varsayılanı PubMed'dir; diğer kaynak için
   `--discovery-source openalex` verilir. Scholar bağlantıları `not_run`
   durumundadır; sonuç toplanmış gibi raporlanmaz. Ayrıntı:
   [`docs/concept-framework.md`](docs/concept-framework.md).

3. Varsayılan olarak **yedi kaynağın tümünde** tara: OpenAlex, Semantic Scholar, PubMed, Europe PMC, Crossref, arXiv ve ClinicalTrials.gov. `search_literature` / `search_all` / `deep_research` çağrılarında `sources` vermezsen hepsi sorgulanır; `priority_only=false` varsayılandır, böylece tüm yayıncılar döner. Yalnızca belirli bir alt küme gerekiyorsa `sources=[...]` ile daralt ve `coverage.per_source.status` alanında her kaynağın `ok`/`error`/`rate_limited` olduğunu kontrol et.
4. Her sorgu ve her veritabanı için `sources_status`, `coverage`, kayıt sayısı ve hata/not bilgisini kaydet. Aranmayan veya başarısız kaynağı başarılı gibi işaretleme. `evidence_scarcity=true` ise kullanıcıya söyle.
5. En yakın bulunan yayınlara ve kapsanmayan bağlam/örneklem/yöntem/sonuçlara dayalı sıralı başlık, araştırma sorusu, genel/özel amaç, kapsam içi/dışı ve gerekçe ver. Mutlak özgünlük iddiasında bulunma.
6. `schemas/topic-discovery.schema.json` uyumlu JSON'u ve HTML'i `01_konu_belirleme/01_konu_<zaman>.json/html` olarak yaz. Şu alanları mutlaka doldur: `genre`, `target_total_words`, `scope_in`, `scope_out`, `audience`, `selected_title`.
7. `ampirik_makale` seçildiyse varsayımları açıkça belirterek `schemas/study-design.schema.json` uyumlu yöntem/tasarım JSON'u ve HTML'i üret (`01_konu_belirleme/01_yontem_tasarimi_<zaman>.json/html`). Kullanıcı onaylamadan `design_status` değerini `proposed` durumundan çıkarma.
8. **Kapı:** kullanıcı başlığı ve türü onaylamadan akış 2 başlamaz.

### İş akışı 2 — Yazım planı (iskelet)

1. Onaylanmış tür ve hedef uzunluğa göre alt başlık iskeletini kur. Her alt başlık için `id` (`S1`…), `heading`, `purpose`, `target_words`, `evidence_needs` belirle.
2. `evidence_needs` için kabul edilen tasarım kodları: `systematic_review`, `meta_analysis`, `rct`, `quasi_experimental`, `cohort`, `cross_sectional`, `qualitative`, `policy_document`, `any`. Her ihtiyaç için `min_count` ver.
3. Kelime bütçesini dengele: `target_words` toplamı `target_total_words`'a ±%10 içinde olmalı.
4. Bu akışta **kaynak seçilmez**. Yalnızca iskeletin gerçekçi olduğunu görmek için hafif tarama yapılabilir; tam fulltext listesi üretilmez.
5. JSON'u `schemas/writing-plan.schema.json` biçiminde `02_yazim_plani/01_yazim_plani_<zaman>.json` olarak yaz; HTML'i üret:

```bash
python3 scripts/build_writing_plan.py <json> -o <proje-kökü>/02_yazim_plani/01_yazim_plani.html
```

6. **Kapı:** kullanıcı iskeleti onaylar (`plan_status: approved`). Onay yoksa akış 3 başlamaz.

7. **Kavram haritasını plana bağla.** Kavramları alt başlıklara bağla ve
   anchor terimsiz bölümleri gör:

```bash
python3 scripts/build_concept_map.py <proje-kökü> --phase 2
```

   `section_coverage` çıktısında `anchor_missing` olan bölüm varsa iskelet
   eksiktir: o bölüm kavramsal çekirdeğe bağlanmamış demektir.

8. **Kavram kapsamı kapısı.** Plan onaylanmadan önce anchor terim zincirini
   doğrula:

```bash
python3 scripts/check_concept_coverage.py <plan.json> --check
```

Her anchor terim `search_terms` içinde olmalı. Eksikse iskelet tamamlanmamıştır;
onaya sunma.

### İş akışı 3 — Plana göre kaynak keşfi ve fulltext seçimi

1. Onaylı plandaki her alt başlık için 2–4 hedefli sorgu üret (Türkçe + İngilizce, eş anlamlı + MeSH). Eş anlamlı/MeSH/dil dönüşümünü `query_expansion` ile açıkça ver.
2. `deep_research` veya `search_literature` ile aday DOI'leri topla; `search_all`, `search_semantic_scholar`, `search_sciencedirect`, `search_pubmed`, `search_europepmc`, `search_arxiv`, `search_clinicaltrials` ile genişlet.
3. Her aday için `get_article` ve `get_links` ile metadata/link al; `verify_doi_and_publisher`, `doi_provenance`, `journal_rank` ile DOI, yayıncı ve quartile doğrula.
4. Atama matrisini üret: alt başlık → DOI. `--update-plan` ile `assigned_dois`/`status`/`gap_note` plana geri yazılır.

```bash
python3 scripts/build_assignment_matrix.py <plan.json> <havuz.json> -o <proje-kökü>/03_kaynak_kesfi --update-plan
```

5. `gap_sections > 0` ise dur ve kullanıcıya sor: kapsam mı daraltılacak, boşluk mu kabul edilecek? Sessizce boş bırakma.
6. `schemas/fulltext-list.schema.json` biçiminde listeyi yaz; `scripts/build_fulltext_list.py` ile HTML üret (tıklanabilir DOI/veritabanı düğmeleri, kısa düz `doi`, "Neden seçildi", "Kalite skoru"; DOI metni kopyalanmaz, ancak "dosya adı" düğmesi tıklanınca düzeltilmiş DOI'yi panoya kopyalar).
7. `scripts/build_search_coverage.py ... --fulltext-list <liste.json> --auto-report` ile kapsam raporunu yaz; `scripts/build_fulltext_index.py <proje-kökü>/03_kaynak_kesfi` ile giriş sayfasını üret.
8. Açık erişimli PDF'leri **yalnızca atanmış DOI'ler için** indir. Varsayılan hedef `03_kaynak_kesfi/fulltext/`; rapor aynı klasörde `oa_indirme_raporu_<zaman>.json`.
9. **Kavram kapsamı (külliyat + seçim).** İndirme sonrası ve atama öncesi:

```bash
python3 scripts/check_concept_coverage.py <plan.json> \
  --project-root <proje-kökü> --workflow 4
```

Üç şeyi denetler: (a) anchor terim `search_terms` içinde mi, (b) indirilen
PDF'lerin en az %15'inde anchor terim geçiyor mu, (c) havuzda anchor terim
içeren kayıt atandı mı veya gerekçesiyle reddedildi mi. Külliyat anchor terimi
taşımıyorsa veya anchor terimli kayıt sessizce atlanmışsa **akış 4 başlamaz**;
akış 3'e dönüp anchor terimle yeni arama yapılır.

10. **Kavram haritasını sorguya çevir ve kapsamı ölç.**

```bash
python3 scripts/build_concept_map.py <proje-kökü> --phase 3
```

    Her kavram için hedefli sorgu üretilir ve havuz/atama/PDF kapsamı ölçülür.
    `missing` kavram hiçbir havuz kaydında geçmiyor demektir: kavram-önce arama
    yapılmalı. `partial` kavram havuzda var ama atanmamış demektir: atama
    matrisine alınmalı.

11. **Kapı:** her alt başlıkta `evidence_needs.min_count` karşılanmadan akış 4 başlamaz.

12. **Eksik kaynak denetimi.** Yayıncıya özel `site:` sorgularından önce
    Scholar'da yayıncıdan bağımsız keşfi planla; yalnızca gerçekten yapılan
    aramaları günlüğe `ok` yaz. `scripts/build_literature_audit.py` ile havuzu
    ek sonuçlar ve bağımsız bilinen yayın listesiyle karşılaştır. Başlık
    eşleşmesi kesin kimlik eşleşmesi değildir. İnceleme önceliği kalite
    puanı değildir; bilinen yayınları bulma oranı literatürün tamamının
    yakalanma oranı değildir. Erişilemeyen/taranmayan veritabanlarını açık
    bırak. [Kullanım](docs/literature-audit.md).

13. **Aramayı model yürütür.** `prepare_platform_search` ile site filtresiz
    ve kaynak alan adına özel görevleri hazırla; host'un bağlı web aracıyla
    gerçekten çalıştır. `collect_platform_results` ile servis, sorgu,
    tarih, kaynak URL'si ve okuma düzeyini koru. Normal web sonuçlarını
    Scholar sonucu diye etiketleme. Başarısız/çalıştırılmamış görevleri açık
    bırak. Önemli yayınları kaçırmamak için keşif aşamasında yayıncı,
    quartile, atıf veya yayın türüyle erken eleme yapma; kaynakça/ileri atıf
    ve bilinen kaynak denetimini tamamla. Cochrane dahil platform listesi
    ve sözleşme: [model araması](docs/model-platform-search.md).

14. **Hız değil kapsam.** Aynı sağlayıcıda sıralı, bağımsız sağlayıcılarda
    en fazla iki paralel arama yürüt. Farklı site: hedefleri aynı web
    sağlayıcısının kotasını paylaşır. Üç sorguluk partilerden sonra gerçek
    sonuçları ve checkpoint'i proje klasörüne kaydet. Retry-After süresini
    kısaltma; beklerken bağımsız kaynakta ilerle. Süre dolduğu için kaynak
    tamamlanmış sayılmaz. HTML'lerde durum, kayıt sayıları, hata, yeniden
    deneme ve kalan görevleri göster; eksik sayıları uydurma.

### İş akışı 4 — Taslak yazma

0. **Zorunlu tam okuma kapısı.** Önce atanmış PDF'leri hedef akışın fulltext
   klasörüne aktar (`paperqa_promote_fulltext` / `promote_fulltext.py`).
   `scripts/fulltext_reading.py` ile hedef
   akışın bütün PDF sayfalarını hazırla. Model metinleri ve gerekli sayfa
   görsellerini gerçekten inceleyip her sayfaya özet, terim ve bölüm ilişkisi
   yazar; `review` ile kaydeder. Sonra `check --fulltext-dir ... --workflow 4`
   ve okuma raporu ekli `build_evidence_gap_request.py --preflight` başarılı
   olmalı. Çıkarma/indeksleme veya hash kopyalama okuma değildir.
   Eksik sayfa, değişen PDF/küme veya plan boşluğu varsa taslak başlamaz.
   Yeni terimler ve ek makale ihtiyaçları akış 3'e geri beslenir.
   [Sözleşme](docs/fulltext-reading.md).

1. **Önce oku, sonra yaz.** Taslağa başlamadan önce atanmış fulltext'lerin tamamını oku:

```bash
python3 scripts/build_evidence_bank.py <proje-kökü> --workflow 4
```

Bu betik PaperQA2 indeksi üzerinde alt başlık başına anlamsal arama yapar ve
sayfa numaralı alıntı adaylarını `04_taslak/taslak/_kanit_bankasi.json` dosyasına
yazar. Abstrakt okuyup yazmaya başlamak, elde yüzlerce sayfa varken metni birkaç
kaynakla sınırlar ve "kanıt yetmiyor" yanılgısını üretir. Betikteki cümleler
**alıntı adayıdır**; taslağa giren her cümle `paperqa_read_pages` ile aynı
sayfadan doğrulanır.

1b. **Kavram haritasını fulltext ile güncelle.** Tam metin okuması yeni
kavramlar ortaya çıkarır; bunlar haritaya `literature` kaynaklı olarak eklenir:

```bash
python3 scripts/build_concept_map.py <proje-kökü> --phase 4
```

1c. **Yazmadan önce kapasiteyi ölç:**

```bash
python3 scripts/build_evidence_gap_request.py <plan.json> --preflight \
  --fulltext-list <03_kaynak_kesfi>/01_fulltext_listesi.json \
  --fulltext-dir <04_taslak>/fulltext \
  --reading-report <03_kaynak_kesfi>/reading-4/03_fulltext_okuma_REVIEWED.json --workflow 4
```

`plan_change_required` çıkarsa **yazmaya başlama**; kullanıcıya sor. Yalnızca
`evidence_shortfall` çıkarsa akış 3'e dönüp yeni kaynak ara (mevcut fulltext
listesini ezme), sonra devam et.

2. PDF'leri hedefe al: `paperqa_promote_fulltext(project_directory=<proje-kökü>, target_workflow="4")` veya `scripts/promote_fulltext.py <proje-kökü> --to 4`. Kullanıcının kendi indirdiği adlandırılmamış PDF'ler de DOI adına çevrilir; hiçbir dosya silinmez.
3. `workflow_project_names.draft` adıyla PDF klasörünü kaydet (`paper_directory` = `04_taslak/fulltext`, `output_directory` = proje kökü). Manifest `.literature-mcp/projects/<ad>/`, indeks `.literature-mcp/indexes/`.
4. `paperqa_build_index` → `paperqa_status` → `library_status` ile indeksi doğrula; beklenen dosya sayısı görünmüyorsa devam etme.
5. Kanıt için yalnızca `paperqa_search` + `paperqa_read_pages` / `read_paper` kullan. Her alıntı için 1 tabanlı PDF sayfası ver. `paperqa_ask` kanıt değildir.
6. Planlanan iskeleti doldur. Her paragraf en az bir doğrulanmış kaynağa bağlanır. Kaynak cümlesini kopyalama; bulguyu paragraf bağlamına uygun özgün Türkçe ile yeniden ifade et.
7. Planda olmayan bölüm eklenirse gerekçesini `correction_summary`'ye yaz; bölüm kelime sayısı hedeften ±%25'ten fazla saparsa gerekçelendir.
8. `source_audit` içindeki her DOI için `source_contributions` alanına rolü, desteklediği/desteklemediği önerme türlerini, sınırlılıklarını ve değerlendirme temelini yaz. Sayfa doğrulanmayanlar kanıt sayılmaz.
9. JSON'u `04_taslak/taslak/04_taslak_<zaman>.json` olarak yaz; `chapter-report build` ile HTML, Markdown ve manifest üret. **Kapı:** kalite kapısı 0 hata.

### İş akışı 5 — Taslak analizi

0. **Analiz öncesi tam okuma.** Hedef PDF kümesinin sayfa inceleme defterini
   `--workflow 5` ile tamamla ve `check` çalıştır. Plan varsa okuma raporu
   ekli `--preflight --workflow 5` de çalıştırılır. Kullanıcı taslağında plan
   yoksa plan şartı aranmaz; bütün sayfaların gerçek okuması ve güncellik
   kontrolü yine zorunludur.

1. **Önce oku, sonra denetle.** Denetlenecek taslağın dayandığı fulltext'lerin
tamamını oku:

```bash
python3 scripts/build_evidence_bank.py <proje-kökü> --workflow 5
```

Çıktı `05_analiz/taslak/_kanit_bankasi.json`. Her iddia bu bankadan gelen pasajla
eşleştirilir, sonra `paperqa_read_pages` ile sayfa doğrulaması yapılır. Kanıt
bankası olmadan iddia–kanıt matrisi kurmak, abstrakt düzeyinde kalmaya yol açar.

2. Plan uyumunu denetle:

```bash
python3 scripts/check_plan_compliance.py <plan.json> <taslak.json> --strict
```

Çıktı `05_analiz/05_plan_uyumu_<zaman>.json/html`: yazılmayan alt başlık, kelime sapması, planda olmayan bölüm, kullanılmayan atama, kanıt boşluğu.

3. Taslak kullanıcıdan geldiyse plan olmayabilir; bu durumda yalnızca kanıt denetimini çalıştır ve plandan söz etme.
4. Her iddia için kaynak, sayfa, kısa alıntı, destek düzeyi ve karar üret (`schemas/claim-evidence.schema.json`). Her düzeltme için `schemas/change-card.schema.json` uyumlu kart üret.
5. Paragraf/makale bağlamını değerlendir: paragrafın amacı, komşu cümlelerle akışı, bölüm savıyla uyumu, kaynak makalenin amacı/yöntemi/örneklemi/sınırlılıkları (`context_review`).
6. Yeniden düzenlenen metni kırmızı, MCP'nin eklediği anlamlı ifadeyi mavi/yeşil işaretle; lejant ekle.
7. Nihai raporu `05_analiz/taslak/05_analiz_<zaman>.html/md` olarak üret. **Kapı:** kalite kapısı 0 hata; plan uyumunda açıklanmamış sapma yok.

## 2. Zorunlu kurallar

1. **Proje izolasyonu.** `paperqa_search`, `paperqa_read_pages`, `paperqa_build_index`, `paperqa_status`, `paperqa_ask`, `project_audit`, `read_paper`, `compare_studies`, `evidence_check`, `library_status` çağrılarında `project` ver. Proje adı bilinmiyorsa önce `list_projects` / `paperqa_projects` çağır.
2. **Kanıt hiyerarşisi.** Tam metin cümlesi > abstract. `paperqa_ask` çıktısı taslaktır; kanıt olarak kullanılamaz. `evidence_check` lexical benzerliktir; entailment kanıtı değildir.
3. **Sayfa numarası.** Her alıntı için 1 tabanlı PDF sayfası ver. Sayfa yoksa iddia `not_found` sayılır.
4. **DOI biçimi.** Teslimlerde yalnızca `https://doi.org/<doi>` kullan. Yerel PDF yolu, `file://` linki veya kullanıcı klasör yolu teslim dosyasına yazılmaz.
5. **Kavram haritası ve anchor terim.** Akış 1'de `02_kavram_haritasi` üretilmeden arama yapılmaz. Bölümün kavramsal çekirdeğinin alanyazındaki adı `anchor_terms` alanında yazılı olmalı ve `search_terms` içinde geçmelidir. MeSH terimleri yalnızca tıp/psikoloji alanındaki kavramlara uygulanır; eğitim alanyazını PubMed'de indekslenmediği için oradaki karşılıklar başka anlama gelir. Kullanıcının Türkçe ifadesini genel eğitim terimlerine çevirmek yeterli değildir; çeviri, alan terimini kaybettirir. Anchor terim doğrulanmadan (`check_concept_coverage.py`) konu keşfi veya kaynak ataması tamamlanmış sayılmaz.

6. **Uydurma yasağı.** DOI, yazar, yıl, dergi, sayfa, alıntı veya sonuç uydurma. Emin değilsen `not_found`, kısmi kanıt varsa `partially_supported` yaz ve kullanıcıya bildir.
6. **Dil.** Teslim Türkçedir. Kaynak cümlesi İngilizceyse özgün hâliyle ver; Türkçe çevirisini ayrı yaz. Çeviri, alıntının yerine geçmez.
7. **Renk kuralı.** HTML'de yalnızca yeniden düzenlenen cümle/parça kırmızı; MCP'nin eklediği anlamlı yeni ifade mavi/yeşil işaretlenir. Paragrafın tamamı, başlık veya kaynak listesi renklendirilmez.
8. **Yayıncıdan bağımsız keşif.** Ovid LWW, ScienceDirect, SpringerLink, Wiley ve Taylor & Francis bağlantıları sunulabilir; keşif bu yayıncılarla sınırlandırılmaz. PubMed/PsycInfo/Embase gibi alan kaynakları, site filtresiz Scholar ve atıf takibi araştırma sorusuna göre önceliklendirilir. İndeks veya yayıncı adı makale kalitesinin kanıtı sayılmaz.
9. **Mevcut projelere dokunma.** Kayıtlı bir projenin PDF klasörü, manifesti, indeksi veya `analysis_json` dosyası, kullanıcı açıkça istemedikçe değiştirilmez. Yeni çalışma için yeni klasör/manifest/indeks kullan.
10. **Çıktı sözleşmesi.** Dosya adları, sütunlar ve biçimler [`docs/output-spec.md`](docs/output-spec.md) dosyasına uyar. JSON çıktıları `schemas/` altındaki şemalara uyumlu olur. Klasör düzeni beş akıştır (01–05); her akış çıktısını kendi klasörüne yazar, PDF'ler yalnızca `fulltext/` altındadır.
11. **Altın standart.** İnsan teslimi `05_analiz_<zaman>.html`'dir; `chapter-report` kalite kapısından 0 hatayla geçmeden teslim edilmez. `05_analiz_<zaman>.json/md` yalnızca denetim odaklı ara çıktıdır. Bölüm raporu HTML'inde DOI kopyalama düğmesi bulunur; kopyalama betiği dışında gömülü betik kullanılmaz. Fulltext listesinde DOI metnini kopyalayan düğme yoktur; tıklanabilir DOI/veritabanı düğmeleri, düz metin DOI ve tıklandığında düzeltilmiş DOI'yi (dosya adı biçimi, uzantısız) panoya kopyalayan "dosya adı" düğmesi bulunur.
12. **Güvenli temizlik.** Üretilmiş dosyalar yalnızca `chapter-report cleanup` ile ve yalnızca `05_analiz_<zaman>.manifest.json` içinde listelenen dosyalar için silinir. PDF, indeks, registry ve manifest dışı dosyalar silinmez.

13. **Özgün anlatım.** Yeni taslakta kaynak bulgularını paragraf bağlamına uygun, özgün cümlelerle aktar. Kaynak cümlelerini aynen kopyalama; doğrudan alıntı gerekiyorsa kısa tut, alıntı olarak işaretle ve PDF sayfasını belirt. Yeniden yazım kanıtın kapsamını genişletmez.
14. **Proje klasörü ve akış seçimi.** Yeni projede kök yolu iste ve `paperqa_create_workspace` çağır; sonra kullanıcıya beş seçenekten birini sor: `1. konu belirleme`, `2. yazım planı`, `3. kaynak keşfi ve fulltext seçimi`, `4. taslak yazma`, `5. taslak analizi`. Seçim gelmeden başlamazsın. Akış 1'de ürün türünü (`kitap_bolumu` / `uygulama_rehberi` / `derleme_makale` / `ampirik_makale`) ve hedef kelime sayısını mutlaka sor; varsayılan tür yoktur. Her akışa özgü PaperQA projesi ve indeksi kullan; manifestler `.literature-mcp/projects/<akış-proje-adı>/`, indeksler `.literature-mcp/indexes/` altındadır.
15. **Kimlik bilgileri ve ilk kurulum.** Yeni proje kökü verildiğinde önce `<proje-kökü>/setup.txt` dosyasını ara. Arama araçlarına `project_directory=<proje-kökü>` ver; araç o klasördeki `setup.txt` dosyasını kendisi okur ve API anahtarlarını o çağrıda kullanır (`setup_file` alanıyla doğrula). Varsa `python3 scripts/setup_credentials.py --project <proje-kökü>` ile bilgileri otomatik al; yoksa kullanıcıya sor: (a) Crossref/NCBI/OpenAlex ve Unpaywall için e-posta, (b) OpenAlex API anahtarı, (c) PubMed/NCBI API anahtarı, (d) Semantic Scholar API anahtarı (isteğe bağlı; 1 istek/sn). MCP sunucusu `setup.txt` dosyasını süreç başında kendisi de okur (`sciencedirect_meta.bootstrap`); bu yüzden anahtarları yalnızca bu dosyada tutmak yeterlidir, ayrıca `opencode.json` düzenlemek gerekmez. Bilgileri ayrıca OpenCode MCP yapılandırmasına yazmak istersen aynı betiği kullan. Anahtarları repoya, rapora veya teslim dosyalarına kopyalama. `setup.txt` düz metin sır içerir; iznini `600` tut ve sürüm kontrolüne ekleme. Anahtarlar isteğe bağlıdır; yoksa araçlar çalışır ancak 429 riski artar. Grup/diğer kullanıcıların okuyabildiği `setup.txt` yüklenmez (`setup_insecure=true`); `chmod 600` uygulanmalıdır. Unpaywall anahtar istemez, yalnızca e-posta ister; `download_open_access.py` bu adresi `setup.txt` içinden okur ve raporda maskeler.

## 3. Araç politikası

| Araç | Ne zaman | Ne zaman değil |
|---|---|---|
| `deep_research` | Konuyu facet'lere bölüp geniş DOI taraması | Tek DOI doğrulama |
| `search_literature` | Çok kaynaklı DOI/metadata arama | Tam metin okuma |
| `search_all` / `search_sciencedirect` / `search_pubmed` / `search_europepmc` / `search_semantic_scholar` / `search_arxiv` / `search_clinicaltrials` | Kaynak havuzunu genişletme | Kanıt üretme |
| `get_article` / `get_links` | Tek kayıt metadata/link | Toplu arama |
| `verify_doi_and_publisher` | DOI gerçekliği, yayıncı, PII | Konu araması |
| `doi_provenance` | DOI hangi veritabanlarında var? | Kalite/kanıt kararı |
| `journal_rank` | Dergi Q1–Q4, SJR | Makale kalitesi kanıtı |
| `project_audit` | Proje PDF'leri + DOI/metadata denetimi | Projeler arası karşılaştırma |
| `read_paper` | Tek PDF tam metni / sayfa aralığı | Abstract ile yetinme |
| `compare_studies` | Yöntem/örneklem/bulgu tablosu | Nihai kanıt |
| `evidence_check` | Hızlı lexical ön tarama | Entailment/kanıt |
| `analysis_updates` | Kayıtlı denetim verisini okuma | Yeni analiz üretme |
| `export_review` | Markdown/CSV/JSON rapor | HTML teslim (ayrıca üretilir) |
| `list_projects` / `library_status` | Proje ve PDF envanteri | Arama |
| `search_diagnostics` | Etkin `setup.txt`, anahtar varlığı, cooldown'lar | Arama sonucu üretme |
| `paperqa_create_workspace` | Seçilen proje kökünde 01–05 akış klasörlerini açma; kayıt/akış/tür seçimi yapmaz | Kullanıcı proje yolunu vermeden |
| `paperqa_promote_fulltext` | Akış 3 PDF'lerini akış 4/5'e kopyalar, DOI adına çevirir | Kaynak seçmeden |
| `paperqa_projects` | Kayıtlı projeler | Arama |
| `paperqa_register_project` | Yeni PDF klasörünü proje yapma | Mevcut projeyi yeniden kaydetme (gerekmedikçe) |
| `paperqa_build_index` | Manifest → indeks | Projeler arası indeks karıştırma |
| `paperqa_status` | İndeks sağlığı | Kanıt |
| `paperqa_search` | Semantik aday cümle/DOI bulma | Nihai alıntı (sayfa doğrulanmalı) |
| `paperqa_read_pages` | Sayfa/quote doğrulama | Tüm PDF'i özetleme |
| `paperqa_ask` | Taslak/özet fikri | Kanıt, alıntı, nihai cümle |

## 4. İş akışı 3 — kabul kriterleri

- Akış 1 ve 2 kullanıldıysa onaylanan başlık, tür, hedef kelime ve alt başlık iskeleti arama çerçevesine aktarılmalı.
- Her adayın DOI'si `verify_doi_and_publisher` ile doğrulanmış olmalı.
- `doi_provenance` en az bir veritabanında kayıt göstermeli.
- `journal_rank` Q1–Q4 veya açık `not_found` döndürmeli.
- HTML tek dosya, yazdırılabilir ve çevrimdışı açılabilir olmalı.
- Her satırda tıklanabilir DOI ve varsa yayıncı linki bulunmalı.
- Liste HTML'i ve JSON'u `03_kaynak_kesfi/` içinde bulunmalı.
- Her alt başlık için en az bir atanmış kaynak bulunmalı; boşluk varsa gerekçesi yazılmalı.
- Her kaynakta bu projedeki olası katkı, destekleyemediği çıkarımlar, sınırlılıklar ve inceleme dayanağı gösterilmeli.

## 5. İş akışı 4 — kabul kriterleri

- PDF'ler geldikten sonra `paperqa_status` ile indeksin gerçekten kurulduğu doğrulanmalı.
- Taslakta her paragraf en az bir doğrulanmış kaynağa bağlanmalı; kaynaksız iddia kalmamalı.
- Bulgular paragraf bağlamına uygun özgün ifadelerle yazılmalı; kaynak cümleleri yalnızca kısa ve açık alıntı olarak kullanılmalı.
- Yeniden yazım doğrulanmış kanıtın kapsamını korumalı; yeni genelleme veya nedensellik eklememeli.
- `04_taslak_<zaman>.json`, `.md` ve `.html` `04_taslak/` içinde olmalı.
- Taslak HTML'i Ek 1 kaynak–taslak eşleştirmelerini ve iddia–kanıt matrisini içermeli; `04_taslak/` içine yazılmalı.
- Her paragraf planlanan bir alt başlığa bağlı olmalı; planda olmayan bölüm varsa gerekçesi yazılmalı.
- Ek 4 her kaynak için projeye katkı, desteklemediği çıkarımlar ve sınırları içermeli; özet/metaveri temelli yorumlar kanıt gibi sunulmamalı.

## 6. İş akışı 5 — kabul kriterleri

- Her düzeltme kartında şu alanlar bulunmalı:
  `id`, `location`, `author_sentence`, `source_sentence`, `source_translation`, `source_doi`, `source_page`, `rewritten_sentence`, `note`, `evidence_status`.
- `source_sentence` birebir PDF'ten alınmış olmalı; sayfa numarası verilmeli.
- `source_translation` kaynak cümlesinin Türkçesi olmalı; yorum katılmamalı.
- `rewritten_sentence` yalnızca kanıtın desteklediği kadarını söylemeli; abartıyı kaldırmalı.
- `rewritten_sentence`, bölüm paragrafına doğrudan alınabilecek doğal ve bağlama uygun bir cümle olmalı. “Kaynaklar bunu göstermiyor”, “kanıt bulunamadı” gibi denetim açıklamaları ana metne değil `note`, iddia–kanıt matrisi veya sınırlılıklara yazılır.
- İddianın tamamı desteklenmiyorsa yalnızca desteklenen kısmı, paragrafın anlamlı akışını koruyarak yeniden kur. Desteklenen bir önerme kalmıyorsa iddiayı ana metinden çıkar; boşluğu rapor notunda açıkla. Kanıt boşluğunu yeni bir iddiayla veya yapay bir geçiş cümlesiyle doldurma.
- Düzeltmeden sonra cümleyi önceki ve sonraki cümleyle birlikte oku: gönderimi belirsiz zamir, kopuk bağlaç, yinelenen fikir veya paragrafın amacından sapan bir cümle bırakma.
- `evidence_status`: `supported`, `partially_supported`, `contradicted`, `not_found`.
- Ek 2 kaynak denetiminde her kaynak için DOI, yayıncı, Q, atıf, erişim ve kullanım kararı bulunmalı.
- İddia–kanıt matrisinde her iddia için kaynak, sayfa, kısa kanıt, destek düzeyi ve karar bulunmalı.
- İddia–kanıt matrisinde konum (`P1 · c2`), kanıt türü ve kısa not sütunları bulunmalı.
- HTML'de yeniden düzenlenen metin kırmızı; MCP'nin anlamlı yeni eklemeleri mavi/yeşil, kaynak cümlesi ve çevirisi normal renkte olmalı. Renk lejantı bulunmalı.
- HTML'de paragraf/bölüm bağlamı değerlendirilmeli: paragraf işlevi, cümle uyumu/akışı ve kaynak makalenin amacı-yöntemi-örneklemi-sınırlılıkları göz önünde bulundurulmalı.
- HTML Ek 3'te bağlama daha uygun olabilecek, DOI ve metadata doğrulanmış kaynak adayları, ilgili konum ve uyum gerekçesiyle listelenmeli. Tam metni okunmamış adayların kanıt olmadığı açıkça yazılmalı; öneri yoksa nedeni belirtilmeli.
- HTML Ek 4'te kaynak başına bu çalışmadaki rol, desteklediği/desteklemediği önerme türleri, sınırlılıklar ve değerlendirme temeli bulunmalı.
- Son teslimde DOI linkleri `https://doi.org/...`; yerel PDF linki yok.
- `05_analiz_<zaman>.html` `chapter-report` kalite kapısından 0 hatayla geçmeli; Ek 1 ve Ek 2 eksiksiz olmalı.
- Plan uyumu raporu `05_analiz/05_plan_uyumu_<zaman>.html` ve nihai rapor `05_analiz/05_analiz_<zaman>.html` içinde olmalı.
- Yazılmayan alt başlık veya açıklanmamış kelime sapması kalmamalı.

## 7. Durma ve kullanıcıya sorma koşulları

Aşağıdaki durumlarda tahmin yürütme; kullanıcıya sor:

- Proje adı/klasörü belirsizse veya `projects.json` ile uyuşmuyorsa.
- İndeks `paperqa_status` ile doğrulanamıyorsa.
- Taslak ile PDF'ler arasında ciddi kapsam farkı varsa.
- Bir iddia için tam metin bulunamıyorsa ve abstract yeterli değilse.
- DOI doğrulanamıyorsa veya birden fazla kayıt aynı DOI'yi farklı metadata ile gösteriyorsa.
- Kullanıcı yeni bir konu/kapsam isteyip hedef kaynak sayısını belirtmemişse.
- Eski proje dosyalarında değişiklik yapılması gerekiyorsa.

## 8. Çıktı yolları ve adlandırma

Çıktılar, en başta kullanıcının verdiği proje klasörüne yazılır. Yeni proje
kaydında `output_directory` zorunludur; `chapter-report build -o ...` ve
`export_review(project=...)` bu yolu izler.
Proje `output_directory` altında:

```text
01_konu_belirleme/01_konu_<zaman>.json
01_konu_belirleme/01_konu_<zaman>.html
01_konu_belirleme/01_yontem_tasarimi_<zaman>.json   (ampirik makale seçildiyse)
01_konu_belirleme/01_yontem_tasarimi_<zaman>.html
02_yazim_plani/01_yazim_plani_<zaman>.json
02_yazim_plani/01_yazim_plani_<zaman>.html
03_kaynak_kesfi/00_atama_matrisi_<zaman>.json
03_kaynak_kesfi/00_atama_matrisi_<zaman>.html
03_kaynak_kesfi/00_kaynak_listeleri_<zaman>.html
03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json
03_kaynak_kesfi/01_fulltext_listesi_<zaman>.html
03_kaynak_kesfi/01_<arastirma-kisa-adi>_fulltext_listesi_<zaman>.json   (çoklu araştırma)
03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>.json
03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>.html
03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>.md
03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>_karsilastirma.json
03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>_karsilastirma.html
03_kaynak_kesfi/fulltext/<doi-adi>.pdf
03_kaynak_kesfi/oa_indirme_raporu_<zaman>.json
04_taslak/fulltext/<doi-adi>.pdf
04_taslak/fulltext_aktarim_<zaman>.json
04_taslak/taslak/04_taslak_<zaman>.json
04_taslak/taslak/04_taslak_<zaman>.md
04_taslak/taslak/04_taslak_<zaman>.html
04_taslak/taslak/04_taslak_<zaman>.manifest.json
04_taslak/oa_indirme_raporu_<zaman>.json
05_analiz/taslak/05_plan_uyumu_<zaman>.json
05_analiz/taslak/05_plan_uyumu_<zaman>.html
05_analiz/taslak/05_analiz_<zaman>.html
05_analiz/taslak/05_analiz_<zaman>.md
05_analiz/taslak/05_analiz_<zaman>.manifest.json
```

`<zaman>` biçimi `YYYYMMDD-HHMMSS`'tir. Sabit ad gerekiyorsa üreticilere
`--no-timestamp` verilebilir; varsayılan davranış zaman sonekidir. Aynı saniye
içinde ikinci çıktı üretilirse `-01`, `-02` soneki eklenir. Zaman soneki
sayesinde tekrar çalıştırma önceki çıktıyı ezmez; yine de aynı ada sahip eski
dosya varsa kullanıcıya sor.

**Silme kuralı:** Yeni bir arama/rapor çalıştırması önceki dosyaları **silmez**;
klasörde her sürüm ayrı dosya olarak kalır. Aynı adla yazma denemesi
`--force` olmadan reddedilir. Tek istisna, kullanıcının açıkça çağırdığı
manifest tabanlı `chapter-report cleanup` komutudur. Eski çıktıyı silmek
gerekmedikçe silme; kullanıcıya sor.

Birden çok araştırmanın listeleri aynı `03_kaynak_kesfi/` klasöründe tutulur; ayrı araştırma kök klasörlerine dağıtılmaz. Her dosya adı sıra numarası ve araştırma kısa adını içerir. `00_kaynak_listeleri_<zaman>.html` tüm listelere giriş sayfasıdır. Aynı ada sahip eski dosya varsa üzerine yazmadan önce kullanıcıya sor.

## 9. Doğrulama kontrol listesi

Teslimden önce:

- [ ] `paperqa_status` doğru projeyi ve beklenen dosya sayısını gösteriyor.
- [ ] Her DOI `verify_doi_and_publisher` ile doğrulandı.
- [ ] Her alıntı `paperqa_read_pages` ile sayfa numarasıyla teyit edildi.
- [ ] `paperqa_ask` çıktısı hiçbir yerde kanıt olarak kullanılmadı.
- [ ] HTML'de düzenlenen metin kırmızı, anlamlı MCP eklemeleri mavi/yeşil ve renk lejantı mevcut.
- [ ] Kaynak listesi ve raporlarda Ek 4 kaynak katkısı/sınır değerlendirmeleri mevcut.
- [ ] İş akışı 5'te paragraf/makale bağlamı değerlendirmesi ve Ek 3 kaynak önerileri mevcut.
- [ ] İş akışı 1'de dört varsayılan veri tabanı durumu, en yakın çalışmalar ve özgünlük sınırlılığı raporlanmış.
- [ ] Yerel PDF yolu / `file://` linki yok.
- [ ] DOI linkleri `https://doi.org/...`.
- [ ] CSV UTF-8 (BOM'lu) ve başlık satırı doğru.
- [ ] JSON şemaya uyuyor.
- [ ] `05_analiz_<zaman>.html` kalite kapısından 0 hatayla geçti.
- [ ] Üretilen HTML/Markdown/manifest/rapor adları `_YYYYMMDD-HHMMSS` soneki içeriyor; önceki çıktı ezilmedi.
- [ ] Kaynak listesi HTML'inde tıklanabilir DOI/veritabanı düğmeleri ve düz metin DOI var; indirilen PDF'ler işaretli; "dosya adı" düğmesi düzeltilmiş DOI'yi kopyalıyor, ham DOI metnini kopyalayan düğme yok.
- [ ] Bölüm raporu HTML'lerinde DOI kopyalama düğmesi var; kopyalama betiği dışında gömülü betik yok.
- [ ] Arama cevabındaki `coverage` ve `evidence_scarcity` alanları incelendi; kapsam raporu `03_kaynak_kesfi/01_arama_kapsam_raporu_<zaman>.json/html/md` olarak yazıldı. Raporda kaynak durumları (`ok`/`error`/`rate_limited`/sorgulanmadı), istenen limit, süre, `warnings`, publisher/OA dağılımı, katı yüksek-kalite sayısı ve trend sinyali görünüyor.
- [ ] Ürün türü ve hedef kelime sayısı kullanıcıya soruldu; yazım planı onaylandı (`plan_status: approved`).
- [ ] Atama matrisi üretildi; her alt başlıkta `min_count` karşılandı veya boşluk gerekçesi yazıldı.
- [ ] Açık erişim indirmeleri yalnızca herkese açık bağlantılarla ve yalnızca atanmış DOI'ler için yapıldı; hedef `03_kaynak_kesfi/fulltext/`, rapor aynı klasörde.
- [ ] Plan uyumu raporu `05_analiz/05_plan_uyumu_<zaman>.html` üretildi ve sapmalar açıklandı.
- [ ] Temizlik yalnızca manifestteki dosyalara uygulandı.
- [ ] Proje izolasyonu ihlal edilmedi; başka proje dosyası okunmadı.
- [ ] Eski proje dosyaları değiştirilmedi.

## 10. Depo durumu ve proje kaydı

- Bu depo **kod ve dokümantasyon** deposudur; PDF, indeks, manifest veya kişisel
  analiz dosyası içermez.
- Depo sürümü v2.15.0; önceki public sürüm v2.7.1'dir.
  Yayımlanmamış bölüm metni ve gerçek proje çıktıları depoya konmaz.
- Depodaki MCP: `sciencedirect-meta` 25 araç, `paperqa-local` 10 araç.
- Kayıtlı projeler kullanıcıya özeldir ve `projects.json` içinde tutulur
  (varsayılan: `~/.literature-mcp/projects.json`). Depoda yalnızca
  `examples/projects.example.json` örneği bulunur.
- Yeni projede önce `paperqa_create_workspace` ile seçilen klasörü başlat;
  PDF'ler geldikten sonra `paperqa_register_project` ile manifeste al.
  Mevcut projeye sonradan PDF ekleme; yeni PDF'ler yeni proje veya yeni
  manifest gerektirir.
- `analysis_updates` yalnızca `analysis_json` tanımlı projelerde çalışır;
  tanımsızsa açık hata döndürmesi beklenen davranıştır.

## 11. Hızlı komutlar

```bash
# Statik kontroller (sürüm + ruff)
bash scripts/lint.sh

# MCP testleri
PYTHONPATH=packages/sciencedirect-meta/src \
  .venv/bin/python -m unittest discover -s packages/sciencedirect-meta/tests -v

# Tüm doğrulamalar
bash scripts/validate_all.sh

# PaperQA bağımlılıkları (CPU-only PyTorch)
bash scripts/setup_paperqa.sh
bash scripts/setup_paperqa.sh --check

# Fulltext HTML üretimi (varsayılan: zaman soneki)
python3 scripts/build_fulltext_list.py \
  <proje-kökü>/03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json \
  -o <proje-kökü>/03_kaynak_kesfi/01_fulltext_listesi_<zaman>.html

# Sabit ad gerekiyorsa
python3 scripts/build_fulltext_list.py adaylar.json -o liste.html --no-timestamp

# Bir veya daha fazla kaynak listesi için giriş sayfası
python3 scripts/build_fulltext_index.py <proje-kökü>/03_kaynak_kesfi

# Arama kapsam raporu (JSON + HTML + Markdown)
python3 scripts/build_search_coverage.py arama.json \
  -o <proje-kökü>/03_kaynak_kesfi

# Yazım planı (akış 2)
python3 scripts/build_writing_plan.py <plan.json> \
  -o <proje-kökü>/02_yazim_plani/01_yazim_plani.html

# Atama matrisi (akış 3)
python3 scripts/build_assignment_matrix.py \
  <proje-kökü>/02_yazim_plani/01_yazim_plani_<zaman>.json \
  <proje-kökü>/03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json \
  -o <proje-kökü>/03_kaynak_kesfi --update-plan

# Açık erişimli PDF'leri indir (Unpaywall → OpenAlex)
# Varsayılan hedef: 03_kaynak_kesfi/fulltext/
python3 scripts/download_open_access.py \
  <proje-kökü>/03_kaynak_kesfi/01_fulltext_listesi_<zaman>.json
python3 scripts/download_open_access.py adaylar.json --workflow 4   # 04_taslak/fulltext/
python3 scripts/download_open_access.py adaylar.json --workflow 5   # 05_analiz/fulltext/
python3 scripts/download_open_access.py adaylar.json --dry-run

# Akış 1 → 4 PDF aktarımı (DOI adına çevirir)
python3 scripts/promote_fulltext.py <proje-kökü> --to 4 --dry-run

# Kavram haritası (akış 1 -> 2 -> 3 -> 4)
python3 scripts/build_concept_map.py <proje-kökü> --phase 1 --query-en "..." [--mesh]
python3 scripts/build_concept_map.py <proje-kökü> --phase 2
python3 scripts/build_concept_map.py <proje-kökü> --phase 3
python3 scripts/build_concept_map.py <proje-kökü> --phase 4

# Kavram kapsamı (anchor terim zinciri)
python3 scripts/check_concept_coverage.py <plan.json> --check
python3 scripts/check_concept_coverage.py <plan.json> \
  --project-root <proje-kökü> --workflow 4

# Akış 4/5 ilk adımı: fulltext okuma + kanıt bankası
python3 scripts/build_evidence_bank.py <proje-kökü> --workflow 4
python3 scripts/build_evidence_bank.py <proje-kökü> --workflow 5 --check

# Yazmadan önce kapasite denetimi (uçuş öncesi)
python3 scripts/build_evidence_gap_request.py \
  <proje-kökü>/02_yazim_plani/01_yazim_plani.json --preflight \
  --fulltext-list <proje-kökü>/03_kaynak_kesfi/01_fulltext_listesi.json \
  --fulltext-dir <proje-kökü>/04_taslak/fulltext \
  --reading-report <proje-kökü>/03_kaynak_kesfi/reading-4/03_fulltext_okuma_REVIEWED.json --workflow 4

# Taslak sonrası boşluk talebi
python3 scripts/build_evidence_gap_request.py \
  <proje-kökü>/02_yazim_plani/01_yazim_plani.json \
  <proje-kökü>/04_taslak/taslak/04_taslak.json \
  -o <proje-kökü>/03_kaynak_kesfi

# Plan uyumu (akış 5)
python3 scripts/check_plan_compliance.py \
  <proje-kökü>/02_yazim_plani/01_yazim_plani_<zaman>.json \
  <proje-kökü>/04_taslak/04_taslak_<zaman>.json --strict

# Altın standart rapor: doğrula + üret + temizlik seçeneği
.venv/bin/chapter-report build <proje-kökü>/04_taslak/04_taslak_<zaman>.json --check
.venv/bin/chapter-report build <proje-kökü>/04_taslak/04_taslak_<zaman>.json \
  -o <proje-kökü>/05_analiz/05_analiz.html \
  --markdown <proje-kökü>/05_analiz/05_analiz.md
.venv/bin/chapter-report cleanup --manifest 05_analiz_<zaman>.manifest.json \
  --scope intermediate --dry-run

# Örnek (sabit adlı örnek dosyalar)
python3 scripts/build_fulltext_list.py \
  examples/fulltext-list.example.json \
  -o examples/fulltext-list.example.html --no-timestamp --force
```

`chapter-report build` verilen HTML/Markdown adlarına varsayılan olarak
`_YYYYMMDD-HHMMSS` ekler; sabit ad için `--no-timestamp --force` kullanın.

Araçların tam listesi ve girdi/çıktı şemaları: [`docs/tool-catalog.json`](docs/tool-catalog.json).
