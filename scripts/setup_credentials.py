#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAlex, PubMed ve Crossref için kimlik bilgilerini yapılandırır.

Betik yalnızca standart kütüphaneyi kullanır. Sırları depoya yazmaz; OpenCode
yapılandırmasındaki ``mcp.servers.sciencedirect-meta.environment`` bölümünü
günceller ve dosya iznini 600 yapar.

Kullanım:
    python3 scripts/setup_credentials.py
    python3 scripts/setup_credentials.py --project /path/to/project
    python3 scripts/setup_credentials.py --check
    python3 scripts/setup_credentials.py --email you@example.org \
        --openalex-key ... --pubmed-key ... \
        --semantic-scholar-key ...
    python3 scripts/setup_credentials.py --config ~/.config/opencode/opencode.json

Betik önce proje kökündeki (veya çalışma dizinindeki) ``setup.txt`` dosyasını
okur; bulamazsa eksik bilgileri sorar. ``setup.txt`` biçimi::

    email=you@example.org
    openalex_key=...
    pubmed_key=...
    semantic_scholar_key=...

Anahtarlar isteğe bağlıdır: tanımlanmazsa araçlar çalışır, ancak PubMed,
OpenAlex ve Semantic Scholar hız limitleri daha düşük olur.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

SERVER_NAME = "sciencedirect-meta"
DEFAULT_TOOL = "sciencedirect-meta-mcp"
SETUP_FILENAME = "setup.txt"

EMAIL_KEYS = {
    "email",
    "e_posta",
    "eposta",
    "mail",
    "contact",
    "contact_email",
    "crossref_mailto",
    "ncbi_email",
    "unpaywall_email",
}
OPENALEX_KEYS = {"openalex", "openalex_key", "openalex_api_key"}
PUBMED_KEYS = {
    "pubmed",
    "pubmed_key",
    "pubmed_api_key",
    "ncbi",
    "ncbi_key",
    "ncbi_api_key",
}
SEMANTIC_SCHOLAR_KEYS = {
    "semantic_scholar",
    "semantic_scholar_key",
    "semantic_scholar_api_key",
    "s2",
    "s2_key",
}


