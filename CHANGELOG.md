# Değişiklik Günlüğü

## v2.6.0 — 2026-10-31

### Eklendi

- İş akışı 0'da kullanıcı bir çalışma başlığı seçtikten sonra yöntem ve
  tasarım önerisi üretimi. Öneri; araştırma soruları, gerekçeli desen,
  örneklem/güç hesabı, ölçümler ve geçerlik sınırları, veri toplama, analiz,
  etik ve kullanıcı karar noktalarını kapsar.
- Yöntem tasarımı için JSON Schema, çevrimdışı HTML üreticisi ve örnek çıktı.
- Tasarım durumu `proposed` olarak saklanır; kullanıcı/araştırma ekibi
  onaylamadan kesinleştirilmez.

## v2.5.1 — 2026-10-31

### Düzeltildi

- Yeniden yazılan cümle örneğindeki segment metni tam cümleyle eşleştirildi;
  kalite kapısındaki segment bütünlüğü hatası giderildi.
- Düzenlenen cümle vurgusu testler ve eski HTML tüketicileriyle uyumlu yalın
  `<mark>` etiketi kullanıyor; MCP eklemeleri ayrı sınıflı renklendirmeyi koruyor.

## v2.5.0 — 2026-10-31

### Eklendi

- Üç iş akışında da her kaynağın bu projedeki katkısını, desteklediği ve
  desteklemediği çıkarımları, sınırlılıklarını ve değerlendirme dayanağını
  gösterme. İş akışı 1'de kaynak listesine; iş akışı 2 ve 3 raporlarında Ek 4'e
  eklendi.
- Özet/metaveri temelli kaynak yorumlarını sayfa doğrulamalı PDF kanıtından
  ayıran `assessment_basis` alanı ve rapor sunumu.
- Akış 3 raporunda yeniden düzenlenen ifadeler ile MCP'nin anlamlı yeni
  eklemelerini farklı renklerde gösterme.
- Akış 3 için paragraf/makale bağlam değerlendirmesi ve bağlama daha uygun
  kaynak adaylarını Ek 3'te sunma.

### Değişti

- Fulltext listesi ve bölüm raporu şemaları; kaynak katkısı ve sınır
  değerlendirmelerini zorunlu kılacak şekilde genişletildi.
- Rapor örnekleri, iş akışı yönergeleri ve kabul ölçütleri güncellendi.

## v2.4.1 — 2026-10-31

### Düzeltildi

- Proje kökü içinde tutulan indeksler için çakışma testleri, aynı çalışma
  alanını kullanan projelerle doğrulanacak şekilde güncellendi.

## v2.4.0 — 2026-10-31

### Eklendi

- Üç aşamalı çalışma akışı: kaynak keşfi, PDF kanıtlarıyla bölüm taslağı ve
  mevcut taslağın cümle cümle denetimi.
- `paperqa_create_workspace`, kullanıcı proje kökünde iş akışı klasörlerini
  başlatır ve 1/2/3 akış seçimini sunar; akış seçilmeden PDF kaydı veya analiz
  yapılmaz.
- Akış 2 ve 3 için ayrı `fulltext/` ve `taslak/` alt klasörleri; ayrı PaperQA
  proje adları, manifestler ve indeksler.
- Akış 2 taslağını HTML ve Markdown olarak üretme; HTML'e Ek 1 kaynak–taslak
  kartları ile sayfa doğrulamalı iddia–kanıt matrisi ekleme.
- Taslak cümlelerini kaynak metnini kopyalamadan, paragraf bağlamına uygun
  özgün ifadelerle yazma yönergeleri.
- `chapter-report` kart etiketlerini Türkçe taslak raporlarına göre özelleştirme.
- `paperqa_register_project` için zorunlu `output_directory`; manifest ve indeks
  kullanıcı proje kökü altında, akıştan izole tutulur.

### Değişti

- README, ajan yönergeleri, iş akışı/mimari belgeleri, araç kataloğu ve örnek
  proje yapılandırması üç akışlı işleyişle eşleştirildi.
- Fulltext listesi şemasında kaynak keşfi çıktıları için yeni alanlar eklendi.

### Düzeltildi

- `chapter-report build`, HTML, Markdown veya manifest hedeflerinden biri
  mevcut olduğunda diğer çıktı dosyalarını yazmadan önce durur. Çıktı yolları
  çakışıyorsa ya da manifeste eklenecek dosya manifest klasörünün dışındaysa
  da üretim başlamadan hata verir.

## Geliştirme aşamasında


## v2.3.0 — 2026-10-28

### Eklendi

