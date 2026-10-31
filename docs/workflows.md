# İş Akışları

Bu belge üç iş akışını adım adım tanımlar. Araç adları MCP araç adlarıdır; insanlar için parantez içinde ne işe yaradığı yazılmıştır.

## İş akışı 1 — Kaynak keşfi ve PDF listesi

Başlamadan önce kullanıcıdan proje klasörünün tam yolunu alın. Bu yol olmadan
dosya oluşturmayın. Aday JSON'u ve `01_fulltext_listesi.html` dosyasını aynı
projenin `01_kaynak_kesfi/` klasörüne yazın. İlk adımda
`paperqa_create_workspace(project_directory=...)` çağrısı yaparak proje
kökünde üç iş akışı klasörünü oluşturun. Proje adı klasör adından alınır;
gerekirse `name` ile açıkça verilebilir. Sonra kullanıcıya üç akıştan hangisini
yapacağını sorun; seçim gelmeden arama, PDF işleme veya raporlama yapmayın.

### Adım 1: Kapsamı netleştir

Şunlar belirlenmeden aramaya başlamayın:

- Bölümün konusu ve hedef kitlesi
- Hedef kaynak sayısı (ör. 8–12)
- Yıl aralığı (ör. 2010–2026)
- Dil (Türkçe/İngilizce)
- Çalışma türü önceliği (sistematik derleme, boylamsal, nitel, müdahale)
- Zorunlu/istenmeyen konular

Kapsam belirsizse kullanıcıya sorun. Varsayım yapmayın.

### Adım 2: Aday DOI'leri topla

Ana araçlar:

```text
deep_research(question="...", max_subtopics=5, results_per_topic=6)
search_literature(query="...", limit=20, year_from=2015, priority_only=true)
```

Gerektiğinde genişletme:

```text
search_all(query="...", limit=20, priority_only=true)
search_sciencedirect(query="...", limit=10)
search_pubmed(query="...", limit=10)
search_europepmc(query="...", limit=10)
```

Kurallar:

- `priority_only=true` yalnızca beş platformdan (Ovid LWW, ScienceDirect, SpringerLink, Wiley, Taylor & Francis) gerçek yayıncı linki olan kayıtları döndürür.
- `priority_only=false` yalnızca keşif içindir; teslim listesine giren her kaydın yayıncı linki ayrıca doğrulanır.
- Aynı DOI birden çok kaynaktan gelebilir; `get_article` ile tekilleştirin.
- Hedefin 2–3 katı aday toplayıp eleme yapın.

### Adım 3: Metadata ve linkleri al

Her aday için:

```text
get_article(identifier="10....", id_type="doi")
get_links(identifier="10....", id_type="doi")
```

Şu alanları kaydedin: `title`, `authors`, `year`, `journal`, `doi`, `publisher`, `publisher_url`, `preferred_url`, `citations`, `open_access`, `oa_pdf_url`.

### Adım 4: DOI ve dergi doğrulaması

Her aday için:

```text
verify_doi_and_publisher(doi="10....")
doi_provenance(doi="10....")
journal_rank(journals=["Dergi Adı"], include_categories=false)
```

Kurallar:

- DOI Crossref ve/veya doi.org üzerinden çözülmüyorsa aday listesine alınmaz.
- `doi_provenance` hiçbir veritabanında kayıt göstermiyorsa aday çıkarılır.
- `journal_rank` Q1–Q4 döndürür; dergi bulunamazsa `not_found` yazılır, uydurma yapılmaz.
- Q tek başına kalite kanıtı değildir; kapsam uygunluğu ayrıca değerlendirilir.

### Adım 5: Aday JSON'unu yaz

`schemas/fulltext-list.schema.json` biçiminde bir dosya oluşturun:

