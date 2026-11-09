# Arama Kapsam Raporu — ADHD okul performansı müdahale

- Proje: **ornek-proje**
- Oluşturma: 2026-11-08T12:00:00+00:00
- Sorgulanan kaynak: 4
- Tekil DOI: 18
- Yüksek kalite: 4
- Kanıt sınırlılığı: **Evet**

> **Kanıt sınırlılığı:** Bu konuda yüksek kaliteli kanıt sınırlı görünüyor. Yüksek kaliteli sonuç sayısı: 4 (eşik: 5). En yakın 3 çalışma: ADHD okul performansı müdahalesi: sistematik derleme (2025), DOI: 10.5555/example.2026.001; Sınıf temelli davranış müdahalesi (2024); Hibrit öğrenme ve dikkat (2023). Araştırma boşluğu olasılığı yüksektir.

## Kaynak uyarıları

- arxiv bu koşuda sorgulanmadı: preprint istenmedi (include_arxiv=false).
- clinicaltrials bu koşuda sorgulanmadı: klinik çalışma araması istenmedi.

## Sorgu ve genişletme

- Orijinal sorgu: `ADHD okul performansı müdahale`
- Genişletilmiş sorgular:
  1. `attention deficit hyperactivity disorder school performance intervention`
  2. `ADHD academic achievement behavioral intervention children`
- MeSH: `Attention Deficit Disorder with Hyperactivity[Mesh]`, `Academic Performance`
- Dil: Türkçe → İngilizce
- Dönüşümler: synonym, MeSH, language
- Not: Türkçe sorgu İngilizce eş anlamlılara çevrildi.
- Not: PubMed ve Europe PMC için MeSH terimleri kullanıldı.

## Kanıt yoğunluğu

| Gösterge | Değer |
|---|---|
| Yüksek kaliteli | 4 |
| Yüksek kaliteli (katı: Q1/Q2 + atıf + RCT/SR/MA) | 2 |
| Q1 dergi | 7 (%39) |
| Son 5 yıl | 11 (%61) |
| RCT | 3 |
| Sistematik derleme / meta-analiz | 2 |
| Klinik çalışma | 1 |
| Preprint | 2 |
| Trend (son 3 yıl) | artıyor (2024: 4, 2025: 6, 2026: 5) |

## Publisher ve fulltext erişim dağılımı

| Platform / yayıncı | Kayıt | Oran |
|---|---|---|
| Ovid LWW | 2 | %11 |
| ScienceDirect | 5 | %28 |
| SpringerLink | 2 | %11 |
| Wiley | 2 | %11 |
| Taylor & Francis | 3 | %17 |
| Diğer yayıncı | 2 | %11 |
| Yayıncı bilinmiyor | 2 | %11 |

- Açık erişim: 6 (%33)
- Preprint: 2 (%11)
- PDF bağlantısı: 8 (%44)

## Kaynak bazında kapsam

| Kaynak | Durum | Dönen | Tekil DOI | Yüksek kalite | İstenen limit | Süre | Not |
|---|---|---|---|---|---|---|---|
| OpenAlex | Tamam | 10 | 9 | 4 | 10 | 640 ms | OpenAlex relevance search; yıl/OA filtreleri uygulandı. |
| Semantic Scholar | Tamam | 10 | 8 | 3 | 10 | 1180 ms | Atıf ve influential citation alanları dahil. |
| PubMed | Tamam | 8 | 7 | 3 | 8 | 520 ms | MeSH/eş anlamlı genişletme ajan tarafından sağlandı. |
| Europe PMC | Tamam | 7 | 6 | 2 | 7 | 430 ms | Europe PMC REST; OA PDF bağlantıları dahil. |
| arXiv | Sorgulanmadı | — | — | — | — | — | preprint istenmedi (include_arxiv=false) |
| ClinicalTrials.gov | Sorgulanmadı | — | — | — | — | — | klinik çalışma araması istenmedi |
| **Toplam (tekilleştirilmiş)** | — | 35 | 18 | 4 | — | — | — |

## Öne çıkan sonuçlar

| # | Kaynak | Çalışma türü | Skor | Atıf | DOI |
|---|---|---|---|---|---|
| 1 | ADHD okul performansı müdahalesi: sistematik derleme | Systematic review / meta-analysis | 0.820 | 44 | [10.5555/example.2026.001](https://doi.org/10.5555/example.2026.001) |
| 2 | Sınıf temelli davranış müdahalesi | Randomized controlled trial | 0.710 | 19 | [10.5555/example.2026.002](https://doi.org/10.5555/example.2026.002) |
| 3 | Hibrit öğrenme ve dikkat | Cohort study | 0.540 | 6 | — |

## Yöntem ve tanımlar

- **score_formula:** 0.35 × anlamsal alaka + 0.25 × log10(atıf+1)/4 + 0.15 × güncellik + 0.15 × dergi quartile + 0.10 × çalışma türü
- **recency:** Son 2 yıl 1.0; 10 yıl ve üzeri 0.0; arası doğrusal azalır.
- **quartile:** Q1=1.0, Q2=0.70, Q3=0.40, Q4=0.15, bilinmiyorsa 0.30.
- **study_type:** Sistematik derleme/meta-analiz ve RCT=1.0; klinik çalışma (girişim)=0.80; kohort/yarı deneysel=0.60; vaka-kontrol=0.50; kesitsel=0.40; nitel=0.35; tanımsız=0.25; preprint=0.05.
- **preprint_penalty:** Preprint sonuçların skoru 0.85 ile çarpılır ve is_preprint=true işaretlenir.
- **high_quality:** Yüksek kalite: preprint değil, skor ≥ 0.60 ve çalışma türü bileşeni ≥ 0.40.
- **high_quality_strict:** Katı yüksek kalite: Q1/Q2 + en az 10 atıf + RCT veya sistematik derleme/meta-analiz.
- **trend:** Son 3 yılın yıllık yayın sayısı eğimi; |eğim| < 0.34 ise sabit kabul edilir.
- **evidence_scarcity:** Yüksek kaliteli sonuç sayısı 5'in altındaysa evidence_scarcity=true olur.

_Bu rapor yalnızca sorgulanan açık metadata kaynaklarının kapsamını gösterir. Skor bir ön eleme göstergesidir; kanıt değildir._
