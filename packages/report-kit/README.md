# literature-report-kit

`chapter-report`, kitap bölümü düzeltmelerini **tek dosyalık, baskıya uygun HTML**
olarak üretir. Tasarım, b1 pilot raporu için beğenilen altın standart raporun
görsel dilini korur:

- geniş sayfa (980 px), sans-serif başlıklar, kart/kanıt/not düzeni,
- düzeltilmiş bölüm metni; yeniden düzenleme kırmızı, anlamlı MCP eklemeleri mavi/yeşil `<mark>`,
- üst bilgi sayı rozetleri ve opsiyonel kaynak politikası kutusu (`notice`),
- Ek 1: yazar cümlesi → kaynak cümlesi (İngilizce) → Türkçe çeviri → yeniden
  yazılan cümle → “ne değişti / neden” notu; kart başlığında durum rozeti,
- Ek 2: kaynak envanteri (rol ve sınırlılık sütunlarıyla), konum + kanıt türü +
  not sütunlu iddia–kanıt matrisi, düzeltme özeti, sınırlılıklar ve opsiyonel
  sonraki adımlar,
- iş akışı 3 için paragraf/makale bağlamı değerlendirmesi ve Ek 3 bağlama uygun
  DOI/metaverisi doğrulanmış kaynak önerileri; tam metni okunmamış öneriler kanıt sayılmaz,
- Ek 4'te her kaynak için bu projedeki katkı, desteklemediği çıkarımlar ve
  çalışma sınırlılıkları; değerlendirme dayanağı (özet/tam metin/sayfa) görünür,
- baskıya uygun tablo sarmalayıcıları ve footer.

## Kurulum

```bash
python -m pip install -e packages/report-kit
```

## Kullanım

```bash
# Yalnızca doğrula (dosya yazmaz)
chapter-report build examples/chapter-report.example.json --check

# HTML üret
chapter-report build rapor.json -o 05_bolum_raporu.html \
  --markdown 05_bolum_raporu.md

# Üret + ara dosyaları manifest üzerinden temizleme seçeneği
chapter-report build rapor.json -o 05_bolum_raporu.html \
  --markdown 05_bolum_raporu.md \
  --artifact 02_degisiklik_kartlari.json \
  --artifact 03_iddia_kanit_matrisi.csv \
  --cleanup ask
```

`--cleanup` seçenekleri:

| Değer | Davranış |
|---|---|
| `keep` | Hiçbir şey silmez (varsayılan). |
| `ask` | Üretim sonunda onay sorar; terminal yoksa silmez. |
| `intermediate` | HTML ve Markdown dışındaki manifest kayıtlarını siler. |
| `all` | Manifestteki tüm üretilmiş dosyaları siler; manifest kalır. |

Silme yalnızca `05_bolum_raporu.manifest.json` içinde listelenen, proje klasörü
içindeki dosyalarda yapılır. PDF, indeks, registry veya manifest dışındaki
dosyalara dokunulmaz. `--dry-run` yalnızca neyin silineceğini gösterir;
`--yes` onay sormadan uygular.

## Kalite kapısı

`build` komutu, HTML yazmadan önce zorunlu alanları ve şu kuralları denetler:

- her değişiklik kartında en az bir DOI + sayfa + birebir alıntı + Türkçe çeviri;
  kart DOI'si kaynak envanterinde bulunmalı,
- her destekli/kısmi iddiada sayfa içeren kanıt ve atıf,
- iddia matrisinde `location`, `evidence_type` ve `note` için öneri uyarıları
  (`--strict` ile hata),
- `notice` metni ve `next_steps` maddeleri için bütünlük denetimi,
- yalnızca `https://doi.org/...` linkleri,
- `file://`, `/home/...`, `C:\...` ve yerel PDF dosya adı yasağı,
- özet sayılarının veriyle uyuşması,
- `<script>`, harici stil/JS ve yerel yol içermeyen dengeli HTML
  (`<article>`, `<footer>`, `<mark>` dahil).

`--strict` uyarıları da hata sayar. Örnek veri ve şema:

- [`examples/chapter-report.example.json`](../../examples/chapter-report.example.json)
- [`schemas/chapter-report.schema.json`](../../schemas/chapter-report.schema.json)

## Neden ayrı bir paket?

Rapor kalitesi yalnızca iyi bir metin üretmekten değil, **kanıtın sayfaya
bağlanmasından** ve görsel standardın her seferinde aynı olmasından gelir.
Bu paket sunumu deterministik yapar; içerik denetimi `paperqa_search` +
`paperqa_read_pages` ile yapılmaya devam eder. `paperqa_ask` çıktısı kanıt
olarak kullanılmaz.
