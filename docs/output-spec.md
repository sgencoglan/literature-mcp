# Çıktı Sözleşmesi

Bu belge, insan ve ajan çıktılarının dosya adlarını, biçimlerini ve zorunlu alanlarını tanımlar. Bir çıktı bu sözleşmeye uymuyorsa teslim edilmiş sayılmaz.

## Genel kurallar

- **Dil:** Teslim Türkçedir. İngilizce kaynak cümlesi özgün hâliyle verilir; Türkçesi ayrı alanda bulunur.
- **DOI:** Yalnızca `https://doi.org/<doi>` biçimi. DOI metni ayrıca `doi` alanında saklanır.
- **Yerel yol yasağı:** HTML/Markdown/CSV/JSON teslimlerinde `file://`, `/home/...`, `C:\...` veya PDF dosya adı linki bulunmaz. PDF'ler yalnızca kaynak kimliği (DOI) ile anılır.
- **Kodlama:** CSV UTF-8 BOM'lu (`utf-8-sig`); JSON UTF-8; HTML `<meta charset="utf-8">`.
- **Tarih:** ISO 8601 (`2026-10-20`) veya ISO 8601 saatli (`2026-10-20T14:30:00+03:00`).
- **Sayfa:** 1 tabanlı PDF sayfa numarası. Aralık `page_start`–`page_end` olarak verilir.
- **Alıntı:** Kısa tutulur (genellikle 1–3 cümle); telif hakkı ve bağlam korunur.
- **Kırmızı:** Yalnızca değişen cümle. Paragrafın tamamı, başlık, kaynakça veya tablo kırmızıya boyanmaz.

## Dosya adları

Proje `output_directory` altında:

| Dosya | Biçim | Kime | İçerik |
|---|---|---|---|
| `01_fulltext_listesi.html` | HTML | İnsan | DOI/yayıncı linkleri, öncelik, Q, atıf, indirildi kutuları |
| `01_fulltext_listesi.json` | JSON | Ajan | Aynı verinin şemalı hâli |
| `02_degisiklik_kartlari.csv` | CSV | İnsan + ajan | Cümle bazlı düzeltme kartları |
| `02_degisiklik_kartlari.json` | JSON | Ajan | Kartların şemalı hâli |
| `03_kaynak_denetimi.csv` | CSV | İnsan + ajan | Ek 2 kaynak denetimi |
| `03_iddia_kanit_matrisi.csv` | CSV | İnsan + ajan | İddia–kanıt matrisi |
| `04_denetim_raporu.html` | HTML | İnsan | Kartlar + denetim + matris + kaynakça |
| `04_denetim_raporu.md` | Markdown | İnsan + ajan | Düzenlenebilir rapor |
| `04_denetim_raporu.json` | JSON | Ajan | Tam yapılandırılmış rapor |
| `05_bolum_raporu.html` | HTML | İnsan | **Altın standart:** düzeltilmiş metin + Ek 1 + Ek 2 |
| `05_bolum_raporu.manifest.json` | JSON | Ajan | Üretilen dosyaların hash'li temizlik manifesti |

Proje adı önek olarak eklenebilir: `<proje-adi>_01_fulltext_listesi.html`. Aynı ada sahip dosya varsa üzerine yazmadan önce kullanıcıya sor.

## 01 — Fulltext listesi

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
   - DOI linki, yayıncı linki, varsa OA PDF linki
5. **Alt bilgi:** "PDF indirme kullanıcı hesabından yapılır; bu liste indirme yapmaz."

Tek dosya olmalı; harici CSS/JS/font kullanılmaz. `@media print` ile yazdırma düzeni bozulmamalı. "İndirildi" durumu `localStorage` ile saklanır; tarayıcı desteklemiyorsa sessizce devam eder.

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
| `priority` | enum | evet | `A`, `B`, `C` |
| `access` | string | hayır | `Açık erişim`, `Kurum erişimi`, `Erişim yok` |
| `rationale` | string | evet | Neden seçildi |

Şema: [`../schemas/fulltext-list.schema.json`](../schemas/fulltext-list.schema.json).

## 02 — Düzeltme kartları

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
| `rewritten_sentence` | Yeniden yazılan cümle |
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

Kırmızı yalnızca `rewritten_sentence` üzerindedir. Kaynak cümlesi ve çevirisi normal renkte, alıntı bloğu olarak verilir.

