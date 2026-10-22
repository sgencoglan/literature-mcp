# İş Akışları

Bu belge, iki ana görevin adım adım yürütülmesini tanımlar. Araç adları MCP araç adlarıdır; insanlar için parantez içinde ne işe yaradığı yazılmıştır.

## Görev 1 — Yeni bölüm için kaynak hattı

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
python3 scripts/build_fulltext_list.py adaylar.json -o 01_fulltext_listesi.html
```

Çıktı:

- Tek dosya, çevrimdışı açılır, yazdırılabilir.
- Tıklanabilir `https://doi.org/...` ve yayıncı linkleri.
- Açık erişim PDF linki varsa ayrı gösterilir.
- Her satırda yazdırılabilir "indirildi" kutusu; durum tarayıcıda saklanır.
- Yerel PDF yolu içermez.

### Adım 7: PDF'leri yerleştir ve projeyi kaydet

Kullanıcı PDF'leri `paper_directory` klasörüne indirir. Dosya adında DOI olması en güvenilir yöntemdir.

```text
paperqa_register_project(
  name="proje-adi",
  paper_directory="~/Documents/papers/example",
  title="...",
  description="...",
  include_subdirectories=false
)
project_audit(project="proje-adi")
paperqa_build_index(project="proje-adi")
paperqa_status(project="proje-adi")
library_status(project="proje-adi")
```

Kurallar:

- `paperqa_register_project` manifest üretir; DOI'ler dosya adından veya ilk iki sayfadan algılanır.
- DOI'siz dosyalar varsayılan olarak manifest dışıdır. Taslak/izin gibi dosyalar için `include_files_without_doi=true` gerekir.
- `project_audit` manifest dışı kalan dosyaları ve DOI eşleşmelerini gösterir.
- `paperqa_build_index` yalnızca manifest üyelerini indeksler; başka projenin indeksine dokunmaz.
- `paperqa_status` beklenen dosya sayısını göstermiyorsa PDF'leri ve manifesti kontrol edin.

### Adım 8: Taslağı yaz

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
- `paperqa_ask` yalnızca taslak fikir verir; cümleleri doğrudan teslime almayın.
- Her paragraf en az bir doğrulanmış kaynağa bağlanır.
- Kaynak yoksa iddia yazılmaz; gerekirse "Bu konuda doğrudan kanıt bulunamadı" denir.

### Adım 9: Teslim

```text
export_review(
  title="...",
  sections=[...],
  references=[...],
  format="md",
  filename="04_denetim_raporu.md"
)
```

Ardından insan için altın standart HTML teslim üretilir:

```bash
chapter-report build rapor.json -o 05_bolum_raporu.html --check
chapter-report build rapor.json -o 05_bolum_raporu.html
```

HTML'de kaynaklar `https://doi.org/...` ile listelenir; yerel PDF yolu bulunmaz. Teslimden sonra `--cleanup intermediate` veya `--cleanup all` seçeneği sunulur.

## Görev 2 — Mevcut taslağı denetleme

### Adım 1: Projeyi doğrula

```text
list_projects()
paperqa_projects()
project_audit(project="...")
paperqa_status(project="...")
library_status(project="...")
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
  filename="04_denetim_raporu.md"
)
export_review(format="csv", filename="03_iddia_kanit_matrisi.csv")
export_review(format="json", filename="02_degisiklik_kartlari.json")
```

Ardından insan için altın standart HTML: düzeltilmiş metin, Ek 1 değişiklik kartları, Ek 2 kaynak denetimi + iddia–kanıt matrisi, düzeltme özeti ve sınırlılıklar. DOI linkleri `https://doi.org/...`.

```bash
chapter-report build rapor.json -o 05_bolum_raporu.html --check
chapter-report build rapor.json -o 05_bolum_raporu.html
```

Teslimden sonra üretilmiş ara dosyaları temizleme seçeneği sunulur:

```bash
chapter-report cleanup --manifest 05_bolum_raporu.manifest.json \
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
