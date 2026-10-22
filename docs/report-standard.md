# Altın standart bölüm raporu

Bu belge, b1 pilot raporu için beğenilen raporun tasarımını ve içerik
kalitesini standartlaştırır. Amaç yalnızca “güzel HTML” üretmek değil; her
düzeltmenin kaynağa, sayfaya ve birebir alıntıya bağlandığı **denetlenebilir**
bir teslim üretmektir.

## Zorunlu yapı

1. **Düzeltilmiş bölüm metni**
   - Yalnızca değişen/eklenen cümleler kırmızı zeminle işaretlenir.
   - Paragrafın tamamı, başlık, kaynakça veya tablo kırmızıya boyanmaz.
2. **Ek 1 — Değişikliklerin kaynak cümleleriyle karşılaştırması**
   - Her değişiklik için:
     - yazarın taslakta yazdığı cümle,
     - kaynaktaki orijinal cümle (İngilizce, birebir),
     - Türkçe çeviri,
     - yeniden yazılan cümle (kırmızı),
     - “Ne değişti?” ve “Neden?” notu.
   - Her kartta en az bir DOI + sayfa + alıntı bulunur.
3. **Ek 2 — Kaynak denetimi ve iddia–kanıt matrisi**
   - Kaynak envanteri: DOI, dergi/yıl, Q, atıf, OA, retraction, kullanım rolü,
     sınırlılık.
   - İddia–kanıt matrisi: iddia, atıf(lar), durum, sayfa içeren kanıt/gerekçe.
   - Düzeltme özeti.
   - Notlar ve sınırlılıklar.
4. **Kaynakça (opsiyonel)** — yalnızca `https://doi.org/...` linkleri.
5. **Markdown eşlik dosyası (opsiyonel)** — aynı veriden üretilen düzenleme
   katmanı; HTML'deki kırmızı vurgu `**değişen cümle**` olarak temsil edilir.

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
- her değişiklik kartındaki DOI'nin kaynak envanterinde bulunması,
- yerel yol/PDF dosya adı sızıntısı,
- HTML etiket dengesi ve `<script>` yasağı.

`--strict` uyarıları da hata sayar. Teslimden önce **0 hata** ve uyarıların
gözden geçirilmiş olması gerekir.

## Tasarım sözleşmesi

- Gövde genişliği `46rem`, Georgia serif, 1.8 satır aralığı.
- Kırmızı: `rgba(255, 0, 0, 0.15)`, yalnızca değişen cümlede.
- Ek 1 kartları: `#fafafa` zemin, ince kenar, koyu kırmızı başlık.
- Ek 2 tabloları: 0.78rem, ince gri kenar, yatay taşma güvenli sarmalayıcı.
- Yazdırma: kırmızı zemin korunur, kartlar sayfa ortasında bölünmez.

Tasarım [`packages/report-kit/src/report_kit/templates/chapter-report.css`](../packages/report-kit/src/report_kit/templates/chapter-report.css)
içinde tek kaynaktır. Rapor üreticisi bu dosyayı gömülü CSS olarak yazar. b1
raporunun mevcut CSS kuralları birebir korunur; yalnızca tablo sarmalayıcı,
footer, dar ekran ve yazdırma için ek kurallar eklenmiştir.

## Temizlik

Üretim sonunda `05_bolum_raporu.manifest.json` oluşur. Temizlik yalnızca bu
manifestteki dosyaları kapsar:

```bash
# Ne silineceğini göster
chapter-report cleanup --manifest 05_bolum_raporu.manifest.json --dry-run

# HTML dışındaki ara dosyaları sil (Markdown korunur)
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