## 03 — Kaynak denetimi (Ek 2)

### CSV sütunları

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

### Kurallar

- Her DOI `verify_doi_and_publisher` ile doğrulanır.
- `project_audit`/`journal_rank` çıktısı yoksa `-` yazılır; uydurma yapılmaz.
- `role` kararı gerekçelendirilir; "iyi görünüyor" gibi gerekçesiz karar verilmez.
- Aynı DOI birden çok kez listelenmez.

## 03 — İddia–kanıt matrisi

### CSV sütunları

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

### Kurallar

- Her satırda en az bir DOI ve sayfa bulunur; `none`/`not_found` istisnadır ve açıkça yazılır.
- `support=full` için alıntı iddiayı doğrudan desteklemelidir; yakın konu yeterli değildir.
- `contradicts` varsa iddia kararı `revise` veya `delete` olur.
- `strength` yalnızca kanıtın türüne göre verilir; dergi Q'su tek başına `strong` yapmaz.

## 04 — Denetim raporu

### HTML bölümleri

1. Kapak: proje, taslak, tarih, kapsam.
2. Yönetici özeti: kaç kart, kaç kaynak, kaç iddia, kaç `not_found`.
3. Düzeltme kartları (kırmızı cümleler).
4. Ek 2 kaynak denetimi tablosu.
5. İddia–kanıt matrisi.
6. Kaynakça: yalnızca DOI linkleri.
7. Ek: yöntem, arama tarihleri, dışlama ölçütleri.

### Markdown

Aynı bölümler; tablolar Markdown olarak. HTML'e özel renkler Markdown'da `**değişen cümle**` veya `<mark>` ile belirtilebilir; teslimde kırmızı kuralı HTML için geçerlidir.

### JSON

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

## 05 — Altın standart bölüm raporu

`05_bolum_raporu.html`, b1 pilot raporu için beğenilen tasarımın
standartlaştırılmış hâlidir. `04_denetim_raporu.html` denetim odaklı ara
çıktıdır; teslimde tercih edilen rapor `05`'tir.

### Bölümler

1. Düzeltilmiş bölüm metni; yalnızca değişen cümleler kırmızı.
2. Ek 1 — değişiklik kartları: yazar cümlesi, kaynak cümlesi (İngilizce),
   Türkçe çeviri, yeniden yazılan cümle, “ne değişti / neden” notu.
3. Ek 2 — kaynak envanteri, iddia–kanıt matrisi, düzeltme özeti, sınırlılıklar.
4. Opsiyonel kaynakça; yalnızca DOI linkleri.

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
  "intro": {"heading": "...", "paragraphs": [...]},
  "change_cards": [...],
  "source_audit": [...],
  "claim_matrix": [...],
  "correction_summary": [...],
  "limitations": [...],
  "references": [...]
}
```

### Üretim ve kalite kapısı

```bash
chapter-report build rapor.json -o 05_bolum_raporu.html --check
chapter-report build rapor.json -o 05_bolum_raporu.html
```

Zorunlu alanlar, DOI biçimi, sayfa/kanıt, yerel yol yasağı ve HTML dengesi
denetlenir. Ayrıntılar: [`report-standard.md`](report-standard.md).

### Temizlik

`05_bolum_raporu.manifest.json` yalnızca üretilen dosyaları listeler. Analiz
sonunda:

```bash
chapter-report cleanup --manifest 05_bolum_raporu.manifest.json \
  --scope intermediate --yes
```

`intermediate` HTML'i korur; `all` HTML'i de siler; manifest kalır. PDF, indeks
ve registry dosyaları manifest dışında olduğu için silinmez.

## Kalite kontrol

- [ ] Tüm DOI'ler `https://doi.org/...` biçiminde.
- [ ] Yerel PDF yolu / `file://` yok.
- [ ] Her alıntıda DOI + sayfa var.
- [ ] Kırmızı yalnızca değişen cümlede.
- [ ] `paperqa_ask` çıktısı kanıt olarak kullanılmadı.
- [ ] CSV UTF-8 BOM'lu, başlıklar doğru.
- [ ] JSON şemaya uyuyor.
- [ ] Proje izolasyonu korundu.
- [ ] Eski proje dosyaları değişmedi.
- [ ] `05_bolum_raporu.html` kalite kapısından 0 hatayla geçti.
- [ ] Temizlik yalnızca manifestteki dosyalara uygulandı.
