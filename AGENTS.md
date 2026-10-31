# AGENTS.md — Literatür Projesi Ajan Sözleşmesi

Bu dosya, bu projede çalışan yapay zekâ ajanları için **bağlayıcı** kuralları ve araç politikasını tanımlar. İnsanlar için giriş noktası [`README.md`](README.md) dosyasıdır.

## 1. Görev tanımı

Her yeni proje kullanıcı proje kökünü verince başlar; `paperqa_create_workspace` 00–03 akış klasörlerini açar; ardından kullanıcıya 0, 1, 2 veya 3. akıştan hangisini istediğini sor. Seçim gelmeden arama veya PDF işleme yapma.

### İş akışı 0 — Konu, çalışma başlığı ve amaç keşfi

1. Kullanıcının konu çerçevesini, hedef grubu/bağlamı, ilgili sonuçları ve uygulanabilirlik kısıtlarını netleştir.
2. Varsayılan OpenAlex, PubMed, Europe PMC ve Crossref kaynaklarında eş anlamlılar ve alt temalarla tara. `search_literature` çağrılarında `sources=["openalex", "pubmed", "europepmc", "crossref"]`, `priority_only=false` kullan.
3. Her sorgu ve her veritabanı için `sources_status`, kayıt sayısı ve hata/not bilgisini kaydet. Aranmayan veya başarısız kaynağı başarılı gibi işaretleme; kısıtlı kapsamlı kaynakları (PubMed/Europe PMC gibi) belirt.
4. En yakın bulunan yayınlara ve kapsanmayan bağlam/örneklem/yöntem/sonuçlara dayalı sıralı çalışma başlığı, araştırma sorusu, genel ve özel amaçlar, önerilen desen, yapılabilirlik ve sıralama gerekçesi ver.
5. Mutlak özgünlük iddiasında bulunma. `novelty_signal` zayıf/orta/belirgin boşluk sinyalidir; tam yenilik değerlendirmesi sistematik tarama, atıf zinciri ve alan uzmanı doğrulaması gerektirir.
6. `schemas/topic-discovery.schema.json` uyumlu `00_konu_basligi_kesfi/00_konu_basligi_kesfi.json` üret ve `scripts/build_topic_discovery.py` ile HTML'e dönüştür. Kullanıcı öneri seçip kapsamı onaylayınca akış 1'e aktar.

### İş akışı 1 — Kaynak keşfi ve PDF listesi

1. Kullanıcı iş akışı 1'i seçtikten sonra konu/kapsam, hedef kaynak sayısı, yıl aralığı ve dil kriterlerini netleştir.
2. `deep_research` veya `search_literature` ile aday DOI'leri topla.
3. Gerekirse `search_all`, `search_sciencedirect`, `search_pubmed`, `search_europepmc` ile genişlet.
4. Her aday için `get_article` ve `get_links` ile metadata ve linkleri al.
5. `verify_doi_and_publisher`, `doi_provenance`, `journal_rank` ile DOI'yi, yayıncıyı ve quartile'ı doğrula.
6. Her aday için projedeki olası katkıyı, destekleyebileceği ve destekleyemeyeceği sonuçları, sınırlılıkları ve değerlendirme temelini (metadata/abstract/fulltext/fulltext_pages) belirt. Tam metin veya sayfa görülmediyse bunu ön değerlendirme olarak sun.
7. Adayları `schemas/fulltext-list.schema.json` biçiminde JSON'a yaz.
8. Aday JSON'u `01_kaynak_kesfi/` içine yaz; `scripts/build_fulltext_list.py` ile `01_kaynak_kesfi/01_fulltext_listesi.html` üret.
9. Kaynak başına katkı ve sınır değerlendirmelerinin HTML'de göründüğünü kontrol et. Bu iş akışı burada tamamlanır.

### İş akışı 2 — PDF'lerden kanıta dayalı taslak

