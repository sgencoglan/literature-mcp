# Araç Kataloğu

İki MCP sunucusunda toplam **28 araç** vardır. Makine okunabilir tam sürüm (JSON Schema dâhil): [`tool-catalog.json`](tool-catalog.json). Bu dosya, aynı katalogun insan okunabilir özetidir.

Yeniden üretmek için:

```bash
cd <repo>
bash scripts/dump_tool_catalog.sh
```

## sciencedirect-meta (19 araç)

Açık metadata kaynaklarını kullanır; LLM çağırmaz. `project` parametresi verilen araçlar yalnızca o projenin klasöründe çalışır.

### Arama ve metadata

| Araç | Amaç | Zorunlu girdi | Önemli isteğe bağlı | Çıktı |
|---|---|---|---|---|
| `search_sciencedirect` | Elsevier/ScienceDirect endeksli makale arama (OpenAlex + Crossref PII; siteye girmez) | `query` | `limit`, `year_from`, `year_to`, `open_access_only` | DOI, metadata, öncelikli linkler |
| `search_pubmed` | PubMed E-utilities araması | `query` | `limit` | Abstract, DOI, PMID |
| `search_europepmc` | Europe PMC REST araması | `query` | `limit` | Abstract, DOI, PMID, atıf, OA PDF |
| `search_all` | OpenAlex + PubMed + Europe PMC birleşik arama | `query` | `limit`, yıl aralığı, `priority_only`, `allowed_publishers` | Tekilleştirilmiş kayıtlar + link önceliği |
| `get_article` | DOI veya PMID ile tek makale | `identifier` | `id_type` | Metadata, abstract, atıf, linkler |
| `get_links` | Tek DOI/PMID için öncelikli linkler | `identifier` | `id_type` | `links`, `preferred_url`, `publisher_url` |
| `search_literature` | OpenAlex + PubMed + Europe PMC + Crossref DOI arama; `local_pdf` ekler | `query` | `sources`, `limit`, yıl aralığı, `priority_only`, `allowed_publishers`, `include_local_pdf`, `project` | DOI, metadata, yerel PDF eşleşmesi |
| `deep_research` | Soruyu facet'lere bölüp çok kaynaklı arama | `question` | `subtopics`, `max_subtopics`, `results_per_topic`, yıl aralığı, `sources`, `priority_only`, `allowed_publishers` | Facet bazlı DOI sonuçları |

### Doğrulama ve değerlendirme

| Araç | Amaç | Zorunlu girdi | Önemli isteğe bağlı | Çıktı |
|---|---|---|---|---|
| `verify_doi_and_publisher` | Crossref + doi.org doğrulaması, yayıncı, Elsevier PII | `doi` | — | Doğrulama sonucu, yayıncı, linkler |
| `doi_provenance` | DOI hangi veritabanlarında var? | `doi` | — | Crossref/OpenAlex/Europe PMC/PubMed kayıt kimlikleri |
| `journal_rank` | SCImago 2024 Q1–Q4, SJR, kategori | `journals` | `include_categories` | Quartile ve dergi metrikleri |

### Proje ve yerel tam metin

| Araç | Amaç | Zorunlu girdi | Önemli isteğe bağlı | Çıktı |
|---|---|---|---|---|
| `list_projects` | Kayıtlı projeleri listeler | — | — | Proje, PDF, DOI, manifest durumu |
| `project_audit` | Projeyi DOI bazında denetler | `project` | `include_quartiles`, `check_retractions`, `max_dois` | Metadata, kaynak kimliği, atıf, Q, retraction |
| `read_paper` | Yerel PDF'ten metin/sayfa okur | — (argümansız: kütüphane listesi) | `identifier`, `pdf_path`, `page_start`, `page_end`, `project` | Metin, sayfa aralığı |
| `compare_studies` | Yöntem/örneklem/bulgu/sınırlılık tablosu | — | `identifiers`, `query`, `limit`, `sources`, `project` | Karşılaştırma tablosu |
| `evidence_check` | İddiaları cümlelerle lexical eşleştirir | `claims` | `identifier`, `pdf_path`, `text`, `top_k`, `project` | `strong`/`moderate`/`weak`/`not_found` + cümleler |
| `library_status` | PDF envanteri ve algılanan DOI'ler | — | `project` | Dosya listesi + DOI eşleşmeleri |
| `analysis_updates` | Kayıtlı denetim/matris verisini okur | — | `doi`, `entry_id`, `query`, `include_*`, `project` | Kayıtlı analiz (varsa) |
| `export_review` | Markdown/CSV/JSON rapor yazar; `project` verilirse proje çıktı klasörüne | `title` | `project`, `sections`, `content`, `references`, `claims`, `format`, `filename`, `output_path` | Diske yazılan rapor |

