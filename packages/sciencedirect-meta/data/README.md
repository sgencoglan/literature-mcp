# Journal rank data

`journal_rank` aracı, SCImago Journal Rank 2024 verisini yerel bir gzip CSV
dosyasından okur. Beklenen alanlar: `Rank`, `Title`, `SJR`, `SJR Best Quartile`,
`Categories`, `Publisher`, `Issn`, `Coverage`.

- Orijinal veri: <https://www.scimagojr.com/journalrank.php>
- Kullanılan açık ayna: <https://github.com/WandLZhang/scimagojr_2024>
- Erişim tarihi: 2026-10-19

## Veri dosyasını indirme

Veri seti telif/lisans koşullarına tabi olabileceği için bu depoda
dağıtılmaz. Bir kez indirin:

```bash
bash scripts/fetch_scimago.sh
```

Farklı bir ayna veya dosya için:

```bash
SCIMAGO_URL="https://.../scimagojr_2024.csv.gz" bash scripts/fetch_scimago.sh
# veya
export JOURNAL_RANK_CSV="$HOME/data/scimagojr_2024.csv.gz"
```

## Notlar

- `journal_rank` çalışma sırasında SCImago sitesine istek atmaz.
- Quartile değeri SCImago'nun `SJR Best Quartile` alanıdır; derginin en iyi
  kategori quartile'ıdır.
- Q1 en yüksek, Q4 en düşük gruptur. Bu alan bir kalite ölçütü değil, yalnızca
  bibliyometrik bağlamdır.
- Veriyi yeniden dağıtmadan önce SCImago'nun güncel kullanım koşullarını
  kontrol edin.