1. Kullanıcı iş akışı 2'yi seçince PDF'leri `<proje-kökü>/02_bolum_taslagi/fulltext/` içine koymasını iste; dosyalar gelmeden devam etme.
2. `paperqa_create_workspace` sonucundaki `workflow_project_names.draft` adını kullanarak PDF klasörünü kaydet. `paper_directory` bu PDF klasörü, `output_directory` proje kökü olsun. Manifestler `<proje-kökü>/.literature-mcp/projects/<proje-adı>/`, indeks `<proje-kökü>/.literature-mcp/indexes/` altında tutulur.
3. `project_audit` → `paperqa_build_index` → `paperqa_status` → `library_status` ile PDF'leri kaydet ve indeksi doğrula.
4. Taslak için yalnızca `paperqa_search` + `paperqa_read_pages` / `read_paper` kanıtını kullan.
5. PDF'ten doğrulanan bulguları, paragrafın amacı ve bağlamına uygun özgün Türkçe cümlelerle yeniden ifade et. Kaynak cümlelerini taslağa aynen kopyalama; yalnızca gerektiğinde kısa, açıkça alıntılanmış ve sayfa numarası verilmiş alıntılar kullan.
6. `source_audit` içindeki her DOI için `source_contributions` alanına projedeki rolünü, desteklediği/desteklemediği önerme türlerini, sınırlılıklarını ve değerlendirme temelini yaz. Sayfa doğrulanmayanlar kanıt olarak gösterilmemeli.
7. Taslak raporu JSON'unu `02_bolum_taslagi/taslak/` içine yaz. `chapter-report build` ile HTML ve Markdown üret; HTML'de bölüm metni, Ek 1 kaynak–taslak eşleştirmeleri, Ek 2 iddia–kanıt matrisi ve Ek 4 kaynak katkısı/sınırları bulunmalı.

### İş akışı 3 — Mevcut taslağı denetleme

1. Kullanıcı iş akışı 3'ü seçince denetlenecek taslağı `03_taslak_denetimi/taslak/` içine, tam metin PDF'leri `03_taslak_denetimi/fulltext/` içine koymasını iste; dosyalar gelmeden devam etme.
2. `workflow_project_names.audit` adını kullanarak denetim PDF klasörünü ayrı bir PaperQA projesi olarak kaydet. `output_directory` proje kökü olsun; denetim manifesti ve indeksi taslak hazırlama akışından ayrı tutulur.
3. `project_audit`, `paperqa_status`, `library_status` ile bu denetim projesinin gerçek durumunu doğrula.
4. Taslağı oku ve her cümleyi/iddiayı ayrı kaydet.
5. Her iddianın paragrafını ve taslağın ilgili bölümünü de değerlendir. Paragrafın amacı, komşu cümlelerle akışı, bölüm savıyla uyumu ve kaynak makalenin amacı/yöntemi/örneklemi/sınırlılıklarını raporun `context_review` alanına yaz.
6. Her iddia için:
   - `paperqa_search(project=..., query=...)`
   - Dönen DOI'yi `paperqa_read_pages(project=..., doi=..., page_start=..., page_end=...)` ile doğrula.
   - Gerekirse `read_paper` ile tam metni oku.
7. `verify_doi_and_publisher` ve `doi_provenance` ile DOI'nin gerçekliğini; `journal_rank` ile dergi quartile'ını doğrula.
8. `compare_studies` ve `evidence_check` yalnızca **yardımcı** tarama içindir; nihai kanıt değildir.
9. Her düzeltme için `schemas/change-card.schema.json` uyumlu kart üret. `rewritten_segments` ile anlam bakımından yeni eklenen ifadeleri `added_by_mcp=true` olarak işaretle; tam cümleyle aynı metni oluşturduğunu doğrula.
10. Paragraf/bölüm metnindeki aynı yeni ifadeleri `intro.paragraphs[].segments` içinde `added_by_mcp=true` olarak da işaretle. HTML lejantında kırmızı yeniden düzenlenen metni, mavi/yeşil MCP eklemesini anlatsın.
11. Bağlama daha uygun kaynak adaylarını bul, DOI ve metadata doğrula; `source_recommendations` alanına neden daha iyi uyduklarını yaz. Bunlar tam metin sayfaları doğrulanmadıkça kanıt sayılmaz. Aday yoksa boş dizi ve `source_recommendations_note` kullan.
12. Ek 2 kaynak denetimi ve iddia–kanıt matrisini `schemas/claim-evidence.schema.json` uyumlu üret.
13. `source_audit` içindeki her DOI için `source_contributions` alanına projedeki rolünü, desteklediği/desteklemediği önerme türlerini, sınırlılıklarını ve sayfa doğrulaması dahil değerlendirme temelini yaz.
14. `export_review(output_path=<proje-kökü>/03_taslak_denetimi/taslak/...)` ile Markdown/CSV/JSON; insan teslimi için `chapter-report build` ile `03_taslak_denetimi/taslak/05_bolum_raporu.html` üret. HTML'de bağlam değerlendirmesi, Ek 3 kaynak önerileri ve Ek 4 kaynak katkısı/sınırları bulunmalı.
15. Kalite kapısı 0 hata verene kadar düzelt; teslimden sonra kullanıcıya `--cleanup intermediate/all` seçeneğini sun.

