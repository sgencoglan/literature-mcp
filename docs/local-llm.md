# Yerel LLM: llama.cpp

`paperqa_ask` gerektiğinde yerel modeli kullanır ve llama.cpp sunucusunu
otomatik başlatır. Bu belge, bu makine sınıfı için arka uç ve model seçimini,
llama.cpp kurulumunu, otomatik yaşam döngüsünü ve OpenCode entegrasyonunu
açıklar.

> **Temel kural değişmedi:** Yerel model yalnızca **taslak/özet** üretir.
> Kanıt; `paperqa_search` + `paperqa_read_pages` ile sayfa düzeyinde doğrulanır.
> Model seçimi rapor kalitesinin tek belirleyicisi değildir.
> Yeni bölüm taslağında doğrulanmış bulgular paragraf bağlamına uygun özgün
> cümlelerle aktarılır; `paperqa_ask` bunu kendiliğinden garanti etmez.

## Kısa karar

| Soru | Karar |
|---|---|
| Arka uç | **llama.cpp** (tek desteklenen arka uç) |
| Varsayılan model | **Qwen2.5-3B-Instruct Q4_K_M** (Türkçe ve talimat takibi daha güvenli) |
| Sayfa kanıtı | **PyMuPDF** kalır; `pymupdf4llm` yalnızca yardımcı çıkarım için |
| OpenCode | `providers.llamacpp` ile `/models` altında görünür; ajan oturumu için 16k+ bağlam gerekir |

### Neden llama.cpp?

- llama.cpp doğrudan GGUF çalıştırır; ayrı bir model yöneticisi veya daemon
  katmanı yoktur. Bu makinede ek servis yükü ve model kopyası oluşmaz.
- llama.cpp `llama-server` OpenAI uyumlu `/v1/chat/completions` sunar; hem
  PaperQA2/LiteLLM hem OpenCode aynı uç noktayı kullanabilir.
- Bayraklar (`-c`, `-t`, `-ngl`, `--temp`) açıkça kontrol edilir.
- Tek ikili + tek GGUF ile sürüm sabitlenebilir; güncelleme bilinçli yapılır.

### Neden Qwen2.5-3B varsayılan?

Bu donanım sınıfında 3B–4B, Q4 quantized model güvenli üst sınırdır. Qwen2.5-3B-Instruct, Türkçe talimat takibi ve tutarlılık açısından bu sınıfta en dengeli seçenektir. Daha küçük modeller hızlı olsa da Türkçe akademik taslakta kalıp ifadelere ve yarım cümlelere daha sık düşer; bu nedenle depo tek varsayılan modelle gelir.

## Donanım sınırı

Ölçülen hedef sistem:

- Intel i5-6300U, 2 fiziksel çekirdek / 4 iş parçacığı,
- 7,6 GB RAM, GPU yok (Intel HD 520),
- yaklaşık 4–5 GB kullanılabilir RAM.

Bu sınıfta güvenli üst sınır **3B–4B, Q4 quantized** modeldir. 7B model
(~4,7 GB ağırlık + bağlam + PaperQA2 yükü) RAM'i zorlar, swap'a düşer ve CPU'da
pratik olmayacak kadar yavaşlar.

| Model | Boyut (Q4_K_M) | Türkçe | Bu sistemde rol |
|---|---:|---|---|
| `Qwen2.5-3B-Instruct` | ~2,1 GB | Destekli | **Varsayılan denge** |
| `Qwen2.5-7B-Instruct` | ~4,7 GB | Destekli | Bu makinede önerilmez (swap) |

## llama.cpp kurulumu

Depo, sudo gerektirmeyen iki betik içerir:

```bash
# Qwen2.5-3B (varsayılan)
bash scripts/setup_llamacpp.sh
```

Betik şunları yapar:

- `~/.local/share/llama.cpp/llama-<sürüm>/` altına önceden derlenmiş
  `llama-server`/`llama-cli` indirir,
