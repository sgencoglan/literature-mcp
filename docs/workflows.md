# İş Akışları

Bu belge beş iş akışını adım adım tanımlar. Araç adları MCP araç adlarıdır.
Her akış kendi klasörüne yazar ve bir sonrakine **kapı** ile devreder.

```text
1. Konu belirleme        → 01_konu_belirleme
2. Yazım planı           → 02_yazim_plani
3. Kaynak keşfi + seçim  → 03_kaynak_kesfi
4. Taslak yazma          → 04_taslak
5. Taslak analizi        → 05_analiz
```

**Temel kural:** Plan yoksa kaynak indirilmez; atama yoksa taslak yazılmaz;
plan onayı yoksa akış 3 başlamaz.

---

## Akış 1 — Konu belirleme

**Amaç:** Neyin, hangi türde ve hangi uzunlukta yazılacağını sabitlemek.
Tür ve hedef uzunluk sabitlenmeden iskelet kurulamaz.

### Adım 1: Çerçeveyi al

Şunları netleştirin: geniş konu, hedef grup/bağlam, hedeflenen sonuç, coğrafi
kapsam, kısıtlar. Belirsiz başlıkları soru olarak sorun; kullanıcı adına konu
seçmeyin.

### Adım 2: Ürün türünü sor (zorunlu)

Varsayılan **yoktur**; kullanıcıya açıkça sorun:

| Kod | Tür | Tipik yapı | Tipik uzunluk |
|---|---|---|---|
| `kitap_bolumu` | Kitap bölümü | Serbest, tematik alt başlıklar | 4.000–7.000 |
| `uygulama_rehberi` | Uygulama rehberi | Sorun → tanıma → müdahale → yönlendirme + kontrol listesi | 4.000–7.000 |
| `derleme_makale` | Derleme makalesi | Giriş–Yöntem–Bulgular–Tartışma | 6.000–9.000 |
| `ampirik_makale` | Ampirik makale | IMRaD + yöntem tasarımı zorunlu | 6.000–9.000 |

Tür seçilmeden akış 2'ye geçilmez. `target_total_words` da bu adımda alınır.

### Adım 3: Varsayılan veri tabanlarında ön tarama

`OpenAlex`, `Semantic Scholar`, `PubMed`, `Europe PMC`, `Crossref` varsayılandır;
`arXiv` ve `clinicaltrials` isteğe bağlıdır.

```text
search_literature(query=..., sources=["openalex", "semantic_scholar", "pubmed", "europepmc", "crossref"], priority_only=false, limit=...)
```

Her sorgu için `coverage`, `sources_status`, sonuç sayısı ve hata/not bilgisini
kaydedin. `evidence_scarcity=true` ise bunu kullanıcıya söyleyin.

### Adım 4: Başlık ve kapsam önerileri

Her öneri için: başlık, araştırma sorusu, genel/özel amaç, hedef kitle,
kapsam içi/dışı, önerilen tür, gerekçe. Mutlak özgünlük iddiasında bulunmayın.

### Adım 5: Çıktıyı yaz

```text
01_konu_belirleme/01_konu_<zaman>.json
01_konu_belirleme/01_konu_<zaman>.html
```

JSON `schemas/topic-discovery.schema.json` biçiminde olur ve şu alanları taşır:
`genre`, `target_total_words`, `scope_in`, `scope_out`, `audience`,
`selected_title`.

Ampirik makale seçildiyse ayrıca yöntem tasarımı üretin:

```text
01_konu_belirleme/01_yontem_tasarimi_<zaman>.json/html
```

**Kapı:** kullanıcı başlığı **ve türü** onaylamadan akış 2 başlamaz.

---

## Akış 2 — Yazım planı (iskelet)

**Amaç:** Yazılacak alt başlıkları, her birinin amacını, hedef kelime sayısını
ve gereken kanıt türünü belirlemek. Bu akış **kaynak seçmez**; yalnızca
iskeletin gerçekçi olduğunu doğrulayacak kadar hafif tarama yapar.

### Adım 1: İskeleti kur

Türüne göre yapı:

- `uygulama_rehberi`: tanım → tanıma → yanlılık → önleme → müdahale →
  uygulama → kademeli destek → işbirliği → bağlama özgü → sınırlılıklar →
  kontrol listesi
- `kitap_bolumu`: tematik bölümler, her biri tek bir savı destekler
- `derleme_makale`: Giriş, Yöntem, Bulgular (tematik), Tartışma, Sınırlılıklar
- `ampirik_makale`: IMRaD + yöntem tasarımına bağlı alt başlıklar

Her alt başlık için:
`id` (`S1`…), `heading`, `purpose`, `target_words`, `evidence_needs`.

`evidence_needs` örneği:

```json
[
  {"design": "meta_analysis", "min_count": 1},
  {"design": "rct", "min_count": 1}
]
```