## 2. Zorunlu kurallar

1. **Proje izolasyonu.** `paperqa_search`, `paperqa_read_pages`, `paperqa_build_index`, `paperqa_status`, `paperqa_ask`, `project_audit`, `read_paper`, `compare_studies`, `evidence_check`, `library_status` çağrılarında `project` ver. Proje adı bilinmiyorsa önce `list_projects` / `paperqa_projects` çağır.
2. **Kanıt hiyerarşisi.** Tam metin cümlesi > abstract. `paperqa_ask` çıktısı taslaktır; kanıt olarak kullanılamaz. `evidence_check` lexical benzerliktir; entailment kanıtı değildir.
3. **Sayfa numarası.** Her alıntı için 1 tabanlı PDF sayfası ver. Sayfa yoksa iddia `not_found` sayılır.
4. **DOI biçimi.** Teslimlerde yalnızca `https://doi.org/<doi>` kullan. Yerel PDF yolu, `file://` linki veya kullanıcı klasör yolu teslim dosyasına yazılmaz.
5. **Uydurma yasağı.** DOI, yazar, yıl, dergi, sayfa, alıntı veya sonuç uydurma. Emin değilsen `not_found`, kısmi kanıt varsa `partially_supported` yaz ve kullanıcıya bildir.
6. **Dil.** Teslim Türkçedir. Kaynak cümlesi İngilizceyse özgün hâliyle ver; Türkçe çevirisini ayrı yaz. Çeviri, alıntının yerine geçmez.
7. **Renk kuralı.** HTML'de yalnızca yeniden düzenlenen cümle/parça kırmızı; MCP'nin eklediği anlamlı yeni ifade mavi/yeşil işaretlenir. Paragrafın tamamı, başlık veya kaynak listesi renklendirilmez.
8. **Beş platform.** Yalnızca Ovid LWW, ScienceDirect, SpringerLink, Wiley ve Taylor & Francis linkleri önceliklidir. Başka bir dizin sağlayıcısına bağımlılık kurma.
9. **Mevcut projelere dokunma.** Kayıtlı bir projenin PDF klasörü, manifesti, indeksi veya `analysis_json` dosyası, kullanıcı açıkça istemedikçe değiştirilmez. Yeni çalışma için yeni klasör/manifest/indeks kullan.
10. **Çıktı sözleşmesi.** Dosya adları, sütunlar ve biçimler [`docs/output-spec.md`](docs/output-spec.md) dosyasına uyar. JSON çıktıları `schemas/` altındaki şemalara uyumlu olur.
11. **Altın standart.** İnsan teslimi `05_bolum_raporu.html`'dir; `chapter-report` kalite kapısından 0 hatayla geçmeden teslim edilmez. `04_denetim_raporu.html` yalnızca denetim odaklı ara çıktıdır.
12. **Güvenli temizlik.** Üretilmiş dosyalar yalnızca `chapter-report cleanup` ile ve yalnızca `05_bolum_raporu.manifest.json` içinde listelenen dosyalar için silinir. PDF, indeks, registry ve manifest dışı dosyalar silinmez.