- `report-kit`: b1 pilot raporundan uyarlanan sayfa tasarımı — 980 px gövde,
  sans-serif başlıklar, `<mark>` vurgusu, kart/kanıt/not düzeni ve baskı
  kuralları.
- `report-kit`: opsiyonel `notice` kaynak politikası kutusu, sayı rozetleri
  (`summary-strip`), değişiklik kartlarında durum rozeti ve footer.
- `report-kit`: kaynak envanterinde `role` ve `limitation` sütunları; iddia
  matrisinde `location`, `evidence_type` ve `note` sütunları.
- `report-kit`: opsiyonel `next_steps` (Sonraki Adımlar) bölümü.
- `paperqa-local`: tek yerel arka uç olarak llama.cpp, OpenAI uyumlu uç nokta,
  model/bağlam/zaman aşımı ortam değişkenleri ve `paperqa_llm_status` aracı
  (toplam 8 araç).
- `paperqa-local`: `paperqa_ask` için otomatik llama.cpp yaşam döngüsü.
  Sunucu kapalıysa başlatılır, model hazır olana kadar beklenir ve yalnızca
  MCP'nin başlattığı sunucu boşta kalınca durdurulur. Elle başlatılan sunucuya
  dokunulmaz; çökme sonrası kalan sunucu pid dosyasından sahiplenilir.
  `PAPERQA_AUTO_START`, `PAPERQA_AUTO_STOP_IDLE`,
  `PAPERQA_LLAMA_START_TIMEOUT`, `PAPERQA_LLAMA_MIN_FREE_MB`,
  `PAPERQA_LLAMACPP_MODEL`, `PAPERQA_LLAMACPP_SCRIPT`,
  `PAPERQA_LLAMACPP_LOG` ve `PAPERQA_LLAMACPP_PIDFILE` ile ayarlanır.
- `scripts/setup_llamacpp.sh`, `scripts/start_llamacpp.sh`,
  `scripts/benchmark_local_llm.py`.
- `docs/local-llm.md`: llama.cpp kurulumu, model seçimi, benchmark ve OpenCode
  `/models` entegrasyonu.

### Değişti

- Yerel LLM varsayılanları hafifletildi: `-t 2` (2 fiziksel çekirdek),
  `-c 8192`, `-ngl 0`; tek Qwen2.5-3B-Instruct Q4_K_M modeli tutuldu.
- `paperqa-local` MCP sunucusu PyMuPDF ve PaperQA2'yi tembel yükler; açılış
  süresi ~35 sn'den ~5 sn'ye indi ve OpenCode bağlantı zaman aşımına takılmaz.
- `paperqa-local`: aynı proje adı farklı bir klasör veya alt klasör taramasıyla
  yeniden kaydedilirse `refresh_manifest=True` zorunlu; eski manifestin yeni
  klasörle karışması engellenir. Aynı veya iç içe `index_directory`/`index_name`
  yolu kullanan ikinci proje reddedilir.
- `paperqa-local`: manifest okunurken mutlak yol, proje klasörü dışına çıkan
  `..` yolları ve çift kayıtlar reddedilir. Kayıt sırasında aynı DOI'ye çözülen
  yinelenen dosyalar manifeste alınmaz ve raporlanır.
- `paperqa_build_index(rebuild=True)` eski indeksi silmek yerine `.bak-*`
  klasörüne taşır; kurulum çökerse eski indeks geri getirilir, bazı dosyalar
  başarısız olursa yedek korunur.
- Proje yeniden kaydedilince veya indeks kurulunca proje ayarları, doküman
  önbelleği ve bellek içi meta veriler temizlenir.
- `paperqa_status`, manifest–indeks uyuşmazlıklarını (`missing_from_index`,
  `index_only_files`) ve `healthy` durumunu raporlar.
- `paperqa_search`, `paperqa_read_pages`, `paperqa_ask` ve `paperqa_llm_status`
  sayısal girdileri doğrular ve sınırlar; `paperqa_ask` her çağrıda ayarların
  kopyasını kullanır. `paperqa_read_pages` tek çağrıda en fazla 50 sayfa okur.
- `paperqa_register_project` artık `output_directory` parametresi alır;
  verilmezse çıktılar başta verilen proje klasörüne (`paper_directory`) yazılır.
  `export_review(project=...)` de aynı klasöre yazar; `output_path` bu klasörün
  dışına çıkamaz.
- `paperqa-local` için 31 bağımlılıksız birim testi eklendi (registry, manifest,
  yol güvenliği, DOI adayları, proje izolasyonu, indeks çakışması, yedekleme,
  önbellek temizliği, yinelenen DOI, otomatik başlatma/durdurma, atexit
  temizliği, çıktı klasörü ve giriş doğrulama).