Kabul edilen tasarım kodları: `systematic_review`, `meta_analysis`, `rct`,
`quasi_experimental`, `cohort`, `cross_sectional`, `qualitative`,
`policy_document`, `any`.

### Adım 2: Kelime bütçesini dengele

`target_words` toplamı `target_total_words`'a yakın olmalı (±%10). Dengesizlik
varsa kullanıcıya söyleyin.

### Adım 3: İskeleti doğrula

`--check` yerine doğrudan üretin; üretici hem şema hem kelime bütçesi
tutarlılığını denetler.

```bash
python3 scripts/build_writing_plan.py \
  <proje-kökü>/02_yazim_plani/01_yazim_plani.json \
  -o <proje-kökü>/02_yazim_plani/01_yazim_plani.html
```

Çıktı:

```text
02_yazim_plani/01_yazim_plani_<zaman>.json
02_yazim_plani/01_yazim_plani_<zaman>.html
```

HTML'de her alt başlık bir karttır: amaç, hedef kelime, gereken kanıt türü,
atanmış kaynaklar (akış 3 doldurur), boşluk notu.

**Kapı:** kullanıcı iskeleti onaylar (`plan_status: approved`). Onay yoksa
akış 3 başlamaz.

---

## Akış 3 — Plana göre kaynak keşfi ve fulltext seçimi

**Amaç:** Planın her alt başlığını savunacak kaynakları bulmak, atamak ve
yalnızca atananların PDF'lerini indirmek.

### Adım 1: Alt başlık başına hedefli arama

Her alt başlık için 2–4 sorgu üretin (Türkçe + İngilizce, eş anlamlı + MeSH).
Sonuçları tek havuzda toplayın. `query_expansion` kaydını doldurun.

### Adım 2: Atama matrisi

```bash
python3 scripts/build_assignment_matrix.py \
  <proje-kökü>/02_yazim_plani/01_yazim_plani_<zaman>.json \
  <proje-kökü>/03_kaynak_kesfi/*fulltext_listesi*.json \
  -o <proje-kökü>/03_kaynak_kesfi \
  --update-plan
```

Atama şeffaftır: alt başlık metni (başlık + amaç) ile aday başlık/özet
örtüşmesi + istenen çalışma türü bonusu + küçük quartile bonusu. Çıktı:

```text
03_kaynak_kesfi/00_atama_matrisi_<zaman>.json
03_kaynak_kesfi/00_atama_matrisi_<zaman>.html
```

`--update-plan` ile `assigned_dois`, `status` ve `gap_note` plana geri yazılır.

### Adım 3: Boşlukları çöz

`gap_sections > 0` ise durun ve kullanıcıya sorun:

- kapsam mı daraltılacak (alt başlık çıkarılacak),
- yoksa boşluk gerekçesiyle kabul mü edilecek (`gap_note` yazılır)?

Sessizce boş bırakılmaz.

### Adım 4: Fulltext listesi ve kapsam raporu

Atanan DOI'lerden `schemas/fulltext-list.schema.json` biçiminde liste üretin,
HTML'i yazın ve kapsam raporunu ekleyin:

```bash
python3 scripts/build_fulltext_list.py liste.json -o liste.html
python3 scripts/build_search_coverage.py arama.json \
  -o <proje-kökü>/03_kaynak_kesfi --fulltext-list liste.json --auto-report
python3 scripts/build_fulltext_index.py <proje-kökü>/03_kaynak_kesfi
```

### Adım 5: PDF indirme (yalnızca atananlar)

```bash
python3 scripts/download_open_access.py liste.json --update-json
```

Varsayılan hedef `03_kaynak_kesfi/fulltext/`. Rapor aynı klasörde
`oa_indirme_raporu_<zaman>.json` olarak yazılır.

**Kapı:** her alt başlıkta `min_count` karşılanmadan akış 4 başlamaz.

---

## Akış 4 — Taslak yazma

**Amaç:** Planlanan iskeleti, sayfa doğrulamalı kanıtla doldurmak.

### Adım 1: PDF'leri hedefe al

Üretilen taslak metni `04_taslak/taslak/`, PDF'ler `04_taslak/fulltext/`
altındadır; iki klasör `paperqa_create_workspace` ile birlikte açılır.

### Adım 0: Fulltext'leri oku (zorunlu ilk adım)

```bash
python3 scripts/build_evidence_bank.py <proje-kökü> --workflow 4
```

PaperQA2 indeksi üzerinde alt başlık başına anlamsal arama; sayfa numaralı
alıntı adayları `04_taslak/taslak/_kanit_bankasi.json` içine yazılır. Cümleler
alıntı adayıdır, kanıt değildir.

Yazmadan önce kapasite denetimi:

```bash
python3 scripts/build_evidence_gap_request.py <plan.json> --preflight \
  --fulltext-list <03_kaynak_kesfi>/01_fulltext_listesi.json \
  --fulltext-dir <04_taslak>/fulltext \
  --reading-report <03_kaynak_kesfi>/reading-4/03_fulltext_okuma_REVIEWED.json --workflow 4
```

`plan_change_required` → yazmaya başlama, kullanıcıya sor.
`evidence_shortfall` → akış 3'te yeni kaynak ara, sonra devam et.

PDF'ler `03_kaynak_kesfi/fulltext/` altındaysa:

```bash
python3 scripts/promote_fulltext.py <proje-kökü> --to 4
```

MCP ile: `paperqa_promote_fulltext(project_directory=..., target_workflow="4")`.
Kullanıcının kendi indirdiği adlandırılmamış PDF'ler de DOI adına çevrilir.
Hiçbir dosya silinmez.

### Adım 2: Projeyi kaydet ve indeksle

```text
paperqa_register_project(name="<workflow_project_names.draft>",
                         paper_directory="<proje-kökü>/04_taslak/fulltext",
                         output_directory="<proje-kökü>")
paperqa_build_index(project="<...>")
paperqa_status(project="<...>")
```

`paperqa_status` beklenen dosya sayısını göstermiyorsa devam etmeyin.

### Adım 3: Kanıtı topla

Her alt başlık için `paperqa_search` ile aday paragraf bulun, sonra
`paperqa_read_pages` (veya `read_paper`) ile **sayfa numarasını doğrulayın**.
`paperqa_ask` yalnızca taslaktır; kanıt değildir.

### Adım 4: Yaz

- Her paragraf en az bir doğrulanmış kaynağa bağlanır.
- Kaynak cümlesi kopyalanmaz; bulgu paragraf bağlamına uygun özgün Türkçe ile
  yeniden ifade edilir. Doğrudan alıntı gerekiyorsa kısa tutulur, alıntı olarak
  işaretlenir ve sayfa verilir.
- Plana yeni bir bölüm eklenirse gerekçesi `correction_summary`'ye yazılır.
- Hedef kelime sayısından ±%25'ten fazla sapma varsa gerekçelendirin.

### Adım 5: Çıktı

```text
04_taslak/taslak/04_taslak_<zaman>.json
04_taslak/taslak/04_taslak_<zaman>.md
04_taslak/taslak/04_taslak_<zaman>.html
04_taslak/taslak/04_taslak_<zaman>.manifest.json
```

```bash
.venv/bin/chapter-report build 04_taslak_<zaman>.json --check
.venv/bin/chapter-report build 04_taslak_<zaman>.json \
  -o 04_taslak_<zaman>.html --markdown 04_taslak_<zaman>.md --no-timestamp
```

**Kapı:** `chapter-report` kalite kapısı 0 hata.

---

## Akış 5 — Taslak analizi

**Amaç:** Taslağı iki eksende denetlemek: kanıt ve plan uyumu.

### Adım 1: Plan uyumu

```bash
python3 scripts/check_plan_compliance.py \
  <proje-kökü>/02_yazim_plani/01_yazim_plani_<zaman>.json \
  <proje-kökü>/04_taslak/taslak/04_taslak_<zaman>.json \
  --strict
```

Denetlenenler:

- Planlanan her alt başlık yazıldı mı?
- Bölüm kelime sayısı hedefe yakın mı (±%25)?
- Planda olmayan alt başlık eklendi mi? (kapsam kayması)
- Atanan kaynakların kaçı taslakta geçiyor?
- Hangi alt başlık kanıt boşluğu olarak kaldı?

Çıktı: `05_analiz/taslak/05_plan_uyumu_<zaman>.json/html`

### Adım 2: Kanıt denetimi

Taslak kullanıcıdan geldiyse (plan yoksa) yalnızca bu adım çalışır. Her iddia
için kaynak, sayfa, kısa alıntı, destek düzeyi ve karar üretilir:

```text
schemas/claim-evidence.schema.json + schemas/change-card.schema.json
```

### Adım 3: Nihai rapor

```text
05_analiz/taslak/05_analiz_<zaman>.html
05_analiz/taslak/05_analiz_<zaman>.md
05_analiz/taslak/05_analiz_<zaman>.manifest.json
```

**Kapı:** kalite kapısı 0 hata; plan uyumu raporunda açıklanmamış sapma yok.

---

## Yeni proje başlatma

```text
paperqa_create_workspace(project_directory="<proje-kökü>")
```

Beş klasörü açar. Ardından kullanıcıya 1–5 arasındaki akışı sorun; seçim
gelmeden işlem yapmayın. İlk proje kökü verildiğinde `setup.txt` dosyasını
kontrol edin (kural: kimlik bilgileri).