- Debian/Ubuntu minimal kurulumunda eksik olan `libgomp.so.1` dosyasını
  `apt-get download` + `dpkg-deb -x` ile yerel `lib/` klasörüne çıkarır,
- GGUF modelini `~/.local/share/llama-models/` altına indirir.

Model dosyaları ve llama.cpp ikilileri **depoya commit edilmez**.

### Sunucuyu başlatma

Normalde elle başlatma gerekmez. `paperqa_ask` çağrıldığında `paperqa-local`
MCP sunucusu sunucunun erişilebilir olup olmadığını kontrol eder; kapalıysa
`scripts/start_llamacpp.sh` ile başlatır ve model hazır olana kadar bekler.
Yalnızca kendi başlattığı sunucuyu, son istekten `PAPERQA_AUTO_STOP_IDLE`
saniye sonra durdurur. Elle başlatılan bir sunucuya dokunmaz.

```bash
# İsteğe bağlı: elle başlatma (MCP bunu sahiplenmez)
bash scripts/start_llamacpp.sh qwen
```

Otomatik yönetim varsayılan olarak açıktır:

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `PAPERQA_AUTO_START` | `1` | `paperqa_ask` sunucuyu gerektiğinde başlatsın |
| `PAPERQA_AUTO_STOP_IDLE` | `300` | Son istekten sonra durdurma süresi (sn); `0` kapatır |
| `PAPERQA_LLAMA_START_TIMEOUT` | `120` | Başlatma için en fazla bekleme (sn) |
| `PAPERQA_LLAMA_MIN_FREE_MB` | `1200` | Başlatmadan önce gereken boş RAM (MB); `0` denetimi kapatır |
| `PAPERQA_LLAMACPP_MODEL` | `qwen` | `start_llamacpp.sh` model seçimi |
| `PAPERQA_LLAMACPP_SCRIPT` | `scripts/start_llamacpp.sh` | Başlatma betiği yolu |
| `PAPERQA_LLAMACPP_LOG` | `/tmp/opencode/llama-server-auto.log` | Otomatik sunucu günlüğü |
| `PAPERQA_LLAMACPP_PIDFILE` | `~/.literature-mcp/llama-server.pid` | Sahiplik/pid dosyası |

> **Bellek notu:** Qwen2.5-3B Q4_K_M sunucusu yaklaşık 3,5–4 GB RSS kullanır.
> Boş RAM eşiğin altındaysa MCP sunucuyu başlatmaz ve `paperqa_ask` açık bir
> hata döndürür. `paperqa-local` PyMuPDF ve PaperQA2'yi tembel yüklediği için
> sunucu kapalıyken hızlı açılır; ağır model/embedding yükü oluşmaz.
>
> MCP süreci kapanırken kendi başlattığı sunucuyu durdurur. Çökme sonrası
> kalan sunucu, pid dosyası üzerinden bir sonraki `paperqa_ask` çağrısında
> sahiplenilir ve boşta kalınca durdurulur.

Varsayılan bayraklar:

```text
-m <model.gguf> --alias qwen2.5-3b-instruct
-c 8192      # bağlam penceresi
-t 2         # 2 fiziksel çekirdek; en hafif ve en hızlı ölçüm
-ngl 0       # GPU yok
--temp 0.1   # daha deterministik çıktı
--host 127.0.0.1 --port 8080 --jinja
```

`--jinja`, modelin kendi sohbet şablonunu ve varsa araç çağrısı biçimini
kullanmasını sağlar. `--alias`, OpenCode ve LiteLLM'in gördüğü model adıdır.

### Bayrak notları

- **`-c 8192`**: Bu makinede Qwen2.5-3B Q4_K_M ile test edildi. PaperQA
  taslakları için 4096 yeterlidir; OpenCode tek isteği için 8192 gerekir.
  Çok turlu OpenCode ajanı 16k+ bağlam ister; 8192'de ikinci istek bağlamı
  aşabilir.
