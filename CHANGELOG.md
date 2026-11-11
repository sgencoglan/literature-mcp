# Değişiklik Günlüğü

## v2.10.0 — 2026-11-11

### Değişti

- **`local_research.py` bölündü.** 3.100 satırlık tek dosya sorumluluk bazlı
  modüllere ayrıldı: `_common` (ayarlar/yardımcılar), `_projects` (kayıt ve
  izolasyon), `_crossref`, `_journals`, `_library` (PDF), `_search`,
  `_evidence`, `_mcp_tools`. En büyük modül 788 satır. `local_research.py`
  artık yalnızca **cephe**: 28 genel ve 59 özel adı yeniden dışa aktarıyor,
  bu yüzden `local_research.read_paper` gibi mevcut çağrılar değişmedi.
- **Ayar adları tek kaynakta.** `PAPER_LIBRARY_DIR`, `JOURNAL_RANK_PATH`,
  `LIT_PROJECTS_REGISTRY` ve benzeri ayarlar `_common` içinde tutuluyor; cephe
  üzerinden okuma/yazma oraya yönlendiriliyor. Önceden `local_research` bir
  kopyayı tutardı; testlerin veya kullanıcıların atadığı yol araçlara
  ulaşmazdı. `mock.patch.object` ile geri alma da güvenli (silme işlemi
  varsayılana döner).
- **Tek hız-limit tablosu.** Yeni `rate_limit` modülü host başına aralıkları,
  `Retry-After` tavanını ve cooldown süresini tanımlıyor. `server.py` ve
  `scripts/download_open_access.py` aynı tabloyu kullanıyor; betiğin
  `--sleep` varsayılanı artık Unpaywall/OpenAlex aralığından (0,5 sn) geliyor.
  Betik 429/5xx yeniden denemelerinde `Retry-After` başlığını onurlandırıyor.
- **SCImago önbelleği yol bazlı.** `JOURNAL_RANK_PATH` başka bir dosyaya
  çevrildiğinde eski veri kümesi dönmüyor.
- **Betik sürümü tek kaynaktan.** `download_open_access.py` User-Agent'ı
  paket sürümünü kullanıyor (`literature-mcp/2.10.0 (open-access downloader)`);
  paket kurulu değilse `dev` yazıyor.