```json
{
  "project": "proje-adi",
  "title": "Bölüm başlığı — fulltext listesi",
  "query": "Arama sorusu",
  "generated_at": "2026-10-20",
  "target_count": 10,
  "notes": "Seçim ölçütleri ve dışlananlar.",
  "candidates": [
    {
      "doi": "10.xxxx/yyyy",
      "title": "...",
      "authors": "Yazar, A.; Yazar, B.",
      "year": 2024,
      "journal": "...",
      "quartile": "Q1",
      "citations": 12,
      "open_access": false,
      "publisher": "ScienceDirect",
      "publisher_url": "https://www.sciencedirect.com/science/article/pii/...",
      "oa_pdf_url": null,
      "priority": "A",
      "access": "Kurum erişimi",
      "rationale": "Doğrudan bölüm konusunu ölçen boylamsal çalışma."
    }
  ]
}
```

`priority` değerleri: `A` = vazgeçilmez, `B` = güçlü ikinci halka, `C` = yedek/bağlam.

### Adım 6: Fulltext listesi HTML'ini üret

```bash
cd <repo>
python3 scripts/build_fulltext_list.py \
  <proje-kökü>/01_kaynak_kesfi/01_fulltext_listesi.json \
  -o <proje-kökü>/01_kaynak_kesfi/01_fulltext_listesi.html
```

Çıktı:

- Tek dosya, çevrimdışı açılır, yazdırılabilir.
- Tıklanabilir `https://doi.org/...` ve yayıncı linkleri.
- Açık erişim PDF linki varsa ayrı gösterilir.
- Her satırda yazdırılabilir "indirildi" kutusu; durum tarayıcıda saklanır.
- Yerel PDF yolu içermez.

## İş akışı 2 — PDF'leri projeye kaydetme ve kanıta dayalı taslak

### Adım 1: Proje klasörünü ve PDF klasörünü belirle

Kullanıcı iş akışı 2'yi seçtikten sonra PDF'leri
`<proje-kökü>/02_bolum_taslagi/fulltext/` altına koyar. Dosyalar gelmeden taslak
hazırlamaya başlamayın. Dosya adında DOI olması en güvenilir yöntemdir.
`paperqa_create_workspace` sonucundaki `workflow_project_names.draft` değerini
PaperQA proje adı olarak kullanın; `output_directory` proje kökü,
`paper_directory` bu PDF klasörüdür.

```text
paperqa_register_project(
  name="<workflow_project_names.draft>",
  paper_directory="<proje-kökü>/02_bolum_taslagi/fulltext",
  title="...",
  description="...",
  include_subdirectories=false,
  output_directory="<kullanıcının-verdiği-proje-kökü>"
)
project_audit(project="<workflow_project_names.draft>")
paperqa_build_index(project="<workflow_project_names.draft>")
paperqa_status(project="<workflow_project_names.draft>")
library_status(project="<workflow_project_names.draft>")
```

Kurallar:

- `paperqa_register_project` manifest üretir; DOI'ler dosya adından veya ilk iki sayfadan algılanır.
- Yeni proje kaydında `output_directory` zorunludur. Manifest ve indeks, proje klasöründeki `.literature-mcp/` içine yazılır.
- DOI'siz dosyalar varsayılan olarak manifest dışıdır. Taslak/izin gibi dosyalar için `include_files_without_doi=true` gerekir.
- `project_audit` manifest dışı kalan dosyaları ve DOI eşleşmelerini gösterir.
- `paperqa_build_index` yalnızca manifest üyelerini indeksler; başka projenin indeksine dokunmaz.
- `paperqa_status` beklenen dosya sayısını göstermiyorsa PDF'leri ve manifesti kontrol edin.

### Adım 2: Taslağı yaz

Her bölüm paragrafı için:

```text
paperqa_search(project="proje-adi", query="paragrafın iddiası", k=6)
paperqa_read_pages(project="proje-adi", doi="10....", page_start=..., page_end=...)
```

Gerekirse tam metin:

```text
read_paper(identifier="10....", id_type="doi", project="proje-adi", max_pages=20)
```

