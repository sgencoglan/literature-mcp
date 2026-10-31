# Public repo kontrolü

Son public sürüm **v2.3.0**'dır. Bu belge v2.4.0 ve sonraki sürümleri
yayımlarken uygulanacak kontrol listesini korur.

## 1. Kişisel veri ve dosya kontrolü

```bash
git status --short
git ls-files
git grep -nE '/home/[a-z]|file://|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY'
git log -p --all -- . ':!LICENSE' | grep -nE '/home/[a-z]|Downloads/|ghp_|github_pat_|sk-[A-Za-z0-9]{20,}'
```

Depoda **bulunmaması gerekenler**:

- PDF'ler ve tam metinler,
- `indexes/`, `projects/`, `outputs/`,
- kişisel `projects.json`, `manifest.csv`, `analysis_updates.json`,
- yayımlanmamış bölüm metinleri ve düzeltilmiş HTML çıktıları,
- `.venv/`, `.env`, API anahtarları, oturum belgeleri,
- SCImago CSV'si (lisans nedeniyle; `scripts/fetch_scimago.sh` kullanılır).

`bash scripts/validate_all.sh` bu kontrollerin bir kısmını otomatik yapar.

## 2. Yer tutucuları düzeltin

- Public README'de gerçek repo URL'si (`https://github.com/sgencoglan/literature-mcp`)
  bulunur; `<private-repo-url>` kalmamalıdır.
- `config/opencode.example.json` yalnızca örnek kalmalı; gerçek `opencode.json`
  dosyasını commit etmeyin.
- `LICENSE` telif sahibini proje sahibine göre güncelleyin.
- Paket sürümleri (`pyproject.toml`) ile `CHANGELOG.md` ve git etiketi
  birbiriyle uyumlu olmalıdır.

## 3. Üçüncü taraf adları ve lisanslar

- ScienceDirect, Ovid LWW, SpringerLink, Wiley ve Taylor & Francis ticari
  markalarıdır. README'de bu platformlarla bağlantı iddiası kurulmadığını açıkça
  belirtin.
- SCImago verisinin lisans/atıf koşullarını doğrulayın; veri dosyasını dağıtmak
  yerine indirme betiği kullanın.
- PaperQA2 ve MCP bağımlılıklarının lisanslarını kontrol edin.

## 4. Test ve CI

```bash
python3 -m venv .venv
.venv/bin/pip install -e packages/sciencedirect-meta
.venv/bin/pip install -e packages/report-kit
.venv/bin/pip install jsonschema
bash scripts/validate_all.sh
```

GitHub Actions iş akışı `.github/workflows/ci.yml` içindedir. Public repoda
branch protection ve zorunlu CI kontrolü açılmalıdır.

## 5. Sürüm yayını sırası

1. Sürüm metadatası (`VERSION`, `pyproject.toml`, `__version__`), changelog ve README sürümünü eşleştirin.
2. Yerel depoyu hazırlayın: `git add .`, `git commit`.
3. `git tag -a v2.4.0 -m "Üç iş akışı ve proje çalışma alanları"`.
4. `git push origin main --tags`.
5. `gh release create v2.4.0 --title "v2.4.0" --notes-file <sürüm-notları>`.
6. Bir kez daha `git ls-files` ve `git grep` ile sızıntı kontrolü yapın.
7. Public görünürlüğü yalnızca kontrol listesi tamamsa değiştirin.

## 6. Public sonrası eksikler

- İngilizce README veya iki dilli dokümantasyon,
- `paperqa-local` için bağımlılıkları taklit eden birim testleri,
- Docker/uv tabanlı tekrarlanabilir kurulum (isteğe bağlı),
- örnek raporun ekran görüntüsü veya statik demo.