- 10 yeni test: modül düzeni/cephe uyumu, ayar yönlendirmesi, önbellek
  anahtarı ve paylaşılan hız politikası. Test süresi 38 sn → 4,7 sn
  (ağa çıkan `read_paper` çağrısı artık mock'lanıyor).

## v2.9.0 — 2026-11-11

### Değişti

- **Tek arama motoru.** `search_all` ile `search_literature` aynı 150 satırlık
  boru hattını iki kez taşıyordu (109 satır birebir aynı). Ortak mantık yeni
  `sciencedirect_meta.pipeline` modülüne taşındı: görev kurulumu, paralel
  toplama, tekilleştirme, PII zenginleştirme, filtre, skorlama ve kapsam
  raporu artık tek yerde. İki araç yalnızca kendi yanıt alanlarını ekliyor.
  v2.8.0'daki "Crossref bir araçta eksik kaldı" hatası bu yapıyla tekrar
  edemez.
- **Tekilleştirme anahtarı güçlendi.** DOI yoksa başlık tek başına yeterli
  değildi; aynı başlıklı editöryel/düzeltme ve farklı yıllardaki çalışmalar
  birleşiyordu. Anahtar artık `başlık + yıl + ilk yazar` taşıyor. Başlığı boş
  kayıtlar birleştirilmiyor, atlanıyor.
- **Event loop sorunu giderildi.** `httpx.AsyncClient` ve `asyncio.Lock`
  nesneleri ilk kullanıldıkları loop'a bağlı kalıyordu; tekrarlanan
  `asyncio.run` çağrılarında "Event loop is closed" ve taşınmamış transport
  uyarıları çıkıyordu. İstemci ve kilitler artık loop değişince yeniden
  oluşturuluyor (`client_for_loop`, `_host_lock`).
- **arXiv politikası.** İstekler 5 sn aralıkla sıraya konuyor ve User-Agent
  iletişim e-postasını içeriyor (`literature-mcp/<sürüm> (mailto:...)`).
  Önceden 3 sn aralık + genel UA ile 429 alınıyordu.
- **`search_diagnostics` aracı (yeni).** Etkin `setup.txt`, hangi API
  anahtarlarının tanımlı olduğu (değerler asla döndürülmez), varsayılan
  kaynak listesi, host/kaynak cooldown'ları ve güvensiz izin durumu tek
  çağrıda görülür. "Neden az sonuç geldi?" sorusu kodu okumadan yanıtlanır.
- **`setup.txt` sertleştirildi.** Grup/diğer kullanıcıların okuyabildiği bir
  dosyadaki anahtarlar artık **yüklenmez**; durum `setup_insecure=true` olarak
  raporlanır ve log'da `chmod 600` önerilir. Bilinçli istisna için
  `LIT_ALLOW_INSECURE_SETUP=1`.
- **Tek sürüm kaynağı.** `__version__` artık kök `VERSION` dosyasından
  okunuyor; `scripts/check_version.py` beş kopyanın (VERSION, iki
  `pyproject.toml`, iki `__version__`, README/AGENTS banner'ı) uyuşmasını
  zorunlu kılıyor. `--set X.Y.Z` hepsini birlikte günceller.
- **Statik kontroller.** `ruff.toml` + `scripts/lint.sh`; `F821` (tanımsız ad),
  `F841` (kullanılmayan değişken), `F401`, `B904` ve import düzeni denetleniyor.
  Bu turda 3 tanımsız ad (PaperQA anotasyonları), 3 kullanılmayan değişken ve
  1 `raise ... from` eksiği düzeltildi.
- **CI matrisi.** GitHub Actions artık Python 3.10–3.13 arasında çalışıyor ve
  `ruff` kuruyor.
- **Katalog kayması testi.** `docs/tool-catalog.json` ile sunucunun gerçek
  araç şemaları karşılaştırılıyor; katalog elle güncellenmeyi unutursa test
  kırılıyor.
- `dump_tool_catalog.sh` göreli yorumlayıcı yolu verildiğinde
  (`PAPER_PY=.venv/bin/python`) alt dizinde dosyayı bulamıyordu; yollar
  mutlaklaştırılıyor.
- `deep_research` aynı facet sorgusunu iki kez göndermiyor.
- Hata yanıtlarına kararlı `error_code` alanı eklendi
  (`unknown_project`, `rate_limited`, `error`); ajanlar Türkçe hata metnini
  ayrıştırmak zorunda değil.

## v2.8.0 — 2026-11-11

### Değişti

- **Tüm veritabanları varsayılan.** `search_all`, `search_literature` ve
  `deep_research` artık yedi kaynağın tümünü sorgular: OpenAlex, Semantic
  Scholar, PubMed, Europe PMC, Crossref, arXiv ve ClinicalTrials.gov.
  `search_all` önceden Crossref'i hiç çağırmıyor, arXiv/ClinicalTrials'ı ise
  varsayılan olarak atlıyordu; `sources` parametresi eklendi.
- **`priority_only` varsayılanı `false`.** Sonuçlar artık tüm yayıncılardan
  döner; yalnızca beş öncelikli platformu istemek için açıkça
  `priority_only=true` verilir. Önceki varsayılan, sorgulanan kaynakların
  sonuçlarını sessizce eliyordu.
- **Proje `setup.txt` önceliği.** Yeni `project_directory` parametresi
  (`search_all`, `search_literature`, `deep_research`) o proje klasöründeki
  `setup.txt` dosyasını çağrı anında okur; `bootstrap.load_for_project`
  önceki bir `setup.txt` yüklemesinin yazdığı anahtarları geçersiz kılar,
  ancak süreç ortamında açıkça verilen değerleri korur. Yanıtta `setup_file`
  alanı etkin dosyayı gösterir. `LIT_PROJECT_ROOT` yedek olarak kullanılır.
- **Nazik hız limitleri.** Tüm HTTP istekleri `polite_get` üzerinden geçer:
  host başına aralık (OpenAlex ~2/sn anahtarsız, ~10/sn anahtarlı; NCBI
  ~3/sn → ~10/sn; Europe PMC ve Crossref ~5–8/sn; arXiv 3 sn), `Retry-After`
  desteği ve 5xx yeniden denemesi. Kalıcı 429 artık tool hatası değil:
  kaynak `rate_limited` olarak raporlanır, 20 sn devre dışı kalır ve kalan
  facet'ler onu tekrar zorlamaz.
- `coverage.per_source`/`notes` her kaynağın `ok`/`error`/`rate_limited`
  durumunu ve nedenini gösterir; `search_literature` yanıtına
  `sources_requested` ve `setup_file` eklendi.
- Testler: varsayılan kaynak kümesi, `priority_only=false`, proje
  `setup.txt` yükleme/öncelik ve `polite_get`/`run_source` hız limiti
  davranışı için yeni birim testleri.

## v2.7.1 — 2026-11-10

### Değişti

- Üreticiler artık her çalıştırmada yeni sürüm biriktirmez. `output_naming`
  modülüne `write_versioned` / `write_versioned_pair` eklendi: içerik
  değişmediyse mevcut çıktı korunur (`Değişiklik yok; mevcut sürüm korundu`),
  değiştiyse yeni sürüm yazılır ve eskiler `<akış>/arsiv/` altına taşınır.
  Dosya silinmez.
- JSON karşılaştırmasında `generated_at`, `timestamp`, `created_at`,
  `updated_at`, `searched_at`, `oa_checked_at`, `approved_at` gibi değişken
  alanlar yok sayılır; aksi hâlde her koşu “yeni sürüm” sayılırdı.
- Bağlanan üreticiler: `build_assignment_matrix.py` (JSON+HTML çifti birlikte),
  `build_search_coverage.py` (JSON+HTML+Markdown), `build_fulltext_list.py`,
  `build_writing_plan.py`, `build_topic_discovery.py`,
  `build_study_design.py`.
- `docs/output-spec.md` “Tek sürüm kuralı” ile güncellendi.

## v2.7.0 — 2026-11-09

### Değişti

- Üreticiler önceki çıktıları silmez; her çalıştırma yeni sürüm ekler. Aynı
  saniyedeki ikinci çalıştırma `-01` sonekli yeni dosya üretir
  (`build_search_coverage.py`); `build_fulltext_index.py` aynı adı `--force`
  olmadan yazmaz. `00_kaynak_listeleri` giriş sayfası tüm sürümleri listeler
  ve "önceki sürümler silinmez" notunu taşır.
- Fulltext listesi HTML'i: DOI açık adresi yerine kısa `doi` etiketi ve
  yalnızca DOI metni gösterilir (tıklanamaz). DOI düğmesi ve yayıncı/veritabanı
  düğmesi korunur; `publisher_url` yoksa DOI ön ekine göre platform linki
  türetilir (ScienceDirect, SpringerLink, Wiley, Taylor & Francis, SAGE, BMC).
- Kapsam raporu HTML/Markdown çıktısında ayrı "Seçilen makaleler" tablosu yok.
  Seçilen kaynaklar normal sonuç tablosunda sıra numarasının yanında yeşil
  `seçildi` etiketiyle işaretlenir.
- Fulltext listesi HTML'i: OA PDF artık uzun açık adres yerine diğerleri gibi
  düğme; her kaynağın altındaki açıklama bloğuna "Neden seçildi" ve
  "Kalite skoru" satırları eklendi (skor `score` alanından, isteğe bağlı).
- Açık erişimli PDF'ler DOI tabanlı adlandırılır ve özel karakterler atılır:
  `10.4073/csr.2011.4` → `10.4073csr.2011.4.pdf`.
- Fulltext listesi, `fulltext/` klasöründe PDF'i bulunan kaynakların
  "İndirildi" kutusunu sayfa açılışında otomatik işaretler; "işaretleri
  temizle" bu işaretleri korur. DOI dosya adı eşleşmesi `_`, ayırıcısız ve
  `-` varyantlarını tanır.
- `download_open_access.py` varsayılan olarak akış 3'ün otomatik
  oluşturulan `03_kaynak_kesfi/fulltext/` klasörüne indirir; `--workflow 4`
  ve `--workflow 5` sırasıyla taslak ve analiz akışının `fulltext/` klasörünü
  seçer. İndirme raporu her akışta doğrudan o akışın klasörüne
  `oa_indirme_raporu_<zaman>.json` olarak yazılır.
- `paperqa_create_workspace` beş akış klasörünü ve her akışın `fulltext/`
  alt klasörünü açar; `fulltext_directories.source/draft/analysis` alanlarını
  döndürür.
- `search_all` ve `search_literature` varsayılan kaynak listesine Semantic
  Scholar eklendi; arXiv ve ClinicalTrials.gov isteğe bağlıdır. Sonuçlar artık
  `score` alanına göre sıralanır.

### Eklendi

- `schemas/writing-plan.schema.json` ve `scripts/build_writing_plan.py`:
  akış 2 iskeleti. Her alt başlık için `purpose`, `target_words`,
  `evidence_needs` ve `assigned_dois`; `plan_status` kullanıcı onayı olmadan
  `approved` yapılmaz.
- `scripts/build_assignment_matrix.py`: akış 3 atama matrisi. Alt başlık
  metni ile aday başlık/özet örtüşmesi, istenen çalışma türü bonusu ve
  quartile bonusuyla DOI atar; karşılanmayan `min_count` ihtiyaçlarını
  `evidence_gaps` olarak raporlar. `--update-plan` atamayı plana geri yazar.
- `scripts/check_plan_compliance.py`: akış 5 plan uyumu denetimi. Yazılmayan
  alt başlık, ±%25 kelime sapması, planda olmayan bölüm (kapsam kayması) ve
  kullanılmayan atamaları raporlar; `--strict` ile hata kodu döndürür.
- `scripts/project_layout.py` ve `sciencedirect_meta/layout.py`: klasör
  düzeninin tek doğruluk kaynağı. `scripts/tests/test_scripts.py` üç kopyanın
  (scripts, sciencedirect-meta, paperqa-local) uyumunu denetler.
- `examples/writing-plan.example.json/.html`: akış 2 biçim örneği;
  `validate_all.sh` şema ve HTML güncelliğini denetler.
- `paperqa_promote_fulltext` ve `scripts/promote_fulltext.py`: akış 3'te
  indirilen açık erişim PDF'lerini akış 4/5 `fulltext/` klasörüne kopyalar
  (isteğe bağlı `--move`) ve dosyayı DOI adına çevirir
  (`10.4073csr.2011.4.pdf`). DOI önce dosya adından, sonra PDF metninden,
  sonra akış 3 başlığından çözülür; kullanıcının adlandırılmamış PDF'leri de
  düzeltilir. Hiçbir dosya silinmez, hedefte aynı DOI varsa atlanır.
- Beş iş akışlı proje düzeni: `01_konu_belirleme/`, `02_yazim_plani/`,
  `03_kaynak_kesfi/`, `04_taslak/`, `05_analiz/`. Tüm betikler, MCP araçları,
  şemalar ve belgeler bu düzene geçti; `taslak/` alt klasörü kaldırıldı,
  çıktılar doğrudan akış klasörüne yazılır. Eski `00/01/02/03` adları
  kullanılmıyor.
- Ürün türü artık varsayılan değil: akış 1'de `kitap_bolumu`,
  `uygulama_rehberi`, `derleme_makale` veya `ampirik_makale` kullanıcıya
  sorulur; tür ve hedef kelime sabitlenmeden akış 2 başlamaz.
- `sciencedirect_meta.bootstrap`: MCP sunucusu süreç başında proje
  `setup.txt` dosyasını kendisi bulup okur (`LIT_SETUP_FILE`,
  `LIT_PROJECT_ROOT`, kayıtlı projeler, çalışma dizini üst klasörleri).
  Yalnızca bilinen anahtarlar yüklenir; tanımlı ortam değişkeni her zaman
  önceliklidir. Böylece OpenAlex/PubMed/Semantic Scholar anahtarları için
  ayrıca `opencode.json` düzenlemek gerekmez.
- Semantic Scholar istemcisi anahtar varken istekleri **2 sn aralıkla**
  sıraya koyar (API sınırı 1 istek/sn), `Retry-After` başlığına uyar ve
  `429` sonrası 8 sn devre dışı kalır (anahtarsız 120 sn). Böylece çok
  facet'li `deep_research` çağrılarında kaynak tümden düşmez.
- `search_semantic_scholar`: Semantic Scholar Graph API araması. DOI, atıf ve
  influential atıf sayısı, OA PDF, venue, yazarlar, paperId ve URL döndürür.
  `SEMANTIC_SCHOLAR_API_KEY` isteğe bağlıdır; hata durumunda boş liste döner
  ve diğer kaynakları etkilemez.
- `search_arxiv`: arXiv Atom API araması. arXiv id, PDF/abs URL, kategori,
  yayın/güncelleme tarihi döndürür; kayıtlar `is_preprint=true` işaretlenir.
- `search_clinicaltrials`: ClinicalTrials.gov API v2 araması. NCT id, durum,
  çalışma türü, faz, koşul ve girişim bilgisi döndürür.
- `coverage` bloğu: `search_all`, `search_literature` ve `deep_research`
  cevaplarında kaynak bazında dönen kayıt/tekil DOI/yüksek kalite sayısı,
  toplam tekil DOI, `query_variants`, zaman ve `evidence_scarcity`.
- `coverage.query_expansion`: orijinal sorgu, genişletilmiş sorgular, MeSH
  terimleri, dil dönüşümü, kullanılan dönüşümler ve notlar. `search_all`,
  `search_literature` ve `deep_research` `query_expansion` parametresiyle
  açıkça verilebilir; verilmezse orijinal sorgu ve `query_variants` üzerinden
  türetilir.
- `coverage.evidence_density`: Q1 sayısı/oranı, son 5 yıl sayısı/oranı,
  RCT, sistematik derleme/meta-analiz, klinik çalışma ve preprint sayıları,
  çalışma türü dağılımı, katı yüksek-kalite sayısı (Q1/Q2 + atıf + RCT/SR/MA)
  ve son 3 yıl `trend` sinyali (artıyor/azalıyor/sabit/belirsiz).
- `coverage.closest_studies`: kanıt sınırlıysa skora göre en yakın 5 çalışma
  (başlık, yıl, DOI, skor, çalışma türü). `evidence_scarcity_message` bu
  listeyi ve “Araştırma boşluğu olasılığı yüksektir” uyarısını içerir.
- `coverage.per_source` artık `status` (ok/partial/error/rate_limited), `note`,
  `requested_limit`, `duration_ms` ve `rate_limited` alanlarını da taşır;
  `coverage.skipped_sources` ve `coverage.warnings` hata, hız limiti ve
  sorgulanmayan kaynakları açıkça gösterir. Bazı sorgularda hata verip yine de
  kayıt döndüren kaynak "partial" olarak işaretlenir; böylece gerçek kapsam
  "hata" diye gizlenmez.
- `coverage.publisher_distribution`: beş öncelikli platform + diğer +
  bilinmeyen dağılımı, açık erişim oranı, preprint oranı ve PDF bağlantısı
  oranı. HTML raporunda "Publisher ve fulltext erişim dağılımı" bölümü olarak
  görünür.
- `coverage.evidence_density.high_quality_strict_total`: Q1/Q2 + en az 10 atıf
  + RCT/sistematik derleme koşulunu sağlayan katı yüksek-kalite sayısı. Ayrıca
  son 3 yıl `trend` sinyali (yön + yıllık sayılar) eklendi.
- `scripts/build_search_coverage.py` artık Markdown çıktısı da yazar
  (`--no-markdown` ile kapatılır), `--compare <json>` ile iki query setinin
  kapsam farkını (`..._karsilastirma.json/html`) üretir ve `--auto-report`
  ile özeti stdout'a basar.
- `score_result` / `score_results`: 0.35 anlamsal alaka + 0.25 log atıf +
  0.15 güncellik + 0.15 SCImago quartile + 0.10 çalışma türü. Preprint skoru
  0.85 ile çarpılır; yüksek kalite eşiği 0.60 ve çalışma türü bileşeni 0.40.
- `score_results_best`: çok sorgulu aramalarda (`deep_research`) her kayıt en
  iyi eşleşen facet sorgusuna göre puanlanır ve kazanan sorgu `scored_query`
  alanına yazılır. Önceden İngilizce kayıtlar Türkçe soruya göre puanlandığı
  için skorlar sıfıra yaklaşıyordu.
- `scripts/build_search_coverage.py` ve
  `schemas/search-coverage.schema.json`: kapsam raporunu
  `01_arama_kapsam_raporu_<zaman>.json/html` olarak yazar.
- `download_open_access.py`: ASCII dışı karakter içeren PDF URL'leri artık
  yüzde-kodlanır (Türkçe karakterli DergiPark linklerinde `UnicodeEncodeError`
  alınıyordu). Yayıncı 401/403 döndürürse Unpaywall'un listelediği sonraki açık
  kopya denenir; hepsi engellenirse rapora "tarayıcıdan indirin" notu yazılır.
- `_get_with_retry`: 429 için `Retry-After` başlığına uyar, 5xx ve geçici
  DNS/bağlantı hatalarında geri çekilmeli yeniden dener; kısa ağ kesintileri
  kaynağın tamamen kaybolmasına yol açmaz.
- OpenAlex araması `search.semantic`, `type`, `cited_by_count`, `has_abstract`
  ve `is_oa` filtrelerini destekler; `search_openalex_advanced` helper'ı
  eklendi.
- İndirilen PDF'ler için JSON'da `oa_downloaded` ve `oa_local_file` alanları;
  `schemas/fulltext-list.schema.json` bu alanları belgeler.
- `scripts/setup_paperqa.sh` ve `requirements-paperqa.txt`: PaperQA2 indeksi
  için CPU-only PyTorch (`download.pytorch.org/whl/cpu`), `sentence-transformers`,
  MCP ve PyMuPDF kurulumu. `--check` torch'un CUDA'sız olduğunu ve tüm
  importların hazır olduğunu doğrular; CUDA paketleri indirilmez.
- Üretilen HTML, Markdown, manifest ve rapor adlarına varsayılan
  `_YYYYMMDD-HHMMSS` zaman soneki. Aynı saniyedeki çakışmalar `-01`, `-02`
  alır; `--no-timestamp` sabit ad üretir. `scripts/output_naming.py` ve
  `report_kit.naming` ortak davranışı sağlar.
- Bölüm raporu HTML'lerine DOI kopyalama düğmesi. Panoya
  kopyalama için tek, denetimli gömülü betik kullanılır; chapter-report kalite
  kapısı bunun dışındaki `<script>`, `<iframe>` ve `on*` özniteliklerini
  reddetmeye devam eder.
- `scripts/download_open_access.py`: Unpaywall (önce) ve OpenAlex (yedek)
  üzerinden yalnızca açık erişimli PDF'leri varsayılan olarak iş akışı 1'in
  `01_kaynak_kesfi/fulltext/` klasörüne indirir. `--dry-run`,
  `--update-json`, `--workflow`, zaman sonekli rapor ve
  maskelenmiş e-posta desteği vardır. Doğrudan PDF vermeyen açılış
  sayfalarında `citation_pdf_url`/PDF bağlantısı bir kez çözülür.
- `scripts/validate_all.sh`: `parpaqa`/`parpqa`/`Paperqa` yazım koruması ve
  `scripts/tests` birim testleri.
- README, AGENTS, çıktı sözleşmesi ve iş akışı belgelerinde API anahtarı
  gereksinimleri: OpenAlex, PubMed/NCBI, Europe PMC ve Crossref anahtarsız
  çalışır; e-posta (`mailto`) önerilir. Unpaywall anahtar istemez, e-posta
  zorunludur.

- `scripts/setup_credentials.py`: ilk kurulumda iletişim e-postasını,
  OpenAlex ve PubMed API anahtarlarını soran; bilgileri yalnızca OpenCode MCP
  yapılandırmasına yazan, dosyayı `600` izniyle koruyan ve yedek alan betik.
  Proje kökündeki `setup.txt` dosyasını otomatik okur; dosya yoksa sorar.
  `--check`, `--project`, `--from-file`, `--non-interactive` ve `--config`
  seçenekleri vardır.
- OpenAlex ve PubMed için isteğe bağlı API anahtarı desteği
  (`OPENALEX_API_KEY`, `PUBMED_API_KEY`). NCBI E-utilities isteklerine
  `tool` ve `email` parametreleri eklendi; 429 yanıtlarında kısa geri
  çekilme ile yeniden deneme yapılıyor. Anahtarlar tanımlı değilse araçlar
  eskisi gibi çalışır.

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