Kurallar:

- `paperqa_search` sonucu aday cümle/DOI verir; nihai alıntı için sayfa doğrulaması şarttır.
- PDF'te doğrulanan bulguları, paragrafın amacı ve önceki/sonraki cümleleriyle uyumlu özgün Türkçe cümlelerle yazın. Kaynağın sonucunu koruyun; kaynak cümlesinin sözdizimini kopyalamayın.
- Doğrudan alıntıyı yalnızca ifade biçimi önemliyse kullanın; kısa tutun, alıntı olarak işaretleyin ve PDF sayfasını verin. İngilizce kaynak cümlesi rapor/denetim alanında birebir gösterilebilir; bu, taslak metnine aynen alınacağı anlamına gelmez.
- `paperqa_ask` sentezlenmiş taslak fikir verebilir, ancak yeniden yazımın özgünlüğünü veya kanıta uygunluğunu garanti etmez. Her iddiayı `paperqa_search` ve `paperqa_read_pages` ile doğrulayın ve taslağı kendiniz bağlama uygun biçimde kurun.
- Her paragraf en az bir doğrulanmış kaynağa bağlanır.
- Kaynak yoksa iddia yazılmaz; gerekirse "Bu konuda doğrudan kanıt bulunamadı" denir.

### Adım 3: Taslağı proje klasörüne kaydet ve teslim et

Taslak rapor verisini `<proje-kökü>/02_bolum_taslagi/taslak/02_bolum_taslagi.json`
olarak kaydedin. JSON'da `intro` bölüm metnini, `change_cards` Ek 1'deki her
iddianın sayfa doğrulamalı kaynak cümlesi ve bağlama uygun özgün anlatımını,
`claim_matrix` ise iddia–kanıt tablosunu taşır. Kaynak denetim özetini
`source_audit` alanına ekleyin. Böylece aynı HTML `chapter-report` şablonu
üçüncü iş akışındaki Ek 1 ve iddia–kanıt matrisini içerir.

Yeni taslakta her `change_cards` kaydı bir taslak iddiasını temsil eder:
`author_sentence` ilk taslak iddiası, `sources` PDF sayfasındaki kısa özgün
alıntı ve Türkçe çevirisi, `rewritten_sentence` paragrafta kullanılan bağlama
uygun özgün ifade olur. Sunum etiketlerini `card_label="İddia"`,
`author_label="Taslakta ileri sürülen iddia"`,
`rewritten_label="Bölümde kullanılan cümle"` ve
`notes_heading="Kanıt ve bağlam notu"` olarak verin. `claim_matrix` her iddia
için DOI, sayfa, kanıt türü ve destek durumunu taşır.

Önce kalite kapısını çalıştırın, sonra HTML ve Markdown'ı üretin:

```bash
chapter-report build <proje-kökü>/02_bolum_taslagi/taslak/02_bolum_taslagi.json --check
chapter-report build <proje-kökü>/02_bolum_taslagi/taslak/02_bolum_taslagi.json \
  -o <proje-kökü>/02_bolum_taslagi/taslak/02_bolum_taslagi.html \
  --markdown <proje-kökü>/02_bolum_taslagi/taslak/02_bolum_taslagi.md
```

İkinci akışın ana teslimi HTML'dir; bölüm metni, Ek 1 ve Ek 2 matrisi birlikte
bulunur. Markdown aynı içeriğin düzenlenebilir sürümüdür.

DOI bağlantıları raporda `https://doi.org/...` biçimindedir; yerel PDF yolu
veya `file://` bağlantısı teslim HTML'ine eklenmez.

## İş akışı 3 — Mevcut taslağı denetleme

