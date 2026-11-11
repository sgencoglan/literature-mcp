#!/usr/bin/env python3
"""Açık erişimli PDF'leri Unpaywall/OpenAlex üzerinden indirir.

Yalnızca yayıncının veya arşivin açıkça sunduğu PDF bağlantılarını dener;
ödeme duvarını, erişim kontrolünü veya kullanım koşullarını aşmaz. Doğrudan
PDF bağlantısı yoksa açılış sayfasındaki ``citation_pdf_url`` veya PDF
bağlantısı bir kez çözülür. İndirilen dosyalar varsayılan olarak iş akışı
3'ün ``03_kaynak_kesfi/fulltext/`` klasörüne yazılır; ``--workflow 4`` ve
``--workflow 5`` sırasıyla taslak ve analiz akışının ``fulltext/`` klasörünü
seçer.

Kullanım:
    python3 scripts/download_open_access.py \
        <proje-kökü>/03_kaynak_kesfi/01_fulltext_listesi.json

    python3 scripts/download_open_access.py adaylar.json \
        --output-dir <proje-kökü>/04_taslak/fulltext --dry-run

    python3 scripts/download_open_access.py adaylar.json \
        --update-json --source both
"""

from __future__ import annotations

import argparse
import html as html_lib
import ipaddress
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

try:  # paket sürümü varsa onu kullan
    from sciencedirect_meta import __version__ as _version
except ImportError:  # tek başına çalıştırma
    _version = "dev"

try:  # scripts/ içinden çalışırken
    from setup_credentials import _parse_setup_file, _resolve_setup_file
except ImportError:  # python -m scripts.download_open_access
    from scripts.setup_credentials import _parse_setup_file, _resolve_setup_file

try:  # scripts/ içinden çalışırken
    from output_naming import add_timestamp, timestamp_suffix
    from project_layout import (
        WORKFLOW_DIRECTORIES,
        fulltext_dir,
        workflow_dir,
    )
except ImportError:  # python -m scripts.download_open_access
    from scripts.output_naming import add_timestamp, timestamp_suffix
    from scripts.project_layout import (
        WORKFLOW_DIRECTORIES,
        fulltext_dir,
        workflow_dir,
    )

try:  # paket kuruluysa tek hız-limit tablosunu kullan
    from sciencedirect_meta.rate_limit import (
        interval_for as _interval_for,
    )
    from sciencedirect_meta.rate_limit import (
        retry_after_seconds as _retry_after_seconds,
    )
except ImportError:  # MCP paketi kurulu değil: aynı varsayılanlarla devam et
    def _interval_for(host: str, has_key: bool = False) -> float:
        return 0.2

    def _retry_after_seconds(header, attempt: int, host: str = "") -> float:
        value = (header or "").strip()
        if value.isdigit():
            return min(float(value), 20.0)
        return min(2.0 * (attempt + 1), 20.0)


def _host_of(url: str) -> str:
    try:
        return (urlparse(str(url)).hostname or "").lower()
    except ValueError:
        return ""


USER_AGENT = f"literature-mcp/{_version} (open-access downloader)"
UNPAYWALL_API = "https://api.unpaywall.org/v2/{doi}"
OPENALEX_API = "https://api.openalex.org/works/https://doi.org/{doi}"
MAX_JSON_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_MB = 80.0
# Unpaywall/OpenAlex paylaşılan tabloda ~5 istek/sn; varsayılan aralık oradan.
DEFAULT_SLEEP = max(
    _interval_for("api.unpaywall.org"), _interval_for("api.openalex.org")
)


class FetchError(Exception):
    """Ağ veya API hatası."""


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    visible = local[:1] if local else ""
    return f"{visible}***@{domain}"


def _safe_url(value: Any) -> Optional[str]:
    """Return a public http(s) URL, or None for unsafe/invalid values."""
    if not value:
        return None
    text = str(value).strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "localhost.localdomain"}:
        return None
    if host.endswith(".local") or host.endswith(".internal"):
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return text
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    ):
        return None
    return text