13. **Özgün anlatım.** Yeni taslakta kaynak bulgularını paragraf bağlamına uygun, özgün cümlelerle aktar. Kaynak cümlelerini aynen kopyalama; doğrudan alıntı gerekiyorsa kısa tut, alıntı olarak işaretle ve PDF sayfasını belirt. Yeniden yazım kanıtın kapsamını genişletmez.
14. **Proje klasörü ve akış seçimi.** Yeni projede kök yolu iste ve `paperqa_create_workspace` çağır; sonra kullanıcıya `1. kaynak listesi`, `2. PDF'lerden taslak`, `3. mevcut taslağı denetleme` seçeneklerinden birini sor. Seçim gelmeden başlamazsın. Her akışa özgü PaperQA projesi ve indeksi kullan; manifestler `.literature-mcp/projects/<akış-proje-adı>/`, indeksler `.literature-mcp/indexes/` altındadır.

## 3. Araç politikası

| Araç | Ne zaman | Ne zaman değil |
|---|---|---|
| `deep_research` | Konuyu facet'lere bölüp geniş DOI taraması | Tek DOI doğrulama |
| `search_literature` | Çok kaynaklı DOI/metadata arama | Tam metin okuma |
| `search_all` / `search_sciencedirect` / `search_pubmed` / `search_europepmc` | Kaynak havuzunu genişletme | Kanıt üretme |
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
| `paperqa_create_workspace` | Seçilen proje kökünde 00–03 akış klasörlerini açma; kayıt/akış seçimi yapmaz | Kullanıcı proje yolunu vermeden |
| `paperqa_projects` | Kayıtlı projeler | Arama |
| `paperqa_register_project` | Yeni PDF klasörünü proje yapma | Mevcut projeyi yeniden kaydetme (gerekmedikçe) |
| `paperqa_build_index` | Manifest → indeks | Projeler arası indeks karıştırma |
| `paperqa_status` | İndeks sağlığı | Kanıt |
| `paperqa_search` | Semantik aday cümle/DOI bulma | Nihai alıntı (sayfa doğrulanmalı) |
| `paperqa_read_pages` | Sayfa/quote doğrulama | Tüm PDF'i özetleme |
| `paperqa_ask` | Taslak/özet fikri | Kanıt, alıntı, nihai cümle |

## 4. İş akışı 1 — kabul kriterleri

- Akış 0 kullanıldıysa seçilen ve kullanıcıca onaylanan başlık/amaç arama çerçevesine aktarılmalı.
- Her adayın DOI'si `verify_doi_and_publisher` ile doğrulanmış olmalı.
- `doi_provenance` en az bir veritabanında kayıt göstermeli.
- `journal_rank` Q1–Q4 veya açık `not_found` döndürmeli.
- HTML tek dosya, yazdırılabilir ve çevrimdışı açılabilir olmalı.
- Her satırda tıklanabilir DOI ve varsa yayıncı linki bulunmalı.
- Liste HTML'i ve JSON'u `01_kaynak_kesfi/` içinde bulunmalı.
- Her kaynakta bu projedeki olası katkı, destekleyemediği çıkarımlar, sınırlılıklar ve inceleme dayanağı gösterilmeli.

## 5. İş akışı 2 — kabul kriterleri

- PDF'ler geldikten sonra `paperqa_status` ile indeksin gerçekten kurulduğu doğrulanmalı.
- Taslakta her paragraf en az bir doğrulanmış kaynağa bağlanmalı; kaynaksız iddia kalmamalı.
- Bulgular paragraf bağlamına uygun özgün ifadelerle yazılmalı; kaynak cümleleri yalnızca kısa ve açık alıntı olarak kullanılmalı.
- Yeniden yazım doğrulanmış kanıtın kapsamını korumalı; yeni genelleme veya nedensellik eklememeli.
- `02_bolum_taslagi.json`, `.md` ve `.html` `02_bolum_taslagi/taslak/` içinde olmalı.
- Taslak HTML'i Ek 1 kaynak–taslak eşleştirmelerini ve iddia–kanıt matrisini içermeli; `02_bolum_taslagi/taslak/` içine yazılmalı.
- Ek 4 her kaynak için projeye katkı, desteklemediği çıkarımlar ve sınırları içermeli; özet/metaveri temelli yorumlar kanıt gibi sunulmamalı.

