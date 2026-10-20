# Public repoya geçiş kontrolü

Bu depo özel (private) çalışma için hazırlandı. Public yapmadan önce aşağıdaki
adımları uygulayın.

## 1. Kişisel veri ve dosya kontrolü

```bash
git status --short
git ls-files
git grep -nE '/home/[a-z]|file://|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY'
```

Depoda **bulunmaması gerekenler**:

- PDF'ler ve tam metinler,
- `indexes/`, `projects/`, `outputs/`,
- kişisel `projects.json`, `manifest.csv`, `analysis_updates.json`,
- `.venv/`, `.env`, API anahtarları, oturum belgeleri,
- SCImago CSV'si (lisans nedeniyle; `scripts/fetch_scimago.sh` kullanılır).

`bash scripts/validate_all.sh` bu kontrollerin bir kısmını otomatik yapar.

## 2. Yer tutucuları düzeltin

- `README.md` içindeki `<private-repo-url>` ve `/path/to/...` örneklerini
  gerçek kurulum yollarıyla değiştirin.
- `config/opencode.example.json` yalnızca örnek kalmalı; gerçek `opencode.json`
  dosyasını commit etmeyin.
- `LICENSE` telif sahibini proje sahibine göre güncelleyin.
- `packages/sciencedirect-meta/pyproject.toml` içindeki paket adı/açıklaması
  public kullanım için gözden geçirin.

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
.venv/bin/pip install jsonschema
bash scripts/validate_all.sh
```

GitHub Actions iş akışı `.github/workflows/ci.yml` içindedir. Public repoda
branch protection ve zorunlu CI kontrolü açılmalıdır.

## 5. Repo oluşturma sırası

1. Yerel depoyu hazırlayın: `git init`, `git add .`, `git commit`.
2. GitHub'da **private** repo oluşturun; remote ekleyip push edin.
3. Bir kez daha `git ls-files` ve `git grep` ile sızıntı kontrolü yapın.
4. README, ekran görüntüsü ve örnek çıktıları gözden geçirin.
5. Ancak bundan sonra public görünürlüğe geçin.

## 6. Public sonrası eksikler

- İngilizce README veya iki dilli dokümantasyon,
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
- sürüm etiketleri ve `CHANGELOG.md`,
- `paperqa-local` için bağımlılıkları taklit eden birim testleri,
- Docker/uv tabanlı tekrarlanabilir kurulum (isteğe bağlı).