- **`-t 2`**: 2 fiziksel çekirdeğin tamamı; hyper-threading'e taşmaz. Benchmarkta
  üretim hızı 2 iş parçacığında daha yüksekti (7,2 tok/s). `THREADS=4` ile
  kendi ölçümünüzü yapabilirsiniz.
- **`-ngl 0`**: GPU yok. Intel HD 520 llama.cpp tarafından hızlandırıcı olarak
  kullanılmaz.
- **`--temp 0.1`**: Özet/taslak için tekrarlanabilirliği artırır. Yaratıcı
  metin için 0.3–0.7 denenebilir.

## paperqa-local yapılandırması

Varsayılanlar llama.cpp'ye ayarlıdır; yalnızca farklı bir uç nokta/model
kullanıyorsanız ortam değişkenlerini verin:

```bash
export PAPERQA_LOCAL_LLM=qwen2.5-3b-instruct
export PAPERQA_LOCAL_API_BASE=http://127.0.0.1:8080/v1
export PAPERQA_LOCAL_MAX_TOKENS=400
export PAPERQA_LOCAL_TEMPERATURE=0.1
export PAPERQA_LOCAL_TIMEOUT=600
```

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `PAPERQA_LOCAL_LLM` | `qwen2.5-3b-instruct` | Model adı/alias |
| `PAPERQA_LOCAL_API_BASE` | `http://127.0.0.1:8080/v1` | OpenAI uyumlu uç nokta |
| `PAPERQA_LOCAL_API_KEY` | boş | Gerekirse; llama.cpp istemez |
| `PAPERQA_LOCAL_MAX_TOKENS` | `400` | Cevap başına üst sınır |
| `PAPERQA_LOCAL_TEMPERATURE` | `0.1` | Örnekleme sıcaklığı |
| `PAPERQA_LOCAL_TIMEOUT` | `600` | LiteLLM istek zaman aşımı (sn) |
| `PAPERQA_AUTO_START` | `1` | `paperqa_ask` için otomatik başlatma |
| `PAPERQA_AUTO_STOP_IDLE` | `300` | Otomatik durdurma için boşta süresi (sn) |
| `PAPERQA_LLAMA_START_TIMEOUT` | `120` | Otomatik başlatma bekleme süresi (sn) |
| `PAPERQA_LLAMA_MIN_FREE_MB` | `1200` | Gereken en az boş RAM (MB) |

Sunucunun durumunu `paperqa_llm_status` aracıyla doğrulayın. Araç,
`/v1/models` üzerinden erişilebilir modelleri listeler; ayrıca `auto_start`,
`auto_stop_idle_seconds`, `managed` ve varsa `managed_pid` alanlarını döndürür.
Araç sunucuyu **başlatmaz**; otomatik başlatma yalnızca `paperqa_ask` içinde
gerçekleşir.

## OpenCode `/models` entegrasyonu

`config/opencode.example.json` içindeki `providers.llamacpp` bölümünü kendi
`~/.config/opencode/opencode.json` dosyanıza ekleyin:

```json
{
  "providers": {
    "llamacpp": {
      "name": "llama.cpp (yerel)",
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": { "baseURL": "http://127.0.0.1:8080/v1" },
      "models": {
        "qwen2.5-3b-instruct": {
          "name": "Qwen2.5 3B Instruct (Q4_K_M, CPU)",
          "modelID": "qwen2.5-3b-instruct",
          "capabilities": {
            "tools": false,
            "input": ["text"],
            "output": ["text"]
          },
          "limit": { "context": 8192, "output": 512 }
        }
      }
    }
  }
}
```

Sonra OpenCode'u yeniden başlatıp `/models` açın; model
`llamacpp/qwen2.5-3b-instruct` olarak görünmelidir. Tek seferlik deneme:

```bash
opencode run --model llamacpp/qwen2.5-3b-instruct "Üç cümlelik Türkçe özet yaz."
```

**Araç desteği:** 3B modelde araç çağrısı güvenilir değildir. Bu nedenle
`capabilities.tools: false` verilir; model sohbet/taslak için kullanılır,
OpenCode'un dosya/terminal ajanı olarak değil. Daha büyük ve araç eğitimli bir
model kullanılırsa bu değer ve `--jinja` birlikte test edilmelidir.