Denetim taslağını ve rapor dosyalarını `<proje-kökü>/03_taslak_denetimi/taslak/`
altında tutun. Kullanıcı denetlenecek taslağı bu klasöre, tam metin PDF'lerini
`03_taslak_denetimi/fulltext/` altına koyar. Dosyalar gelmeden denetime başlamayın.
Bu akış için `workflow_project_names.audit` adını kullanarak ayrı PDF projesi
kaydedin; böylece ikinci akışın indeksiyle karışmaz. Rapor `chapter-report`
kalite kapısından geçmelidir.

### Adım 1: Projeyi doğrula

```text
paperqa_register_project(
  name="<workflow_project_names.audit>",
  paper_directory="<proje-kökü>/03_taslak_denetimi/fulltext",
  output_directory="<proje-kökü>",
  title="..."
)
project_audit(project="<workflow_project_names.audit>")
paperqa_status(project="<workflow_project_names.audit>")
library_status(project="<workflow_project_names.audit>")
```

Proje adı, PDF klasörü ve indeks uyuşmuyorsa durun; kullanıcıya sorun.

### Adım 2: Taslağı cümlelere ayır

Her cümleyi/iddiayı ayrı kaydedin:

```json
{
  "id": "C1",
  "location": "Giriş, 2. paragraf",
  "claim": "...",
  "status": "bekliyor"
}
```

### Adım 3: Kanıt ara ve doğrula

Her iddia için:

```text
paperqa_search(project="...", query="iddia", k=6)
paperqa_read_pages(project="...", doi="10....", page_start=1, page_end=3)
```

Gerekirse:

```text
read_paper(identifier="10....", id_type="doi", project="...", page_start=..., page_end=...)
```

Kurallar:

- Sayfa numarası 1 tabanlıdır.
- Abstract ile tam metin çelişiyorsa tam metin esastır; çelişki not edilir.
- Aynı iddia birden fazla kaynakla destekleniyorsa hepsini kaydedin.
- Kanıt bulunamazsa `not_found`; kısmi destek varsa `partially_supported`.

### Adım 4: Kaynak kimliğini doğrula

```text
verify_doi_and_publisher(doi="10....")
doi_provenance(doi="10....")
journal_rank(journals=["..."], include_categories=false)
```

Yardımcı:

```text
compare_studies(identifiers=["10....", "10...."], project="...")
evidence_check(claims=["..."], identifier="10....", project="...")
```

`compare_studies` tablo üretir; `evidence_check` lexical benzerlik verir. İkisi de nihai kanıt değildir.

### Adım 5: Düzeltme kartlarını üret

Her kart için `schemas/change-card.schema.json` uyumlu veri:

| Alan | İçerik |
|---|---|
| `id` | `D1`, `D2`, ... |
| `location` | Paragraf/cümle konumu |
| `author_sentence` | Yazarın özgün cümlesi |
| `source_sentence` | PDF'ten birebir İngilizce cümle |
| `source_translation` | Kaynak cümlesinin Türkçesi |
| `source_doi` | DOI |
| `source_page` | Sayfa numarası |
| `rewritten_sentence` | Kanıta uygun yeniden yazım |
| `note` | Neden değişti, sınırlılık, dikkat |
| `evidence_status` | `supported`, `partially_supported`, `contradicted`, `not_found` |

Kurallar:

- `source_sentence` birebir alıntıdır; düzeltme veya özet değildir.
- `source_translation` yorum katmaz.
- `rewritten_sentence` kanıtın izin verdiği kadarını söyler; abartı, nedensellik ve genelleme kaldırılır.
- `rewritten_sentence` paragraf içinde doğrudan kullanılabilir, doğal ve konuyla ilgili bir cümle olmalıdır. “Kaynak bunu göstermiyor” veya “bu iddia desteklenmiyor” gibi denetçi açıklamalarını ana metne koymayın; bunları `note` alanında ve iddia–kanıt matrisinde belirtin.
- İddianın bir bölümü destekleniyorsa desteklenen anlamı koruyarak yeniden kurun. İddianın çekirdeği kanıtsızsa ana metinden çıkarın veya aynı paragraf amacına hizmet eden, kaynakla destekli bir önerme kullanın; destek boşluğunu yapay bir geçiş cümlesiyle doldurmayın.
- Kartı tamamlamadan önce önerilen cümleyi paragrafın tamamında okuyun. Bağlaçların, zamirlerin ve atıfların akışa uyduğunu; cümlenin paragrafın işlevine katkı verdiğini kontrol edin.
- HTML'de yalnızca `rewritten_sentence` kırmızı; kaynak cümlesi ve çevirisi normal renktedir.