def _config_candidates() -> list[Path]:
    home = Path.home()
    candidates: list[Path] = []
    explicit = os.environ.get("OPENCODE_CONFIG", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend(
        [
            home / ".config" / "opencode" / "opencode.json",
            home / ".config" / "opencode" / "config.json",
            home / "Library" / "Application Support" / "opencode" / "opencode.json",
        ]
    )
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        candidates.append(Path(appdata) / "opencode" / "opencode.json")
    return candidates


def _resolve_config(explicit: Optional[str], create: bool) -> Optional[Path]:
    if explicit:
        return Path(explicit).expanduser()
    for candidate in _config_candidates():
        if candidate.is_file():
            return candidate
    if create:
        return Path.home() / ".config" / "opencode" / "opencode.json"
    return None


def _resolve_setup_file(
    explicit: Optional[str],
    project: Optional[str],
) -> Optional[Path]:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    candidates: list[Path] = []
    if project:
        candidates.append(Path(project).expanduser() / SETUP_FILENAME)
    candidates.extend(
        [
            Path.cwd() / SETUP_FILENAME,
            Path(__file__).resolve().parents[1] / SETUP_FILENAME,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _parse_setup_file(path: Path) -> Dict[str, str]:
    """Read ``key=value`` lines from setup.txt; ignore comments and blanks."""
    values: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Uyarı: {path} okunamadı: {exc}", file=sys.stderr)
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        key = re.sub(r"[\s\-]+", "_", key.strip().lower())
        value = value.strip().strip('"').strip("'").strip()
        if not value:
            continue
        if key in EMAIL_KEYS:
            values["email"] = value
        elif key in OPENALEX_KEYS:
            values["openalex"] = value
        elif key in PUBMED_KEYS:
            values["pubmed"] = value
        elif key in SEMANTIC_SCHOLAR_KEYS:
            values["semantic_scholar"] = value
    return values


def _warn_setup_permissions(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & 0o077:
        print(
            f"Uyarı: {path} diğer kullanıcılar tarafından okunabilir. "
            "Sırlar için `chmod 600` önerilir.",
            file=sys.stderr,
        )


def _load_config(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {}
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Hata: {path} geçerli JSON değil: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Hata: {path} bir JSON nesnesi değil.")
    return payload


def _server_entry(config: Dict[str, Any], create: bool) -> Dict[str, Any]:
    mcp = config.setdefault("mcp", {})
    servers = mcp.setdefault("servers", {})
    server = servers.get(SERVER_NAME)
    if server is None:
        if not create:
            raise SystemExit(
                f"Hata: yapılandırmada mcp.servers.{SERVER_NAME} bulunamadı. "
                "Önce config/opencode.example.json dosyasını kendi "
                "yapılandırmanıza uyarlayın veya --create kullanın."
            )
        repo = Path(__file__).resolve().parents[1]
        if os.name == "nt":
            binary = repo / ".venv" / "Scripts" / "sciencedirect-meta-mcp.exe"
        else:
            binary = repo / ".venv" / "bin" / "sciencedirect-meta-mcp"
        server = {"type": "local", "command": [str(binary)], "environment": {}}
        servers[SERVER_NAME] = server
    if not isinstance(server, dict):
        raise SystemExit(f"Hata: mcp.servers.{SERVER_NAME} bir nesne değil.")
    environment = server.setdefault("environment", {})
    if not isinstance(environment, dict):
        raise SystemExit(f"Hata: mcp.servers.{SERVER_NAME}.environment bir nesne değil.")
    return server


def _mask(value: str) -> str:
    value = value.strip()
    if not value:
        return "(boş)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]}"


def _prompt(label: str, current: str = "", secret: bool = False) -> str:
    suffix = f" [mevcut: {_mask(current)}; korumak için boş bırakın]" if current else ""
    prompt = f"{label}{suffix}: "
    try:
        if secret and sys.stdin.isatty():
            value = getpass.getpass(prompt)
        else:
            value = input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit("İptal edildi.")
    value = value.strip()
    return value or current


def _valid_email(value: str) -> bool:
    return "@" in value and "." in value.rsplit("@", 1)[-1]


def _write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _backup(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup)
    os.chmod(backup, 0o600)
    return backup


def _read_values(path: Optional[Path]) -> Dict[str, str]:
    if not path or not path.is_file():
        return {}
    config = _load_config(path)
    server = (config.get("mcp", {}).get("servers", {}) or {}).get(SERVER_NAME) or {}
    environment = server.get("environment") or {}
    return {str(k): str(v) for k, v in environment.items()}


def _print_summary(path: Path, values: Dict[str, str]) -> None:
    print(f"\nYapılandırma: {path}")
    print(f"  İletişim e-postası : {values.get('NCBI_EMAIL') or values.get('CROSSREF_MAILTO') or '(boş)'}")
    print(f"  OpenAlex anahtarı  : {_mask(values.get('OPENALEX_API_KEY', ''))}")
    print(f"  PubMed anahtarı    : {_mask(values.get('PUBMED_API_KEY', ''))}")
    print(f"  Semantic Scholar   : {_mask(values.get('SEMANTIC_SCHOLAR_API_KEY', ''))}")
    print(f"  NCBI aracı         : {values.get('NCBI_TOOL', DEFAULT_TOOL)}")
    print("  Anahtarlar isteğe bağlıdır; yoksa da araçlar çalışır.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenAlex/PubMed/Crossref kimlik bilgilerini OpenCode MCP yapılandırmasına yaz."
    )
    parser.add_argument("--config", help="opencode.json yolu (varsayılan: otomatik bul).")
    parser.add_argument("--project", help="setup.txt dosyasını içeren proje kökü.")
    parser.add_argument("--from-file", help="setup.txt yolu (varsayılan: proje kökü veya çalışma dizini).")
    parser.add_argument("--email", help="Crossref/NCBI/OpenAlex için iletişim e-postası.")
    parser.add_argument("--openalex-key", help="OpenAlex API anahtarı (isteğe bağlı).")
    parser.add_argument("--pubmed-key", help="PubMed/NCBI API anahtarı (isteğe bağlı).")
    parser.add_argument(
        "--semantic-scholar-key",
        help="Semantic Scholar API anahtarı (isteğe bağlı; hız limitini yükseltir).",
    )
    parser.add_argument("--check", action="store_true", help="Yalnızca mevcut durumu göster, yazma.")
    parser.add_argument("--create", action="store_true", help="Eksik yapılandırma dosyasını oluştur.")
    parser.add_argument("--non-interactive", action="store_true", help="Soru sorma; yalnızca bayrakları ve setup.txt'yi kullan.")
    args = parser.parse_args()

    path = _resolve_config(args.config, create=args.create)
    if path is None:
        print(
            "OpenCode yapılandırması bulunamadı.\n"
            "config/opencode.example.json dosyasını kopyalayıp yolları düzenleyin "
            "veya bu betiği --config <yol> ile çalıştırın.",
            file=sys.stderr,
        )
        return 1

    current = _read_values(path)
    if args.check:
        if not path.is_file():
            print(f"Yapılandırma yok: {path}", file=sys.stderr)
            return 1
        _print_summary(path, current)
        return 0

    email = (args.email or "").strip()
    openalex = (args.openalex_key or "").strip()
    pubmed = (args.pubmed_key or "").strip()
    semantic_scholar = (args.semantic_scholar_key or "").strip()

    setup_path = _resolve_setup_file(args.from_file, args.project)
    if args.from_file and not setup_path:
        print(f"Uyarı: setup.txt bulunamadı: {args.from_file}", file=sys.stderr)
    if setup_path:
        file_values = _parse_setup_file(setup_path)
        _warn_setup_permissions(setup_path)
        print(f"setup.txt bulundu: {setup_path}")
        found = [
            label
            for key, label in (
                ("email", "e-posta"),
                ("openalex", "OpenAlex anahtarı"),
                ("pubmed", "PubMed anahtarı"),
                ("semantic_scholar", "Semantic Scholar anahtarı"),
            )
            if file_values.get(key)
        ]
        if found:
            print("Otomatik alındı: " + ", ".join(found))
        else:
            print("setup.txt içinde tanınan bilgi bulunamadı; eksikler sorulacak.")
        email = email or file_values.get("email", "")
        openalex = openalex or file_values.get("openalex", "")
        pubmed = pubmed or file_values.get("pubmed", "")
        semantic_scholar = semantic_scholar or file_values.get("semantic_scholar", "")

    if not args.non_interactive:
        print("literature-mcp — API kimlik bilgileri")
        print(f"Yapılandırma: {path}")
        print("Boş bırakılan alanlar mevcut değeri korur.\n")
        if not email:
            email = _prompt(
                "İletişim e-postası (Crossref/NCBI/OpenAlex)",
                current.get("NCBI_EMAIL") or current.get("CROSSREF_MAILTO", ""),
            )
        if not openalex:
            openalex = _prompt(
                "OpenAlex API anahtarı (isteğe bağlı)",
                current.get("OPENALEX_API_KEY", ""),
                secret=True,
            )
        if not pubmed:
            pubmed = _prompt(
                "PubMed/NCBI API anahtarı (isteğe bağlı)",
                current.get("PUBMED_API_KEY", ""),
                secret=True,
            )
        if not semantic_scholar:
            semantic_scholar = _prompt(
                "Semantic Scholar API anahtarı (isteğe bağlı)",
                current.get("SEMANTIC_SCHOLAR_API_KEY", ""),
                secret=True,
            )

    if email and not _valid_email(email):
        print(f"Hata: geçerli bir e-posta girin: {email!r}", file=sys.stderr)
        return 2

    config = _load_config(path) if path.is_file() else {}
    server = _server_entry(config, create=args.create)
    environment = server["environment"]

    if email:
        environment["CROSSREF_MAILTO"] = email
        environment["NCBI_EMAIL"] = email
    environment.setdefault("NCBI_TOOL", DEFAULT_TOOL)
    if openalex:
        environment["OPENALEX_API_KEY"] = openalex
    if pubmed:
        environment["PUBMED_API_KEY"] = pubmed
    if semantic_scholar:
        environment["SEMANTIC_SCHOLAR_API_KEY"] = semantic_scholar

    backup = _backup(path)
    _write_atomic(path, config)
    if backup:
        print(f"Yedek: {backup}")

    _print_summary(path, {str(k): str(v) for k, v in environment.items()})
    print("\nYazıldı. MCP sunucusunu yeniden başlatınca bilgiler etkinleşir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
