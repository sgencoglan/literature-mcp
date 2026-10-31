# Altın standart bölüm raporu

Bu belge, b1 pilot raporu için beğenilen raporun tasarımını ve içerik
kalitesini standartlaştırır. Amaç yalnızca “güzel HTML” üretmek değil; her
düzeltmenin kaynağa, sayfaya ve birebir alıntıya bağlandığı **denetlenebilir**
bir teslim üretmektir.

## Zorunlu yapı

1. **Düzeltilmiş bölüm metni**
   - Yalnızca değişen/eklenen cümleler kırmızı zeminle işaretlenir.
   - Paragrafın tamamı, başlık, kaynakça veya tablo kırmızıya boyanmaz.
   - Kırmızı cümleler, rapor açıklaması değil, paragrafta kullanılabilecek son metin önerisidir. Önceki ve sonraki cümlelerle birlikte okunduğunda doğal akmalı ve paragrafın amacına hizmet etmelidir.
   - Metnin üstünde opsiyonel **kaynak politikası / yöntem notu** kutusu
     (`notice`) yer alabilir.
2. **Ek 1 — Değişikliklerin kaynak cümleleriyle karşılaştırması**
   - Her değişiklik için:
     - yazarın taslakta yazdığı cümle,
     - kaynaktaki orijinal cümle (İngilizce, birebir),
     - Türkçe çeviri,
     - yeniden yazılan cümle (kırmızı),
     - “Ne değişti?” ve “Neden?” notu.
   - Her kartta en az bir DOI + sayfa + alıntı bulunur.
   - Kart başlığında `evidence_status` rozeti gösterilir.
3. **Ek 2 — Kaynak denetimi ve iddia–kanıt matrisi**
   - Kaynak envanteri: DOI, dergi/yıl, Q, atıf, OA, retraction, kullanım rolü,
     sınırlılık. `role` ve `limitation` tabloda ayrı sütun olarak görünür.
   - İddia–kanıt matrisi: iddia, atıf(lar), durum, sayfa içeren kanıt/gerekçe;
     ayrıca **konum** (`P1 · c2`), **kanıt türü** (kesitsel, meta-analiz,
     amaç beyanı vb.) ve **not** sütunları.
   - Düzeltme özeti.
   - Notlar ve sınırlılıklar.
   - **Sonraki adımlar** (`next_steps`, opsiyonel): yapılacak somut işler.
4. **Kaynakça (opsiyonel)** — yalnızca `https://doi.org/...` linkleri.
5. **Markdown eşlik dosyası (opsiyonel)** — aynı veriden üretilen düzenleme
   katmanı; HTML'deki kırmızı vurgu `**değişen cümle**` olarak temsil edilir.
6. **Footer (opsiyonel)** — proje, sürüm ve üretim tarihi; yerel yol içermez.

## Kanıt kuralları

- **Kanıt LLM çıktısı değildir.** `paperqa_ask` yalnızca taslak/özet üretir;
  raporda kanıt olarak kullanılmaz.
- Kanıt; `paperqa_search` ile bulunur, `paperqa_read_pages` / `read_paper` ile
  sayfa numarası doğrulanır.
- Her destekli/kısmi iddiada en az bir DOI ve sayfa (`s. 4`, `p. 7`,
  `sayfa 12`) bulunur.
- `not_found` / `contradicted` iddialar saklanmaz; gerekçesi ve kararı yazılır.
- Aynı DOI kaynak envanterinde birden fazla kez listelenmez.
- Q değeri, atıf sayısı veya dergi prestiji tek başına kanıt gücü yapmaz.
- Kanıtın sınırlarını bölüm metninde hakem notu gibi anlatmayın. “Bu kaynak X'i göstermemektedir” türü açıklamalar `note`, iddia–kanıt matrisi veya sınırlılıklar bölümüne aittir.
- Kısmi destek varsa iddiayı desteklenen kapsamda, metnin anlamlı akışını koruyarak yeniden yazın. İddianın çekirdeği desteklenmiyorsa onu ana metinden çıkarın veya dayanağı olan başka bir önermeyle değiştirin; kanıt boşluğunu metne “kanıt yok” cümlesi ekleyerek kapatmayın.
- Her öneriyi paragraf bağlamında kontrol edin: konuya katkısı, atıf uyumu, önceki/sonraki cümleye geçişi ve yinelenen fikir olup olmadığı. Yalnızca dilbilgisel olarak doğru olması yeterli değildir.

