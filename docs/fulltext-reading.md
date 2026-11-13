# Akış 4/5 öncesinde zorunlu tam metin okuma

PDF yükleme, metin çıkarma ve indeksleme modelin anlamsal okuması değildir.
Her PDF'in **bütün sayfaları** hazırlanır; model gerçekten okuduğu sayfalara
inceleme notu verir. Kaynak PDF'ler değiştirilmez.

## Hazırlama

```bash
python3 scripts/fulltext_reading.py prepare \
  --fulltext-dir /path/to/workspace/04_taslak/fulltext \
  --output-dir /path/to/workspace/03_kaynak_kesfi/reading-4 --workflow 4
```

`pages/<belge-kimliği>/page-N.txt` ve `page-N.png` çıkarılır. JSON/HTML
raporu; dosya, PDF metadata başlığı, sayfa, hata ve inceleme durumunu gösterir.
İlk rapor engellidir: çıkarılmış sayfalar henüz incelenmiş sayılmaz.
Bozuk/şifreli belgeler hata olarak kalır. Metinsiz veya görsel içeren sayfalar
görsel incelenmelidir; okunamayan içerik için OCR/daha okunaklı belge gerekir.

## Modelin sayfa incelemelerini kaydetme

Model bütün metinleri ve gereken sayfa görsellerini okur. Bir JSON listesinde
her sayfa için `document_id`, `page`, `mode` (`text`, `visual`,
`text_and_visual`), gereken `text_sha256`/`image_sha256`, `summary`,
`terms`, `sections` (ör. `S1`) ve `limitations` kaydeder. Kimlik/hash'ler
hazırlama raporundan alınır; summary gerçek sayfa içeriğinin notudur.

```bash
python3 scripts/fulltext_reading.py review \
  --manifest /path/to/reading-4/03_fulltext_okuma_TIMESTAMP.json \
  --reviews /path/to/reviews.json \
  --fulltext-dir /path/to/workspace/04_taslak/fulltext --workflow 4 \
  --plan /path/to/plan.json
```

İncelemeler partilerle eklenebilir; her partide son manifest kullanılır.
Raporlar korunur. `--plan`, sayfa notlarından kaynak sayfası izli yeni terim
adayları ve alt başlıklara göre ek makale ihtiyaçlarını üretir. Bunlar öneridir;
terim geçmesi veya belge sayısı, kanıt yeterliliği değildir. Gerçek arama
yapılmadan yeni makale başlığı üretilmez.

Hash'ler güncel sayfaya referansı doğrular; modelin anladığını matematiksel
olarak kanıtlamaz. Okuma sayfa notlarıyla kaydedilen model beyanıdır.
Hash kopyalamak okuma değildir; ajan gerçek içeriği incelemeden not yazamaz.
İddia–pasaj doğrulaması ayrıca yapılır.

## Geçiş kontrolü

```bash
python3 scripts/fulltext_reading.py check \
  --manifest /path/to/reading-4/03_fulltext_okuma_REVIEWED.json \
  --fulltext-dir /path/to/workspace/04_taslak/fulltext --workflow 4

python3 scripts/build_evidence_gap_request.py /path/to/plan.json --preflight \
  --fulltext-list /path/to/fulltext-list.json \
  --fulltext-dir /path/to/workspace/04_taslak/fulltext \
  --reading-report /path/to/reading-4/03_fulltext_okuma_REVIEWED.json \
  --workflow 4 -o /path/to/workspace/03_kaynak_kesfi
```

Eksik inceleme, değişen PDF/küme, yanlış hedef akış veya çözümlenmemiş
plan/kaynak boşluğu geçişi engeller. Preflight raporu yine yazılır;
`transition_allowed=false` ve çıkış kodu 1 olur. `check` başarı kodu 0'dır.
`--fulltext-dir` olmadan güncellik doğrulanmaz. Akış 5 için `--workflow 5`
ve ilgili belge kümesi kullanılır. Kullanıcı taslağında plan yoksa bağımsız
tam okuma `check` yine zorunludur; yapay plan hazırlanmaz.

## Akış 1–3 HTML'lerinde ortak panel

Konu, yazım planı ve fulltext JSON'larına `search_reports` listesi eklenir.
Her öğe `{"kind":"coverage","payload":GERÇEK_API_CEVABI}` veya
`{"kind":"platform_results","payload":GERÇEK_MODEL_ARAMA_RAPORU}` biçimindedir.
Mevcut konu raporundaki `database_searches` de desteklenir.

Panel; durum, dönen kayıt, tekil DOI, yeni aday, listede kalan, süre, tarih,
hata/not, bekleme ve sonraki işlemi gösterir. Bildirilmemiş değerler `—`
kalır; sıfır veya başarı varsayılmaz. `new_candidates`/`selected` yalnızca
günlükte sağlanmışsa gösterilir, kalite skorundan türetilmez.

```bash
python3 scripts/build_fulltext_list.py /path/to/fulltext-list.json \
  --coverage /path/to/search-response.json \
  --platform-results /path/to/platform-results.json \
  --reading-report /path/to/03_fulltext_okuma_REVIEWED.json \
  -o /path/to/workspace/03_kaynak_kesfi/fulltext.html
```

Konu/yazım planı JSON'larında `fulltext_reading` alanına okuma raporu eklenebilir.
HTML kayıt anındaki durumu gösterir; geçişte güncel PDF'ler yeniden doğrulanır.
Rapor, inceleme notları ve sayfa çıktıları araştırma klasöründe kalır; GitHub'a
yüklenmez. Şema: `schemas/fulltext-reading.schema.json`.