## 6. İş akışı 3 — kabul kriterleri

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
- `05_bolum_raporu.html` `chapter-report` kalite kapısından 0 hatayla geçmeli; Ek 1 ve Ek 2 eksiksiz olmalı.
- Ana rapor çıktısı `03_taslak_denetimi/taslak/` içinde olmalı.

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
00_konu_basligi_kesfi/00_konu_basligi_kesfi.json
00_konu_basligi_kesfi/00_konu_basligi_kesfi.html
01_kaynak_kesfi/01_fulltext_listesi.html
01_kaynak_kesfi/01_fulltext_listesi.json
02_bolum_taslagi/taslak/02_bolum_taslagi.json
02_bolum_taslagi/taslak/02_bolum_taslagi.md
02_bolum_taslagi/taslak/02_bolum_taslagi.html
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

Proje adı dosya adına eklenmek istenirse başta verilir: `<proje-adi>_01_fulltext_listesi.html`. Aynı ada sahip eski dosya varsa üzerine yazmadan önce kullanıcıya sor.

## 9. Doğrulama kontrol listesi

Teslimden önce:

- [ ] `paperqa_status` doğru projeyi ve beklenen dosya sayısını gösteriyor.
- [ ] Her DOI `verify_doi_and_publisher` ile doğrulandı.
- [ ] Her alıntı `paperqa_read_pages` ile sayfa numarasıyla teyit edildi.
- [ ] `paperqa_ask` çıktısı hiçbir yerde kanıt olarak kullanılmadı.
- [ ] HTML'de düzenlenen metin kırmızı, anlamlı MCP eklemeleri mavi/yeşil ve renk lejantı mevcut.
- [ ] Kaynak listesi ve raporlarda Ek 4 kaynak katkısı/sınır değerlendirmeleri mevcut.
- [ ] İş akışı 3'te paragraf/makale bağlamı değerlendirmesi ve Ek 3 kaynak önerileri mevcut.
- [ ] İş akışı 0'da dört varsayılan veri tabanı durumu, en yakın çalışmalar ve özgünlük sınırlılığı raporlanmış.
- [ ] Yerel PDF yolu / `file://` linki yok.
- [ ] DOI linkleri `https://doi.org/...`.
- [ ] CSV UTF-8 (BOM'lu) ve başlık satırı doğru.
- [ ] JSON şemaya uyuyor.
- [ ] `05_bolum_raporu.html` kalite kapısından 0 hatayla geçti.
- [ ] Temizlik yalnızca manifestteki dosyalara uygulandı.
- [ ] Proje izolasyonu ihlal edilmedi; başka proje dosyası okunmadı.
- [ ] Eski proje dosyaları değiştirilmedi.

## 10. Depo durumu ve proje kaydı

- Bu depo **kod ve dokümantasyon** deposudur; PDF, indeks, manifest veya kişisel
  analiz dosyası içermez.
- Depo sürümü v2.5.1; önceki public sürüm v2.5.0'dır.
  Yayımlanmamış bölüm metni ve gerçek proje çıktıları depoya konmaz.
- Depodaki MCP: `sciencedirect-meta` 19 araç, `paperqa-local` 9 araç.
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
# MCP testleri
PYTHONPATH=packages/sciencedirect-meta/src \
  .venv/bin/python -m unittest discover -s packages/sciencedirect-meta/tests -v

# Tüm doğrulamalar
bash scripts/validate_all.sh

# Fulltext HTML üretimi
python3 scripts/build_fulltext_list.py \
  <proje-kökü>/01_kaynak_kesfi/01_fulltext_listesi.json \
  -o <proje-kökü>/01_kaynak_kesfi/01_fulltext_listesi.html

# Altın standart rapor: doğrula + üret + temizlik seçeneği
.venv/bin/chapter-report build <proje-kökü>/03_taslak_denetimi/taslak/rapor.json --check
.venv/bin/chapter-report build <proje-kökü>/03_taslak_denetimi/taslak/rapor.json \
  -o <proje-kökü>/03_taslak_denetimi/taslak/05_bolum_raporu.html \
  --markdown <proje-kökü>/03_taslak_denetimi/taslak/05_bolum_raporu.md
.venv/bin/chapter-report cleanup --manifest 05_bolum_raporu.manifest.json \
  --scope intermediate --dry-run

# Örnek
python3 scripts/build_fulltext_list.py \
  examples/fulltext-list.example.json \
  -o examples/fulltext-list.example.html
```

Araçların tam listesi ve girdi/çıktı şemaları: [`docs/tool-catalog.json`](docs/tool-catalog.json).