### Adım 6: Ek 2 kaynak denetimi

Her kaynak için:

- DOI, yazar/yıl, dergi, yayıncı
- Q ve atıf sayısı (`journal_rank`, `project_audit`)
- Açık erişim / erişim durumu
- Kullanım kararı: çekirdek / destek / bağlam / dışla
- Sınırlılık notu

### Adım 7: İddia–kanıt matrisi

Her iddia için `schemas/claim-evidence.schema.json` uyumlu satır:

- `claim_id`, `claim`
- `source_doi`, `source_page`
- `evidence_quote` (kısa), `evidence_translation`
- `support` (`full`, `partial`, `none`, `contradicts`)
- `strength` (`strong`, `moderate`, `weak`)
- `decision` (`keep`, `revise`, `delete`, `add_source`)

### Adım 8: Rapor ve teslim

```text
export_review(
  title="...",
  sections=[...],
  claims=[...],
  references=[...],
  format="md",
  output_path="<proje-kökü>/03_taslak_denetimi/taslak/04_denetim_raporu.md",
  project="proje-adi"
)
export_review(format="csv", filename="03_iddia_kanit_matrisi.csv")
export_review(format="json", filename="02_degisiklik_kartlari.json")
```

Ardından insan için altın standart HTML: düzeltilmiş metin, Ek 1 değişiklik kartları, Ek 2 kaynak denetimi + iddia–kanıt matrisi, düzeltme özeti ve sınırlılıklar. DOI linkleri `https://doi.org/...`.

```bash
chapter-report build <proje-kökü>/03_taslak_denetimi/taslak/rapor.json --check
chapter-report build <proje-kökü>/03_taslak_denetimi/taslak/rapor.json \
  -o <proje-kökü>/03_taslak_denetimi/taslak/05_bolum_raporu.html \
  --markdown <proje-kökü>/03_taslak_denetimi/taslak/05_bolum_raporu.md
```

Teslimden sonra üretilmiş ara dosyaları temizleme seçeneği sunulur:

```bash
chapter-report cleanup \
  --manifest <proje-kökü>/03_taslak_denetimi/taslak/05_bolum_raporu.manifest.json \
  --scope intermediate --dry-run
```

## Karar noktaları

| Durum | Karar |
|---|---|
| DOI doğrulanamıyor | Adayı listeden çıkar; kullanıcıya bildir. |
| Tam metin yok, abstract var | Abstract yalnızca bağlam/özet için; kanıt sayılmaz. |
| Kanıt kısmi | `partially_supported`; cümle kanıt kadarını söyleyecek şekilde yazılır. |
| Kanıt çelişiyor | `contradicted`; yazar cümlesi düzeltilir, çelişki not edilir. |
| Kaynak aynı DOI'yi farklı metadata ile gösteriyor | Çoğunluk/Crossref esas alınır; fark not edilir. |
| Proje adı bilinmiyorsa | `list_projects` / `paperqa_projects`; kullanıcıya sor. |
| İndeks beklenenden az dosya içeriyorsa | Manifest ve PDF'leri kontrol et; `paperqa_build_index(rebuild=true)` gerekebilir. |
| PDF'ler klasörde ama manifestte yoksa | `paperqa_register_project(refresh_manifest=true)` veya manifesti güncelle. |
| Yeni konu, hedef kaynak sayısı yok | Kullanıcıya sor; aramayı başlatma. |