## paperqa-local (9 araç)

PaperQA2 indeksleri üzerinde çalışır. `paperqa_search` ve `paperqa_read_pages` LLM çağırmaz; `paperqa_ask` yerel Qwen modelini kullanır, sunucu kapalıysa llama.cpp'yi otomatik başlatır ve taslak üretir.

| Araç | Amaç | Zorunlu girdi | İsteğe bağlı | Çıktı | LLM |
|---|---|---|---|---|---|
| `paperqa_create_workspace` | Seçilen proje kökünde 00–03 akış klasörlerini açar; kayıt veya akış seçimi yapmaz | `project_directory` | `name` | Akış klasörleri + akışa özel proje adları | Hayır |
| `paperqa_projects` | Kayıtlı projeleri listeler | — | — | Proje + indeks durumu | Hayır |
| `paperqa_register_project` | PDF klasörünü kaydeder; kullanıcı proje klasörü olan `output_directory` zorunludur | `name`, `paper_directory`, `output_directory` | `title`, `description`, `include_subdirectories`, `include_files_without_doi`, `refresh_manifest`, `enrich_metadata`, `index_directory`, `index_name` | Proje kaydı + proje klasöründeki manifest | Hayır |
| `paperqa_build_index` | Manifest → PaperQA2 indeksi | `project` | `rebuild` | İndeks | Hayır (embedding) |
| `paperqa_status` | İndeks durumu | `project` | — | Dosya/doküman/parça sayısı | Hayır |
| `paperqa_search` | Proje içinde semantik arama | `project`, `query` | `k`, `max_chars` | Parçalar + DOI + sayfa adayları | Hayır |
| `paperqa_read_pages` | PDF'ten sayfa metni | `project`, `doi` | `page_start`, `page_end`, `max_chars` | Sayfa metni | Hayır |
| `paperqa_llm_status` | llama.cpp sunucu durumu (başlatmaz) | — | `timeout_seconds` | Erişim, model listesi, otomatik yönetim durumu | Hayır |
| `paperqa_ask` | Yerel Qwen ile sentezlenmiş taslak cevap; iddialar sayfada doğrulanmalı, çıktı özgün yeniden yazımı garanti etmez | `project`, `question` | `evidence_k`, `max_sources`, `timeout_seconds` | Taslak cevap + kaynaklar | Evet |

## Kanıt değeri

| Çıktı | Kanıt sayılır mı? | Neden |
|---|---|---|
| `paperqa_search` parçası | Doğrulama sonrası evet | Aday cümle/DOI verir; sayfa `paperqa_read_pages` ile teyit edilir |
| `paperqa_read_pages` | Evet | PDF sayfa metni |
| `read_paper` | Evet | PDF metni |
| `paperqa_ask` | Hayır | Yerel 3B model taslağı; atıf hatası yapabilir |
| `evidence_check` | Hayır (yardımcı) | Lexical benzerlik; entailment değil |
| `compare_studies` | Hayır (yardımcı) | Özet tablo |
| `get_article` abstract | Bağlam | Tam metin yoksa kanıt yerine geçmez |
| `journal_rank` | Bağlam | Dergi metriği; makale kalitesi kanıtı değil |
