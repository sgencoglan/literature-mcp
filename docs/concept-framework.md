# Konu başlığından kavram çerçevesi

`scripts/build_concept_map.py` artık JSON/HTML kavram haritasına bir
`framework` alanı ekler. Çerçeve; kapsam, boyutlar, kaynak pasajları, sözlük
tanımları, ilişki önerileri ve çalıştırılmamış arama bağlantılarından oluşur.
Şeması: [`concept-framework.schema.json`](../schemas/concept-framework.schema.json).

## 1. Başlıkla aday keşfi

Depo kökünde, bağımlılıklar kurulu Python ile çalıştırın:

```bash
python3 scripts/build_concept_map.py /path/to/research-workspace \
  --phase 1 --domain psychology \
  --title "Araştırılacak Türkçe başlık" \
  --query-en "English topic and context"
```

Tıp/psikolojide varsayılan kaynak PubMed, eğitimde OpenAlex'tir.
`--discovery-source openalex` veya `--discovery-source pubmed` ile değişir.
Bu komut birden çok veritabanını kapsayan tam literatür taraması değil,
terim keşfi için sınırlı örneklem toplar. Örneklem, MeSH indekslemesi
olmayan yeni yayınları da özetleri mevcutsa aday keşfinde kullanabilir.

Başlığın İngilizce çevirisini kod kendiliğinden üretmez; `--query-en`
kullanıcı veya çalışan yapay zekâ ajanı tarafından hazırlanır. Otomatik
adaylar kelime öbekleridir; anlamlı kavram ve doğru anchor oldukları henüz
doğrulanmamıştır. Eksik veya yanlış kavramlar için tohum girişi kullanın.

`discovery_coverage`, başarılı boş sonucu API hatasından ayırır. Arka plan
örneklemi yoksa ayırt edicilik hesaplanmaz. Aynı yayının yinelenen kayıtları
destek sayısını artırmaz. Sık geçen bir adayın `role: anchor` olması bir
öneridir; `validation_status: proposed` olarak kalır.

## 2. Kavram ve kapsam taslağını düzenleme

[`concept-seed.example.json`](../examples/concept-seed.example.json)
şablonunu **araştırma çalışma klasörünüze** kopyalayıp doldurun. Başlığı şu
boyutlarda ayrıştırın: olgu, hedef grup, bağlam, müdahale, sonuç, kuram,
ölçüm, etik. Bilinmeyen boyutu boş bırakın; model tahminini tanım diye
yazmayın. Çerçeve eksik boyutları raporlar.

```bash
python3 scripts/build_concept_map.py /path/to/research-workspace \
  --phase 1 \
  --concept-seed /path/to/research-workspace/concept-seed.json \
  --mesh
```

MeSH anahtar istemez. İki işlem ayrı tutulur:

- NLM RDF sözlüğünde **tam etiket eşleşmesi**: kimlik, tanım ve ağaç
  konumları `mesh_entries` içine yazılır. Ağaç konumu alt terim sanılmaz.
  Terimin proje bağlamına uygunluğu yine değerlendirilmelidir. Yalnızca
  tam etiket aranır; giriş terimiyle arama şu an ayrıca desteklenmez.
- PubMed sonuçlarındaki **birlikte-görülme**: `related_mesh` içinde PMID
  iziyle tutulur; eş anlamlıya veya otomatik sorgu genişletmesine dönüşmez.

NLM'nin [RDF servisi](https://id.nlm.nih.gov/mesh/) ve
[PubMed E-utilities](https://www.nlm.nih.gov/dataguide/eutilities/how_eutilities_works.html)
kullanılır. Ağ hataları raporlanır; sözlük karşılığı uydurulmaz.

`evidence` kayıtlarında `source_id`, `passage`, `read_level`, mümkünse
`doi`, `pmid`, `title`, `field` verin. Kodun örneklemden çıkardığı pasajlar
terim görülmesini gösterir. Dışarıdan eklenen pasaj ve tanımların doğruluğu
ayrıca denetlenir. İlişkiler kaynak eklense bile otomatik onaylanmaz.

## 3. Çıktıyı kullanma

`01_konu_belirleme/02_kavram_haritasi_<zaman>.html` dosyasını açın:

- Kavram boyutları ve eksik kapsamı inceleyin.
- Kaynak kimliği, başlık/özet pasajı ve MeSH tanımını ayrı okuyun.
- PubMed için `[Title/Abstract]` ve doğrulanmış sözlük adları için
  `[MeSH Terms]` sorgularını kullanın.
- Scholar bağlantıları her yayıncı için ayrı `site:` sorgusu açar.
  Site filtresiz, eş anlamlıları da içeren sorgular ana keşif adımıdır;
  yayıncı sorguları tamamlayıcıdır.
  Bunlar hazır bağlantılardır; Scholar aramasının çalıştırıldığı veya
  sonuçlarının toplandığı anlamına gelmez. Otomatik Scholar taraması yoktur.

Önce geniş olgu taraması, sonra hedef grup/bağlam/müdahaleden birini ekleyen
odaklı taramalar hazırlanır. Tüm boyutların aynı sorguda zorunlu tutulması
önlenir. Arama sorguları insan/ajan tarafından sonuçlarına göre iyileştirilir.

Sonraki aşamalar en son değiştirilmiş zaman damgalı haritayı yükler.
Açıkça verilen `--concept-seed`, önceki haritadan önceliklidir.
Yeni başlık/sorgu ile aşama 1 yeniden çalıştırılırsa eski kavramlar sessizce
devralınmaz. `--input` ile belirli bir harita seçilebilir.

## Çevrimdışı tekrar üretme

`--corpus` şu yapıda bir JSON alır:

```json
{
  "records": [
    {
      "id": "fixture-1",
      "title": "Example construct in an example setting",
      "abstract": "Example construct is discussed here."
    }
  ]
}
```

```bash
python3 scripts/build_concept_map.py /path/to/research-workspace \
  --title "Geliştirme denemesi" --query-en "example construct" \
  --corpus /path/to/corpus.json
```

Bir yayından güvenilir kavram keşfi yapılmaz; örnek yalnızca dosya biçimini
gösterir. `--corpus` ağ araması yapmaz ve `--mesh` ile birleştirilemez.
Doğrudan bir dil modeli çağrısı eklenmedi: modeli kullanan ajan tohum
dosyasını hazırlayabilir; kod kaynak toplama ve izlenebilir raporu yürütür.

Bu araç bir araştırma/yazım oturumu başlatmaz; kişisel PDF, indeks veya
manifestlere dokunmaz. Mevcut beş aşamalı iş akışının onay kapıları geçerlidir.

Kaynak havuzu oluştuktan sonra [eksik kaynak denetimi](literature-audit.md)
ile ek sonuçları ve bilinen önemli yayınları karşılaştırın.