def _ascii_url(url: str) -> str:
    """Percent-encode non-ASCII characters so urllib/http.client can send it.

    Turkish characters in DOIs, titles or repository paths (e.g. DergiPark
    links) otherwise raise ``UnicodeEncodeError: 'ascii' codec`` inside
    http.client. Already-encoded URLs are left untouched.
    """
    parsed = urlparse(str(url))
    if not parsed.scheme:
        return str(url)
    netloc = parsed.netloc
    try:  # IDN alan adı: ASCII olmayan host'u punycode'a çevir
        netloc = netloc.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeEncodeError):
        pass
    safe_path = quote(parsed.path or "/", safe="/%:@&=+$,;~()!*'")
    safe_query = quote(parsed.query or "", safe="=&%:@+,;~()!*'/")
    safe_fragment = quote(parsed.fragment or "", safe="=&%:@+,;~()!*'/")
    return parsed._replace(
        netloc=netloc,
        path=safe_path,
        query=safe_query,
        fragment=safe_fragment,
    ).geturl()


def _fetch_json(url: str, timeout: float, retries: int = 3) -> Optional[Dict[str, Any]]:
    url = _ascii_url(url)
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(MAX_JSON_BYTES)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            return data if isinstance(data, dict) else None
        except HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries - 1:
                # 429 iste Retry-After'ı onurlandır; tabloda olmayan bir
                # bekleme süresi uydurma.
                header = exc.headers.get("Retry-After") if exc.headers else None
                time.sleep(_retry_after_seconds(header, attempt, _host_of(url)))
                last_error = exc
                continue
            raise FetchError(f"HTTP {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(_retry_after_seconds(None, attempt, _host_of(url)))
                continue
    raise FetchError(str(last_error) if last_error else "bilinmeyen ağ hatası")


def _dedupe_candidates(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for item in items:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def _sort_candidates(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Prefer direct PDF links over landing pages."""
    return sorted(
        items,
        key=lambda item: 0 if item.get("kind") == "pdf" else 1,
    )


def _unpaywall_candidates(
    doi: str,
    email: str,
    timeout: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not email:
        return [], {"error": "Unpaywall için e-posta gerekli"}
    url = UNPAYWALL_API.format(doi=quote(doi, safe="/")) + "?email=" + quote(email)
    data = _fetch_json(url, timeout)
    if not data:
        return [], {"error": "Unpaywall kaydı bulunamadı"}
    locations: List[Dict[str, Any]] = []
    best = data.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    for location in data.get("oa_locations") or []:
        if isinstance(location, dict):
            locations.append(location)
    candidates: List[Dict[str, Any]] = []
    for location in locations:
        for key in ("url_for_pdf", "url"):
            url_value = _safe_url(location.get(key))
            if not url_value:
                continue
            candidates.append(
                {
                    "url": url_value,
                    "source": "Unpaywall",
                    "kind": "pdf" if key == "url_for_pdf" else "landing",
                    "license": location.get("license"),
                    "host_type": location.get("host_type"),
                    "version": location.get("version"),
                }
            )
    return _sort_candidates(_dedupe_candidates(candidates)), {
        "is_oa": bool(data.get("is_oa"))
    }


def _openalex_candidates(
    doi: str,
    email: str,
    timeout: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    url = OPENALEX_API.format(doi=quote(doi, safe="/"))
    if email:
        url += "?mailto=" + quote(email)
    data = _fetch_json(url, timeout)
    if not data:
        return [], {"error": "OpenAlex kaydı bulunamadı"}
    locations: List[Dict[str, Any]] = []
    best = data.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    for location in data.get("locations") or []:
        if isinstance(location, dict):
            locations.append(location)
    candidates: List[Dict[str, Any]] = []
    for location in locations:
        for key in ("pdf_url", "landing_page_url"):
            url_value = _safe_url(location.get(key))
            if not url_value:
                continue
            candidates.append(
                {
                    "url": url_value,
                    "source": "OpenAlex",
                    "kind": "pdf" if key == "pdf_url" else "landing",
                    "license": location.get("license"),
                    "host_type": location.get("source", {}).get("type")
                    if isinstance(location.get("source"), dict)
                    else None,
                    "version": location.get("version"),
                }
            )
    open_access = data.get("open_access") or {}
    if isinstance(open_access, dict):
        url_value = _safe_url(open_access.get("oa_url"))
        if url_value:
            candidates.append(
                {
                    "url": url_value,
                    "source": "OpenAlex",
                    "kind": "landing",
                    "license": None,
                    "host_type": None,
                    "version": None,
                }
            )
    return _sort_candidates(_dedupe_candidates(candidates)), {
        "is_oa": bool(open_access.get("is_oa"))
    }


META_RE = re.compile(r"<meta\b[^>]*>", re.I)
LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
ANCHOR_RE = re.compile(r"<a\b[^>]*>", re.I)
ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))"""
)
PDF_HREF_RE = re.compile(r"\.pdf(?:$|[?#])", re.I)


def _attrs(tag: str) -> Dict[str, str]:
    return {
        match.group(1).lower(): html_lib.unescape(
            match.group(2) or match.group(3) or match.group(4) or ""
        )
        for match in ATTR_RE.finditer(tag)
    }


def _extract_pdf_link(page_text: str, base_url: str) -> Optional[str]:
    """Find a PDF link in an open-access landing page."""
    for tag in META_RE.findall(page_text):
        attrs = _attrs(tag)
        if (
            attrs.get("name", "").lower() == "citation_pdf_url"
            and attrs.get("content")
        ):
            candidate = _safe_url(urljoin(base_url, attrs["content"]))
            if candidate:
                return candidate
    for tag in LINK_RE.findall(page_text):
        attrs = _attrs(tag)
        if (
            attrs.get("type", "").lower() == "application/pdf"
            and attrs.get("href")
        ):
            candidate = _safe_url(urljoin(base_url, attrs["href"]))
            if candidate:
                return candidate
    for tag in ANCHOR_RE.findall(page_text):
        attrs = _attrs(tag)
        href = attrs.get("href", "")
        if href and PDF_HREF_RE.search(href):
            candidate = _safe_url(urljoin(base_url, href))
            if candidate:
                return candidate
    return None


def _download_pdf(
    url: str,
    destination: Path,
    timeout: float,
    max_bytes: int,
    _depth: int = 0,
) -> None:
    url = _ascii_url(url)
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            # Bazı kurum depoları yalnızca PDF isteyen Accept başlığını
            # reddediyor (403); açılış sayfasını da kabul et.
            "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > max_bytes:
            raise FetchError(f"PDF çok büyük: {length} bayt")
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise FetchError(f"PDF boyut sınırını aşıyor ({max_bytes} bayt)")
    if not data.startswith(b"%PDF"):
        # Unpaywall bazı kayıtlarda doğrudan PDF yerine yayıncı açılış
        # sayfasını verir. Tek adımda sayfadaki PDF bağlantısını çöz.
        if _depth < 1:
            page = data[: 2 * 1024 * 1024].decode("utf-8", errors="replace")
            pdf_url = _extract_pdf_link(page, url)
            if pdf_url and pdf_url != url:
                return _download_pdf(
                    pdf_url,
                    destination,
                    timeout,
                    max_bytes,
                    _depth + 1,
                )
        raise FetchError(
            "Açık kopya PDF yerine HTML sayfası döndürdü (bot koruması veya "
            "açılış sayfası); tarayıcıdan indirip fulltext/ klasörüne koyabilirsiniz"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=destination.stem + ".",
        suffix=".part",
        dir=str(destination.parent),
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _slug(value: Any, max_length: int = 80) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")
    return (text or "kaynak")[:max_length]


def _doi_filename(doi: str) -> str:
    """DOI'yi dosya adına çevir; özel karakterleri at.

    ``10.4073/csr.2011.4`` -> ``10.4073csr.2011.4.pdf``. Eğik çizgi ve diğer
    özel karakterler kaldırılır; yalnızca harf, rakam, nokta ve tire kalır,
    böylece dosya adı DOI ile kolayca eşleştirilebilir.
    """
    text = unicodedata.normalize("NFKD", str(doi or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    # Özel karakterleri tamamen çıkar (tireye çevirme): 10.4073csr.2011.4
    text = re.sub(r"[^A-Za-z0-9.\-]+", "", text).strip(".-")
    return (text or "doi-yok")[:150]


def _filename_for(candidate: Dict[str, Any]) -> str:
    """PDF dosya adı: DOI tabanlı, özel karakterlerden arındırılmış."""
    doi = str(candidate.get("doi") or "").strip()
    if doi:
        return f"{_doi_filename(doi)}.pdf"
    authors = str(candidate.get("authors") or "")
    first_author = authors.split(";")[0].split(",")[0].strip()
    year = str(candidate.get("year") or "tarih-yok")
    return f"{_slug(first_author, 40)}_{_slug(year, 12)}.pdf"


def _resolve_email(args: argparse.Namespace, project_root: Path) -> str:
    email = (args.email or "").strip()
    if email:
        return email
    for name in ("UNPAYWALL_EMAIL", "CROSSREF_MAILTO", "NCBI_EMAIL"):
        email = (os.environ.get(name) or "").strip()
        if email:
            return email
    setup_path = _resolve_setup_file(
        args.from_file,
        args.project or str(project_root),
    )
    if setup_path:
        values = _parse_setup_file(setup_path)
        email = (values.get("email") or "").strip()
    return email


def _project_root(input_path: Path, explicit: Optional[Path]) -> Path:
    if explicit:
        return explicit.expanduser().resolve()
    for parent in [input_path.parent, *input_path.parents]:
        if parent.name in set(WORKFLOW_DIRECTORIES.values()):
            return parent.parent
    return input_path.parent


def _default_output_dir(
    input_path: Path, project_root: Path, workflow: str | None
) -> Path:
    """Hedef PDF klasörü. Varsayılan 3 (``03_kaynak_kesfi/fulltext``)."""
    if workflow:
        return fulltext_dir(project_root, workflow)
    # Akış belirtilmediyse girdinin hangi akışta olduğuna bak.
    for key in ("5", "4", "3", "2", "1"):
        try:
            input_path.resolve().relative_to(
                workflow_dir(project_root, key).resolve()
            )
            return fulltext_dir(project_root, key)
        except ValueError:
            continue
    return fulltext_dir(project_root, "3")


def _default_report_path(output_dir: Path, timestamp: str) -> Path:
    """Rapor, hedef ``fulltext/`` klasörünün bir üstünde (akış klasöründe) yazılır."""
    if output_dir.name == "fulltext":
        return output_dir.parent / f"oa_indirme_raporu_{timestamp}.json"
    return output_dir / f"oa_indirme_raporu_{timestamp}.json"


def _update_candidate(
    candidate: Dict[str, Any],
    chosen: Dict[str, Any],
    checked_at: str,
) -> None:
    candidate["open_access"] = True
    candidate["oa_pdf_url"] = chosen["url"]
    candidate["access"] = "Açık erişim"
    candidate["oa_source"] = chosen.get("source")
    candidate["oa_license"] = chosen.get("license")
    candidate["oa_host_type"] = chosen.get("host_type")
    candidate["oa_checked_at"] = checked_at
    candidate["oa_downloaded"] = False
    candidate.pop("oa_local_file", None)


def _mark_downloaded(candidate: Dict[str, Any], destination: Path) -> None:
    candidate["oa_downloaded"] = True
    candidate["oa_local_file"] = destination.name


def _mark_not_downloaded(candidate: Dict[str, Any]) -> None:
    candidate["oa_downloaded"] = False
    candidate.pop("oa_local_file", None)


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Atomik JSON yazımı; mevcut dosyanın izinlerini korur.

    ``mkstemp`` yeni dosyayı 600 ile açar. Var olan bir dosyanın üzerine
    yazarken eski izin (ör. 644) korunur, böylece raporlar yanlışlıkla
    yalnızca sahibine açık hâle gelmez.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_mode: Optional[int] = None
    try:
        previous_mode = path.stat().st_mode & 0o777
    except OSError:
        previous_mode = None
    handle, temp_name = tempfile.mkstemp(
        prefix=path.stem + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if previous_mode is not None:
            try:
                os.chmod(temp_name, previous_mode)
            except OSError:
                pass
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _find_oa_candidates(
    doi: str,
    source: str,
    email: str,
    timeout: float,
    sleep: float,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    notes: List[str] = []
    candidates: List[Dict[str, Any]] = []
    if source in {"unpaywall", "both"} and email:
        try:
            found, meta = _unpaywall_candidates(doi, email, timeout)
            candidates.extend(found)
            if meta.get("error"):
                notes.append(f"Unpaywall: {meta['error']}")
        except FetchError as exc:
            notes.append(f"Unpaywall: {exc}")
        time.sleep(max(0.0, sleep))
    if not candidates and source in {"openalex", "both"}:
        try:
            found, meta = _openalex_candidates(doi, email, timeout)
            candidates.extend(found)
            if meta.get("error"):
                notes.append(f"OpenAlex: {meta['error']}")
        except FetchError as exc:
            notes.append(f"OpenAlex: {exc}")
        time.sleep(max(0.0, sleep))
    return _sort_candidates(_dedupe_candidates(candidates)), notes


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unpaywall/OpenAlex üzerinden açık erişimli PDF'leri indirir."
    )
    parser.add_argument("input", type=Path, help="Fulltext listesi JSON dosyası")
    parser.add_argument(
        "--output-dir",
        "--pdf-dir",
        dest="output_dir",
        type=Path,
        help="PDF klasörü (varsayılan: proje köküne göre 01/02/03 fulltext).",
    )
    parser.add_argument(
        "--project",
        help="setup.txt ve çıktı kökünü belirleyen proje klasörü.",
    )
    parser.add_argument("--from-file", type=Path, help="setup.txt yolu.")
    parser.add_argument("--email", help="Unpaywall/OpenAlex için e-posta.")
    parser.add_argument(
        "--source",
        choices=["unpaywall", "openalex", "both"],
        default="both",
        help="Açık erişim kaynağı (varsayılan: both).",
    )
    parser.add_argument(
        "--workflow",
        choices=sorted(WORKFLOW_DIRECTORIES),
        help="PDF hedef akışı (varsayılan: girdi klasörüne göre; 3 = 03_kaynak_kesfi).",
    )
    parser.add_argument("--limit", type=int, help="İlk N adayı işle.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-mb", type=float, default=DEFAULT_MAX_MB)
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP)
    parser.add_argument("--overwrite", action="store_true", help="Var olan PDF'in üzerine yaz.")
    parser.add_argument("--dry-run", action="store_true", help="İndirme; yalnızca OA durumunu bildir.")
    parser.add_argument("--update-json", action="store_true", help="Girdi JSON'una OA alanlarını yaz.")
    parser.add_argument("--report", type=Path, help="İndirme raporu JSON yolu.")
    parser.add_argument(
        "--timestamp",
        dest="timestamp",
        action="store_true",
        default=True,
        help="Rapor adına tarih-saat ekle (varsayılan: açık).",
    )
    parser.add_argument(
        "--no-timestamp",
        dest="timestamp",
        action="store_false",
        help="Rapor adında tarih-saat kullanma.",
    )
    args = parser.parse_args(argv)

    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        print(f"Hata: girdi bulunamadı: {input_path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Hata: JSON çözümlenemedi: {exc}", file=sys.stderr)
        return 2
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        print("Hata: JSON içinde 'candidates' listesi yok veya boş.", file=sys.stderr)
        return 2

    project_root = _project_root(input_path, Path(args.project) if args.project else None)
    email = _resolve_email(args, project_root)
    source = args.source
    if source in {"unpaywall", "both"} and not email:
        if source == "unpaywall":
            print(
                "Hata: Unpaywall için e-posta gerekli. --email, setup.txt veya "
                "CROSSREF_MAILTO/UNPAYWALL_EMAIL kullanın.",
                file=sys.stderr,
            )
            return 2
        print(
            "Uyarı: e-posta bulunamadı; Unpaywall atlanıyor, OpenAlex kullanılacak.",
            file=sys.stderr,
        )
        source = "openalex"

    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else _default_output_dir(input_path, project_root, args.workflow)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    selected = candidates[: args.limit] if args.limit and args.limit > 0 else candidates
    checked_at = _iso_now()
    items: List[Dict[str, Any]] = []
    summary = {
        "total": len(selected),
        "downloaded": 0,
        "exists": 0,
        "available": 0,
        "no_oa": 0,
        "error": 0,
    }
    max_bytes = int(max(0.1, args.max_mb) * 1024 * 1024)

    for index, candidate in enumerate(selected, start=1):
        if not isinstance(candidate, dict):
            continue
        doi = str(candidate.get("doi") or "").strip()
        title = str(candidate.get("title") or "")
        item: Dict[str, Any] = {
            "doi": doi,
            "title": title,
            "status": "",
            "source": None,
            "kind": None,
            "url": None,
            "saved_as": None,
            "license": None,
            "host_type": None,
            "notes": [],
        }
        if not doi.startswith("10."):
            item["status"] = "error"
            item["notes"].append("Geçersiz DOI")
            _mark_not_downloaded(candidate)
            summary["error"] += 1
            items.append(item)
            continue

        destination = output_dir / _filename_for(candidate)
        if destination.exists() and not args.overwrite:
            item["status"] = "exists"
            item["saved_as"] = destination.name
            _mark_downloaded(candidate, destination)
            summary["exists"] += 1
            items.append(item)
            continue

        found, notes = _find_oa_candidates(doi, source, email, args.timeout, args.sleep)
        item["notes"].extend(notes)
        if not found:
            item["status"] = "no_oa"
            _mark_not_downloaded(candidate)
            summary["no_oa"] += 1
            items.append(item)
            continue

        if args.dry_run:
            chosen = found[0]
            item["source"] = chosen.get("source")
            item["kind"] = chosen.get("kind")
            item["url"] = chosen.get("url")
            item["license"] = chosen.get("license")
            item["host_type"] = chosen.get("host_type")
            _update_candidate(candidate, chosen, checked_at)
            item["status"] = "available"
            summary["available"] += 1
            items.append(item)
            continue

        # Yayıncı sunucuları bot korumasıyla 401/403 döndürebilir. Bu bir
        # erişim kontrolünü aşma değil; Unpaywall'un listelediği bir sonraki
        # açık kopyayı (ör. kurum deposu) denemektir.
        forbidden: List[str] = []
        downloaded = False
        for position, option in enumerate(found):
            url = option.get("url")
            if not url:
                continue
            item.update(
                {
                    "source": option.get("source"),
                    "kind": option.get("kind"),
                    "url": url,
                    "license": option.get("license"),
                    "host_type": option.get("host_type"),
                }
            )
            try:
                _download_pdf(url, destination, args.timeout, max_bytes)
                downloaded = True
                # Yalnızca gerçekten indirilen kopyayı "açık erişim" olarak
                # işaretle; denenen ama başarısız URL'ler adayı kirletmesin.
                _update_candidate(candidate, option, checked_at)
                if position:
                    item["notes"].append(
                        f"{position + 1}. açık kopya kullanıldı ({option.get('host_type') or 'bilinmiyor'})"
                    )
                break
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    forbidden.append(f"{option.get('host_type') or option.get('source') or 'host'}: HTTP {exc.code}")
                else:
                    item["notes"].append(f"{url}: HTTP {exc.code}")
                # 403/404/5xx: sıradaki açık kopyayı dene.
                continue
            except (FetchError, URLError, TimeoutError, OSError) as exc:
                item["notes"].append(f"{url}: {exc}")
                continue

        if downloaded:
            item["status"] = "downloaded"
            item["saved_as"] = destination.name
            _mark_downloaded(candidate, destination)
            summary["downloaded"] += 1
        else:
            item["status"] = "error"
            if forbidden:
                item["notes"].append(
                    "Açık kopya sağlayıcısı PDF'i bot koruması nedeniyle vermedi ("
                    + ", ".join(forbidden)
                    + "); tarayıcıdan indirip fulltext/ klasörüne koyabilirsiniz."
                )
            elif not item["notes"]:
                item["notes"].append("Açık erişim kopyası indirilemedi")
            _mark_not_downloaded(candidate)
            summary["error"] += 1
        items.append(item)
        print(
            f"[{index}/{len(selected)}] {item['status']}: {doi}"
            + (f" -> {item['saved_as']}" if item.get("saved_as") else "")
        )

    if args.update_json:
        data["candidates"] = candidates
        _write_json_atomic(input_path, data)
        print(f"JSON güncellendi: {input_path}")

    timestamp = timestamp_suffix()
    report_path = args.report or _default_report_path(output_dir, timestamp)
    report_path = add_timestamp(report_path, enabled=args.timestamp)
    report = {
        "generated_at": checked_at,
        "input": input_path.name,
        "output_dir": output_dir.name,
        "email": _mask_email(email),
        "source": source,
        "dry_run": bool(args.dry_run),
        "summary": summary,
        "items": items,
    }
    _write_json_atomic(report_path, report)

    print(
        "\nÖzet: "
        + ", ".join(f"{key}={value}" for key, value in summary.items())
    )
    print(f"Rapor: {report_path}")
    if not args.dry_run:
        print(f"PDF klasörü: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
