# Modelin site: sorgularıyla kaynak keşfi

Hedef önemli yayınları kaçırma riskini azaltmaktır. Model kendi bağlı web
arama aracını kullanır; tarayıcı otomasyonu veya ayrı Scholar API anahtarı
gerektiren bir entegrasyon eklenmez. Modelin web aracı yoksa plan hazırlanır,
arama görevleri `not_run` kalır. MCP güncellendikten sonra sunucuyu yeniden
başlatın; iki yeni araç görünür.

## Kullanıcı isteği

> Bu konuda önemli yayınları kaçırmadan araştır. Önce genel arama yap,
> ardından Cochrane, ScienceDirect, Taylor & Francis, Springer, Wiley, SAGE,
> APA ve diğer ilgili platformları site: sorgularıyla kontrol et. Kitap
> bölümlerini de dahil et. Kaynakça ve ileri atıf takibi yap; eksik kalan
> aramaları belirt.

## Ajanın iş akışı

1. Konuyu kavramlara ayır; İngilizce eş anlamlıları ve farklı bağlam
   adlandırmalarını belirle. Projedeki konu/plan onayları geçerlidir.
2. `prepare_platform_search` çağır. `topic` ana sorgu, `query_variants` modelin
   hazırladığı en fazla dört alternatif sorgudur. Varsayılan bütün platformlar
   kullanılır. `platforms` ile daraltılırsa kapsam sınırını raporla.
3. Dönen site filtresiz görevleri **önce**, platform görevlerini sonra host'un
   gerçek web aracıyla yürüt. Aynı platformda her alan adı/varyant ayrı görevdir.
4. Sonuçlara göre yeni terimleri ve bağlamı sorgula. İlgili kaynakların
   kaynakçaları ve ileri atıf takibi ayrı tamamlayıcı işlemlerdir. Tek bir
   sorgunun ilk sonuçları, platformun tamamının tarandığı anlamına gelmez.
5. Her gerçek çağrı için `task_id`, `engine`, `searched_at`, `status` ve
   bulunan yayınları kaydet. `collect_platform_results` ile birleştir.
6. Sonuçtaki `records` listesini JSON olarak araştırma klasöründe sakla;
   `build_literature_audit.py --additional ...` ile mevcut havuza ve bağımsız
   bilinen yayın listesine karşı kontrol et.
7. Kullanıcıya başlık, yıl, bağlantı, yayın türü, neden ilgili olduğu ve okuma
   düzeyiyle bir tablo sun. Eksik sorgu/erişimleri ayrıca göster.

Yeni MCP araçları arama sağlayıcısı çalıştırmaz: planı modele verir ve modelin
host aracıyla yaptığı çağrıların sonuçlarını düzenler. Normal web araması
Google Scholar araması diye sunulmaz. `web_url` normal web bağlantısı,
`scholar_url` isteğe bağlı Scholar bağlantısıdır; ikisinin oluşturulması
aramaların yapıldığı anlamına gelmez.

## Kaynak alan adları

| Platform | Alan adları |
|---|---|
| Cochrane | `cochranelibrary.com`, `cochrane.org` |
| PubMed | `pubmed.ncbi.nlm.nih.gov` |
| NICE / WHO | `nice.org.uk`, `who.int` |
| ScienceDirect | `sciencedirect.com` |
| Taylor & Francis / Routledge | `tandfonline.com`, `taylorfrancis.com` |
| Springer Nature | `link.springer.com`, `nature.com` |
| Wiley | `onlinelibrary.wiley.com` |
| SAGE | `journals.sagepub.com` |
| APA | `psycnet.apa.org` |
| Cambridge | `cambridge.org` |
| Oxford | `academic.oup.com` |
| BMJ | `bmj.com` |
| JAMA | `jamanetwork.com` |
| PsychiatryOnline | `psychiatryonline.org` |
| Ovid / LWW | `ovid.com`, `journals.lww.com` |