## pymupdf4llm kullanılmalı mı?

**Hayır, sayfa kanıtı için değil.** Mevcut `paperqa_read_pages` PyMuPDF'in
`get_text("blocks", sort=True)` çıktısını kullanır. Bu çıktı, PDF'teki cümleyi
birebir karşılaştırmaya elverişlidir.

`pymupdf4llm.to_markdown(page_chunks=True)` sayfa numarası taşıyan Markdown
üretir; başlık, tablo ve liste yapısını korur. Ancak:

- boşlukları, tireleri ve satır sonlarını Markdown için yeniden düzenler,
- tabloları Markdown tablosuna çevirir,
- birebir alıntı eşleşmesini normalize etmeyi gerektirir.

Bu nedenle `pymupdf4llm` yalnızca **isteğe bağlı** bir yapı/indeks yardımcısı
olarak değerlendirilmelidir. Altın standart raporun `quote` alanı PyMuPDF
sayfa metniyle doğrulanmaya devam eder. `paperqa_read_pages` çıktısını
değiştirmek, sayfa doğrulamasını ve `report-kit` kalite kapısını riske atar.

## Benchmark

Ölçüm: Intel i5-6300U, 2 fiziksel çekirdek / 4 iş parçacığı, GPU yok,
7,6 GB RAM; llama.cpp b11954, Q4_K_M, `-ngl 0`, `-c 4096`, `--temp 0.1`.
Türkçe akademik paragraf istemi; 160 token üretim sınırı.

| Model | İş parçacığı | Üretim (tok/s) | Prompt (tok/s) |
|---|---:|---:|---:|
| Qwen2.5-3B-Instruct | 2 | 7,2 | 21,3 |
| Qwen2.5-3B-Instruct | 4 | 6,7 | 22,3 |

Notlar:

- **Qwen2.5-3B** Türkçe çıktı üretir; ancak 3B ölçeğinde cümleler kısa ve
  yer yer kalıp ifadelere yakındır. Taslak/özet için kullanılabilir, nihai
  kanıt veya düzeltme metni için değil.
- Üretim hızı 2 ve 4 iş parçacığında belirgin fark göstermedi. Toplam süre
  model yükleme ve disk önbelleği nedeniyle 13,8–34,8 s arasında değişti;
  tek koşuya dayanarak iş parçacığı sayısı seçilmemelidir.
- Ölçümler tek koşudur; arka plan yükü ve model sıcaklığı sonuçları
  oynatabilir. Kendi makinenizde
  `python3 scripts/benchmark_local_llm.py --threads 2,4` ile doğrulayın.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `libgomp.so.1: cannot open shared object file` | `bash scripts/setup_llamacpp.sh` yeniden çalıştırın; yerel `lib/` klasörünü kullanır. |
| `paperqa_llm_status` erişilemiyor | Sunucu kapalı olabilir; `paperqa_ask` otomatik başlatır. Elle denetim: `curl http://127.0.0.1:8080/v1/models` |
| `paperqa_ask` "yetersiz RAM" döndürüyor | Bellek kullanan uygulamaları kapatın veya `PAPERQA_LLAMA_MIN_FREE_MB` değerini düşürün. |
| Otomatik başlatma başarısız | `/tmp/opencode/llama-server-auto.log` son satırlarına bakın; `PAPERQA_LLAMA_START_TIMEOUT` değerini artırın. |
| Model listede yok | `--alias` ile `PAPERQA_LOCAL_LLM` aynı olmalı. |
| OpenCode modeli göstermiyor | OpenCode'u yeniden başlatın; `baseURL` `/v1` ile bitmeli. |
| Çok yavaş | `THREADS=2` deneyin; `-c 4096` ve `max_tokens=400` ile sınırlayın. |
| RAM/swap sorunu | 7B model kullanmayın; `free -h` ve `swap` kullanımını izleyin. |