## Teslim güvenliği

- DOI linkleri yalnızca `https://doi.org/...`.
- `file://`, `/home/...`, `C:\...`, `/Users/...` ve yerel PDF dosya adı yasak.
- HTML tek dosyadır; harici CSS/JS/font, `<script>` veya `<iframe>` yoktur.
- Yayımlanmamış bölüm metni public depoya konmaz; public örnek sentetiktir.

## Kalite kapısı

```bash
chapter-report build rapor.json -o 05_bolum_raporu.html --check
```

Komut şunları denetler:

- zorunlu alanlar ve özet sayıları,
- DOI biçimi ve tekrarı,
- her kartta kaynak + sayfa + alıntı + çeviri + not,
- her destekli iddiada sayfa ve atıf,
- iddia matrisinde `location`, `evidence_type` ve `note` için öneri uyarıları,
- `notice` varsa başlık/metin bütünlüğü, `next_steps` varsa boş madde yasağı,
- her değişiklik kartındaki DOI'nin kaynak envanterinde bulunması,
- yerel yol/PDF dosya adı sızıntısı,
- HTML etiket dengesi (`<article>`, `<footer>`, `<mark>` dahil) ve `<script>` yasağı.

`--strict` uyarıları da hata sayar; iddia konumu ve kanıt türü eksikse teslim
geçmez. Teslimden önce **0 hata** ve uyarıların gözden geçirilmiş olması
gerekir.

## Tasarım sözleşmesi

- Gövde genişliği `980px`, Georgia serif, 1.65 satır aralığı; başlıklar
  sistem sans-serif fontuyla.
- Kırmızı: `rgba(255, 0, 0, 0.13)`, yalnızca değişen cümlede; HTML'de semantik
  `<mark>` etiketi kullanılır.
- Üst bilgi: proje/tarih meta satırı, ardından sayı rozetleri
  (`summary-strip`) ve opsiyonel kaynak politikası kutusu (`notice`).
- Ek 1 kartları: `.card` sınıfı, ince kenar, `break-inside: avoid`; kaynak
  alıntıları `.ev` bloğunda, düzeltme notları `.notes` kutusunda.
- Ek 2 tabloları: 0.84rem, ince gri kenar, `scope="col"` başlıkları ve yatay
  taşma güvenli `.table-wrap` sarmalayıcısı.
- Footer: ince üst çizgi, küçük gri metin; yerel PDF yolu veya `file://`
  içermez.
- Yazdırma: kırmızı zemin korunur, kartlar sayfa ortasında bölünmez, tablo
  başlıkları her sayfada yinelenir.

Tasarım [`packages/report-kit/src/report_kit/templates/chapter-report.css`](../packages/report-kit/src/report_kit/templates/chapter-report.css)
içinde tek kaynaktır. Rapor üreticisi bu dosyayı gömülü CSS olarak yazar.
b1 raporunun görsel dili (geniş sayfa, sans-serif başlık, kart/kanıt/not
düzeni) korunur; b1'deki yerel yol içeren footer bilinçli olarak dışarıda
bırakılır.

## Temizlik

Üretim sonunda `05_bolum_raporu.manifest.json` oluşur. Temizlik yalnızca bu
manifestteki dosyaları kapsar:

```bash
# Ne silineceğini göster
chapter-report cleanup --manifest 05_bolum_raporu.manifest.json --dry-run

# HTML ve Markdown dışındaki ara dosyaları sil
chapter-report cleanup --manifest 05_bolum_raporu.manifest.json \
  --scope intermediate --yes

# Tüm üretilmiş dosyaları sil (manifest kalır)
chapter-report cleanup --manifest 05_bolum_raporu.manifest.json \
  --scope all --yes
```

PDF, indeks, `projects.json`, manifest dışı dosyalar ve proje klasörü dışındaki
yollar silinmez. Hash değişmiş dosyalar `--force` verilmedikçe atlanır.

## Neden yerel model yeterli değil?

Bu rapordaki kalite, daha büyük bir modelin “daha güzel yazmasından” değil;
kanıtın sayfaya bağlanması, her iddianın ayrı ayrı denetlenmesi ve sunumun
deterministik olmasından gelir. Yerel Qwen modeli taslak/özet için yararlıdır;
nihai kanıt ve sayfa doğrulaması her zaman araç çıktısına dayanmalıdır.