Bu alanlar kod ve kavram haritasında aynı katalogdan gelir. Kaynak listesi
keşfi sınırlayan beyaz liste değildir: site filtresiz sorgular diğer
yayıncıları, tezleri ve arşivleri de kapsama almak içindir.

```text
site:cochranelibrary.com de-escalation aggression
site:cochrane.org de-escalation aggression
site:sciencedirect.com de-escalation aggression
site:taylorfrancis.com de-escalation aggression
```

`site:` araması ilgili sitenin veritabanında eksiksiz arama yapmaz; arama
motorunun indeksini sorgular. Cochrane web sayfalarını bulmak CENTRAL'ın
tamamında tarama yapıldığı anlamına gelmez.

## Kayıt sözleşmesi

`prepare_platform_search` çıktısındaki planı aynen koruyun. Bir gerçek arama
için `runs` öğesi şu biçimdedir (aşağıdaki kayıt yalnızca şablondur):

```json
{
  "task_id": "Q2",
  "status": "ok",
  "engine": "host_web_search",
  "searched_at": "2026-01-01T00:00:00Z",
  "results": [
    {
      "title": "Kaynağın doğrulanan başlığı",
      "url": "https://example.org/publication",
      "read_level": "snippet",
      "excerpt": "Gerçekte görülen arama özeti",
      "relevance_note": "Bu kaynağın araştırma sorusuyla ilişkisi"
    }
  ]
}
```

Görev kimliği planda bulunmalı; gerçek servis ve tarih zorunludur.
Başarısız arama sonuç içeremez; kısmi sonuç için `partial` kullanılır.
Aynı görevde başarı ve hata birlikte varsa durum `partial` kalır.
Hedef alan adı dışındaki sonuçlar uyarıyla korunur; sessizce elenmez.
Aynı URL farklı sorgularda bulunursa tüm sorgu/servis izleri saklanır.

Yalnızca arama özetini görmek `snippet`, asıl abstract'ı okumak `abstract`
olarak kaydedilir. `abstract` metni yalnızca abstract/fulltext okuma düzeyinde
kabul edilir. `quality_status=not_assessed`, `index_status=not_verified`
kalır; site veya DOI biçimi kalite/indeks doğrulaması sayılmaz.

Keşifte Q1/Q2, yüksek atıf, güncellik veya yalnızca RCT filtresi uygulanmaz.
Bu ölçütler önemli yeni yayınları, kavramsal çalışmaları ve kitap bölümlerini
kaçırabilir. Konu/yöntem uygunluğu sonraki değerlendirmedir; hiçbir çıktı
eksiksizlik garantisi vermez.

## Süre ve sağlayıcı kotası

Hız hedefi veya süre dolunca tamamlandı sayma kuralı yoktur. Varsayılan
parti üç sorgudur; aynı sağlayıcıda sıralı, bağımsız API sağlayıcılarında
en fazla iki paralel arama önerilir. Farklı `site:` hedefleri aynı web
arama sağlayıcısının kotasını paylaşır.

Her partiden sonra `collect_platform_results` çıktısındaki `checkpoint`
araştırma klasöründe saklanır. Sonraki çağrıda bu checkpoint'in `plan` ve
`runs` alanları yeni gerçek arama kayıtlarıyla birlikte kullanılır.
`resume.pending_task_ids` bitmemiş işleri, `ready_task_ids` çalıştırılabilir
işleri, `next_batch_task_ids` sonraki küçük partiyi gösterir. Sağlayıcının
bildirdiği `retry_after_seconds` arama kaydına eklenir; `provider_retry_at`
zamanından önce aynı sağlayıcıya dönülmez. Bekleyen kaynaklar tamamlanmış
sayılmaz; bu sırada bağımsız bir sağlayıcıda ilerlenebilir.

API katmanı saniye ve HTTP-date biçimindeki `Retry-After` değerini kısaltmaz.
Uzun bekleme MCP çağrısını kilitlemek yerine `rate_limited`, bekleme süresi
ve yeniden deneme zamanı olarak raporlanır. Bu alanlar tarama HTML'lerine
taşınır. Kaynak/sorgu hataları eski başarılı sonuçları silmez.
