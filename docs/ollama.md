# Yerel Ollama modeli seçimi

Bu depo, `paperqa_ask` için yerel Ollama modeli kullanabilir. Ancak model
seçimi donanıma bağlıdır ve **rapor kalitesinin tek belirleyicisi değildir**.

## Bu makine sınıfı için ölçülen sınırlar

Örnek hedef sistem:

- Intel i5-6300U, 2 çekirdek / 4 iş parçacığı,
- 7,6 GB RAM, GPU yok (Intel HD 520),
- yaklaşık 4 GB kullanılabilir RAM.

Bu sınıfta güvenli üst sınır **3B–4B, Q4 quantized** modeldir. 7B model
(~4,7 GB ağırlık + bağlam + PaperQA2 yükü) RAM'i zorlar, swap'a düşer ve CPU'da
pratik olmayacak kadar yavaşlar.

| Model | Yaklaşık boyut | Bu sistemde değerlendirme |
|---|---:|---|
| `qwen2.5:1.5b-instruct` | ~1 GB | Hızlı; taslak/özet için temel. Kalite sınırlı. |
| `qwen2.5:3b-instruct` | ~2 GB | **Önerilen denge.** 4 GB boş RAM ile güvenli. |
| `qwen3:4b` | ~2,5 GB | Denenebilir; daha yeni Ollama ve biraz daha fazla RAM ister. |
| `qwen2.5:7b-instruct` | ~4,7 GB | Bu sistemde önerilmez; swap ve yavaşlık. |

## Öneri

1. Ollama'yı güncelleyin. Depodaki kurulum `0.3.0` gibi eski bir sürümse
   `qwen3` desteği olmayabilir.
2. Önce `qwen2.5:3b-instruct` ile deneyin:

```bash
ollama pull qwen2.5:3b-instruct
ollama run qwen2.5:3b-instruct "Kısa bir özet yaz."
```

3. `qwen3:4b` denemek için güncel Ollama ve en az ~4 GB boş RAM gerekir:

```bash
ollama pull qwen3:4b
```

4. PaperQA2 tarafında modeli ayarlayın (ortam değişkeni veya PaperQA2
   yapılandırması): `qwen2.5:3b-instruct`.

## Beklenti yönetimi

- CPU-only bir sistemde 3B model bile yavaştır; ilk yükleme ve uzun bağlam
  belirgin gecikme yaratır.
- Yerel model **taslak/özet** içindir. Kanıt; `paperqa_search` +
  `paperqa_read_pages` ile sayfa düzeyinde doğrulanır.
- Altın standart raporun kalitesi model boyutundan değil; kanıt matrisi,
  DOI/sayfa doğrulaması ve deterministik HTML şablonundan gelir.
- 7B'ye geçmek bu makinede kalite artışından çok bekleme süresi ve bellek
  baskısı üretir. Daha yüksek kalite gerekiyorsa yerel modeli büyütmek yerine
  API tabanlı daha güçlü bir model veya daha iyi donanım değerlendirilmelidir.