- `paperqa_ask`, sunucu başlatılamazsa ağır doküman/embedding yüklemesi
  yapmadan açık bir hata, durum ayrıntısı ve başlatma ipucu döndürür. Girdiler
  sunucu başlatılmadan önce doğrulanır.
- `report-kit` HTML üreticisi semantik `<article>`, `<mark>` ve `<footer>`
  etiketleri kullanır; kalite kapısı bu etiketleri de denetler.
- Kalite kapısı, iddia `location`/`evidence_type`/`note` alanları için uyarı
  üretir; `--strict` bu uyarıları hata sayar.
- `examples/chapter-report.example.json`, HTML ve Markdown örnekleri yeni
  alanlarla güncellendi.
- `docs/report-standard.md`, `docs/output-spec.md`, `packages/report-kit/README.md`
  ve `AGENTS.md` yeni rapor standardına göre güncellendi.
- OpenCode örnek yapılandırması `providers.llamacpp` ve 8192 bağlamla
  güncellendi; `paperqa-local` 8 araç olarak belgelendi.

### Kaldırıldı

- Ollama arka ucu, `PAPERQA_LOCAL_BACKEND` değişkeni, Ollama model listesi ve
  `docs/ollama.md`; sistemde tek yerel arka uç llama.cpp'dir.
- LFM3-1.7B modeli ve tüm betik/belge referansları (Türkçe çıktı ve düşünme
  bloğu davranışı yetersizdi).

### Korundu

- Proje izolasyonu, DOI/sayfa doğrulaması, `paperqa_ask` yasağı ve yerel yol
  yasağı.
- Public depoda PDF, indeks, kişisel `projects.json`, manifest veya analiz
  verisi bulunmaması.
- `sciencedirect-meta` 19 araç.

## v2.2.0 — 2026-10-22

### Eklendi

- Kalite kapısı, her değişiklik kartındaki DOI'nin kaynak envanterinde
  bulunmasını zorunlu tutar; envanterde olmayan DOI raporu düşürür.
- Bu çapraz kontrol için birim testi eklendi.

### Değişti

- `docs/report-standard.md` ve `packages/report-kit/README.md` yeni DOI
  envanteri kuralına göre güncellendi.

## v2.1.0 — 2026-10-22

### Eklendi

- `chapter-report --markdown`: HTML ile aynı veriden üretilen düzenleme katmanı.
- Markdown çıktısı manifestte `markdown` türüyle izlenir; `--cleanup intermediate`
  HTML ve Markdown'ı korur, yalnızca CSV/JSON ara dosyalarını siler.
- Silinmiş manifest dosyaları temizlikte hata vermek yerine atlanır.

### Değişti

- Örnek rapor `examples/chapter-report.example.md` ile genişletildi.
- README, output-spec, report-standard, workflows ve AGENTS Markdown eşlik
  dosyasına göre güncellendi.

## v2.0.0 — 2026-10-22

### Eklendi

- `packages/report-kit`: altın standart bölüm raporu üreteci (`chapter-report`).
- Tek dosyalık HTML şablonu: düzeltilmiş metin, Ek 1 değişiklik kartları,
  Ek 2 kaynak denetimi ve iddia–kanıt matrisi.
- `schemas/chapter-report.schema.json` ve sentetik
  `examples/chapter-report.example.json` / `.html`.
- Kalite kapısı: DOI, sayfa, birebir alıntı, Türkçe çeviri, atıf, yerel yol
  yasağı ve HTML dengesi denetimi.
- Manifest tabanlı güvenli temizlik: `--cleanup keep|ask|intermediate|all`,
  `--dry-run`, `--yes`, hash doğrulaması ve path traversal koruması.
- `docs/report-standard.md`, `docs/ollama.md`.
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `VERSION`.

### Değişti

- README public v2 kurulumu, altın standart rapor ve temizlik akışıyla
  güncellendi.
- `AGENTS.md`, `docs/output-spec.md`, `docs/workflows.md`,
  `docs/architecture.md` yeni rapora göre güncellendi.
- Yerel model önerisi 1.5B'den 3B'ye yükseltildi; 7B'nin bu donanım sınıfında
  uygun olmadığı belgelendi.

### Korundu

- `sciencedirect-meta` 19 araç, `paperqa-local` 7 araç.
- Proje izolasyonu, DOI/sayfa doğrulaması ve `paperqa_ask` yasağı.
- MIT lisansı ve public depoda PDF/indeks/kişisel veri bulunmaması.
