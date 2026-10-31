#!/usr/bin/env python3
"""Fulltext indirme listesini tek dosyalık HTML'e çevirir.

Girdi: schemas/fulltext-list.schema.json biçiminde JSON.
Çıktı: yazdırılabilir, çevrimdışı, tıklanabilir DOI/yayıncı linkleri içeren HTML.

Standart kütüphane dışında bağımlılık yoktur.

Kullanım:
    python3 scripts/build_fulltext_list.py \
        <project-root>/01_kaynak_kesfi/01_fulltext_listesi.json \
        -o <project-root>/01_kaynak_kesfi/01_fulltext_listesi.html
    python3 scripts/build_fulltext_list.py adaylar.json --check
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

PRIORITY_ORDER = ["A", "B", "C"]
PRIORITY_LABEL = {
    "A": "A · Öncelikli",
    "B": "B · Güçlü ikinci",
    "C": "C · Yedek / bağlam",
}
PUBLISHERS = [
    "Ovid LWW",
    "ScienceDirect",
    "SpringerLink",
    "Wiley",
    "Taylor & Francis",
    "Diğer",
]
LINK_KEYS = ["ovid_lww", "sciencedirect", "springerlink", "wiley", "taylor_francis"]
QUARTILES = {"Q1", "Q2", "Q3", "Q4", "-", None}
DOI_RE = re.compile(r"^10\.\S+$")


class ValidationError(Exception):
    """Girdi doğrulama hatası."""


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def doi_href(doi: str) -> str:
    return "https://doi.org/" + quote(doi, safe="/")


def safe_http_url(url: Any) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(str(url))
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return str(url)
    return None


def require(data: Dict[str, Any], key: str, path: str, errors: List[str]) -> Any:
    if key not in data:
        errors.append(f"{path}: '{key}' alanı zorunlu.")
        return None
    return data[key]


def validate(data: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(data, dict):
        return ["Kök nesne bir JSON nesnesi olmalı."]

    for key in ("project", "title", "query"):
        value = require(data, key, "kök", errors)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(f"kök: '{key}' boş olmayan bir metin olmalı.")

    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        errors.append("kök: 'candidates' boş olmayan bir liste olmalı.")
        return errors

    for index, item in enumerate(candidates, start=1):
        path = f"candidates[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: nesne olmalı.")
            continue
        for key in ("doi", "title", "authors", "year", "journal", "publisher", "priority", "rationale"):
            value = require(item, key, path, errors)
            if value is None:
                continue
            if key == "year":
                if not isinstance(value, int) or isinstance(value, bool):
                    errors.append(f"{path}.year: tam sayı olmalı.")
            elif key in ("title", "authors", "journal", "rationale") and (not isinstance(value, str) or not value.strip()):
                errors.append(f"{path}.{key}: boş olmayan metin olmalı.")
            elif key == "doi":
                if not isinstance(value, str) or not DOI_RE.match(value):
                    errors.append(f"{path}.doi: '10.' ile başlayan geçerli DOI olmalı.")
            elif key == "publisher" and value not in PUBLISHERS:
                errors.append(f"{path}.publisher: {value!r} desteklenmiyor. Seçenekler: {PUBLISHERS}")
            elif key == "priority" and value not in PRIORITY_ORDER:
                errors.append(f"{path}.priority: A/B/C olmalı.")

        quartile = item.get("quartile")
        if quartile not in QUARTILES:
            errors.append(f"{path}.quartile: Q1–Q4 veya '-' olmalı.")

        citations = item.get("citations")
        if citations is not None and (not isinstance(citations, int) or isinstance(citations, bool)):
            errors.append(f"{path}.citations: tam sayı veya null olmalı.")

        open_access = item.get("open_access")
        if open_access is not None and not isinstance(open_access, bool):
            errors.append(f"{path}.open_access: true/false olmalı.")

        for key in ("publisher_url", "oa_pdf_url"):
            value = item.get(key)
            if value is not None and not isinstance(value, str):
                errors.append(f"{path}.{key}: metin veya null olmalı.")

        for key in ("publisher_url", "oa_pdf_url"):
            url = item.get(key)
            if url and not safe_http_url(url):
                errors.append(f"{path}.{key}: yalnızca http(s) adresi olmalı.")

    return errors


def derive_publisher_url(item: Dict[str, Any]) -> Optional[str]:
    url = safe_http_url(item.get("publisher_url"))
    if url:
        return url
    links = item.get("links") or {}
    if isinstance(links, dict):
        for key in LINK_KEYS:
            url = safe_http_url(links.get(key))
            if url:
                return url
    return safe_http_url(item.get("preferred_url"))


def render_rows(candidates: List[Dict[str, Any]]) -> str:
    rows: List[str] = []
    for index, item in enumerate(candidates, start=1):
        doi = str(item["doi"])
        title = str(item["title"])
        authors = str(item["authors"])
        year = item["year"]
        journal = str(item["journal"])
        publisher = str(item["publisher"])
        priority = str(item["priority"])
        rationale = str(item["rationale"])
        quartile = item.get("quartile") or "-"
        citations = item.get("citations")
        open_access = bool(item.get("open_access"))
        access = item.get("access") or ("Açık erişim" if open_access else "Kurum erişimi")

        publisher_url = derive_publisher_url(item)
        oa_pdf_url = safe_http_url(item.get("oa_pdf_url"))
        doi_url = doi_href(doi)

        q_class = str(quartile).lower() if quartile in {"Q1", "Q2", "Q3", "Q4"} else "q-none"
        citations_text = "—" if citations is None else f"{citations:,}".replace(",", ".")
        oa_badge = '<span class="badge oa">OA</span>' if open_access else '<span class="badge closed">Kapalı</span>'

        links = [f'<a class="btn doi" href="{esc(doi_url)}" target="_blank" rel="noopener">DOI</a>']
        if publisher_url:
            links.append(
                f'<a class="btn pub" href="{esc(publisher_url)}" target="_blank" rel="noopener">'
                f'{esc(publisher)}</a>'
            )
        if oa_pdf_url:
            links.append(
                f'<a class="btn oa" href="{esc(oa_pdf_url)}" target="_blank" rel="noopener">OA PDF</a>'
            )

        rows.append(
            f"""
      <tr>
        <td class="check">
          <input type="checkbox" class="dl" data-doi="{esc(doi)}" aria-label="{esc(title)} — indirildi">
        </td>
        <td class="num">{index}</td>
        <td class="prio"><span class="badge prio-{esc(priority.lower())}">{esc(PRIORITY_LABEL.get(priority, priority))}</span></td>
        <td class="src">
          <div class="authors">{esc(authors)} ({esc(year)})</div>
          <div class="title">{esc(title)}</div>
          <div class="rationale">{esc(rationale)}</div>
        </td>
        <td class="journal">
          <div>{esc(journal)}</div>
          <div><span class="badge {q_class}">{esc(quartile)}</span></div>
        </td>
        <td class="cites">{esc(citations_text)}</td>
        <td class="access">
          <div>{oa_badge}</div>
          <div class="muted">{esc(access)}</div>
        </td>
        <td class="links">{' '.join(links)}</td>
      </tr>"""
        )
    return "\n".join(rows)


HTML_TEMPLATE = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — Fulltext listesi</title>
<style>
:root {
  --bg: #f4f6f8;
  --card: #ffffff;
  --ink: #16212b;
  --muted: #5b6b7b;
  --line: #dbe2e9;
  --accent: #0b5cad;
  --accent-soft: #e7f0fa;
  --red: #b3261e;
  --green: #1e7d4f;
  --amber: #9a6400;
  --gray: #5f6b76;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.5;
}
a { color: var(--accent); }
.hero {
  background: #0b2540;
  color: #fff;
  padding: 30px 22px 26px;
}
.hero .eyebrow {
  text-transform: uppercase;
  letter-spacing: .08em;
  font-size: 12px;
  opacity: .8;
}
.hero h1 { margin: 8px 0 6px; font-size: 26px; line-height: 1.25; }
.hero p { margin: 0; max-width: 900px; opacity: .92; }
.hero .meta { margin-top: 14px; font-size: 13px; opacity: .85; }
main { max-width: 1400px; margin: 0 auto; padding: 20px 22px 40px; }
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 12px;
  margin: 18px 0;
}
.stat {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 14px;
}
.stat .num { font-size: 24px; font-weight: 700; }
.stat small { color: var(--muted); display: block; }
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 14px;
}
.toolbar .search { display: flex; gap: 8px; align-items: center; }
.toolbar input[type="search"] {
  min-width: 260px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font: inherit;
}
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
button {
  font: inherit;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
}
button:hover { border-color: var(--accent); color: var(--accent); }
.table-wrap {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow-x: auto;
}
table { width: 100%; border-collapse: collapse; min-width: 1080px; }
thead th {
  text-align: left;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: var(--muted);
  background: #f8fafc;
  border-bottom: 1px solid var(--line);
  padding: 10px 10px;
  white-space: nowrap;
}
tbody td { border-bottom: 1px solid var(--line); padding: 12px 10px; vertical-align: top; }
tbody tr:hover { background: #fcfdff; }
td.check { width: 42px; text-align: center; }
td.check input { width: 18px; height: 18px; }
td.num { width: 34px; color: var(--muted); }
td.prio { width: 120px; }
td.src { min-width: 340px; }
td.journal { min-width: 170px; }
td.cites { width: 70px; text-align: right; white-space: nowrap; }
td.access { min-width: 120px; }
td.links { min-width: 190px; white-space: nowrap; }
.authors { font-size: 12.5px; color: var(--muted); }
.title { font-weight: 600; margin: 2px 0 5px; }
.rationale { font-size: 12.5px; color: var(--muted); }
.muted { color: var(--muted); font-size: 12.5px; }
.badge {
  display: inline-block;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 11.5px;
  font-weight: 700;
  line-height: 1.6;
  white-space: nowrap;
}
.prio-a { background: #fde8e6; color: #9b1c13; }
.prio-b { background: #fff4d6; color: #7a5200; }
.prio-c { background: #edf1f5; color: var(--gray); }
.oa { background: #e2f4ea; color: var(--green); }
.closed { background: #f0f2f4; color: var(--gray); }
.q1 { background: #e2f4ea; color: var(--green); }
.q2 { background: #e7f0fa; color: var(--accent); }
.q3 { background: #fff4d6; color: var(--amber); }
.q4, .q-none { background: #f0f2f4; color: var(--gray); }
.btn {
  display: inline-block;
  text-decoration: none;
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 5px 9px;
  font-size: 12.5px;
  font-weight: 600;
  margin-right: 4px;
}
.btn.doi { border-color: #b9d3ee; background: var(--accent-soft); }
.btn.pub { background: #fff; }
.btn.oa { border-color: #bfe3cd; background: #eefaf2; color: var(--green); }
.notes {
  margin: 14px 0 0;
  background: #fffdf3;
  border: 1px solid #f0e2b6;
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 13.5px;
}
.empty { text-align: center; color: var(--muted); padding: 26px; }
footer {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 22px 36px;
  color: var(--muted);
  font-size: 12.5px;
}
@media print {
  body { background: #fff; font-size: 10pt; }
  .hero { background: #fff; color: #000; border-bottom: 2px solid #000; padding: 0 0 12px; }
  .toolbar, .no-print { display: none !important; }
  .stats { grid-template-columns: repeat(3, 1fr); gap: 6px; }
  .stat, .table-wrap { border: 1px solid #666; box-shadow: none; }
  thead th { background: #eee; color: #000; }
  table { min-width: 0; }
  tbody td { padding: 6px 5px; }
  tr { break-inside: avoid; }
  .btn { border: 0; padding: 0; margin: 0 6px 0 0; background: none !important; color: #000; text-decoration: underline; }
  a { color: #000; }
  footer { padding-bottom: 0; }
}
</style>
</head>
<body>
<header class="hero">
  <div class="eyebrow">Fulltext indirme listesi</div>
  <h1>__TITLE__</h1>
  <p>__QUERY__</p>
  <div class="meta">Proje: <strong>__PROJECT__</strong> &middot; Oluşturma: __GENERATED__ &middot; Hedef: __TARGET__ kaynak</div>
</header>
<main>
  <section class="stats" aria-label="Özet">
    <div class="stat"><span class="num">__TOTAL__</span><small>Toplam kaynak</small></div>
    <div class="stat"><span class="num">__OA_COUNT__</span><small>Açık erişim</small></div>
    <div class="stat"><span class="num">__Q1_COUNT__</span><small>Q1 dergi</small></div>
    <div class="stat"><span class="num" id="stat-done">0</span><small>İndirildi</small></div>
    <div class="stat"><span class="num" id="stat-left">__TOTAL__</span><small>Kalan</small></div>
  </section>
  <section class="toolbar no-print">
    <label class="search">Ara
      <input type="search" id="filter" placeholder="Başlık, yazar, dergi, DOI…" autocomplete="off">
    </label>
    <div class="actions">
      <button type="button" id="print">Yazdır / PDF</button>
      <button type="button" id="clear">İşaretleri temizle</button>
    </div>
  </section>
  <div class="table-wrap">
    <table id="sources">
      <thead>
        <tr>
          <th scope="col">İndirildi</th>
          <th scope="col">#</th>
          <th scope="col">Öncelik</th>
          <th scope="col">Kaynak</th>
          <th scope="col">Dergi / Q</th>
          <th scope="col">Atıf</th>
          <th scope="col">Erişim</th>
          <th scope="col">Linkler</th>
        </tr>
      </thead>
      <tbody>
__ROWS__
      </tbody>
    </table>
  </div>
  <p class="empty" id="empty" hidden>Filtreye uyan kayıt yok.</p>
__NOTES__
</main>
<footer>
  Bu liste yalnızca DOI ve yayıncı sayfası bağlantıları içerir; PDF indirmez, ödeme duvarını veya erişim kontrolünü aşmaz.
  Tam metinleri kendi kurum hesabınızdan indirip proje klasörüne koyun. "İndirildi" işaretleri bu tarayıcıda saklanır.
</footer>
<script>
const PROJECT = __PROJECT_JS__;
const STORAGE_KEY = "fulltext-downloaded:" + PROJECT;
const boxes = Array.from(document.querySelectorAll("input.dl"));
const rows = Array.from(document.querySelectorAll("#sources tbody tr"));
const filter = document.getElementById("filter");
const empty = document.getElementById("empty");
const doneEl = document.getElementById("stat-done");
const leftEl = document.getElementById("stat-left");

function readState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch (err) {
    return new Set();
  }
}

function writeState() {
  try {
    const done = boxes.filter(b => b.checked).map(b => b.dataset.doi);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(done));
  } catch (err) {
    /* localStorage kapalıysa sessizce devam et */
  }
  updateStats();
}

function updateStats() {
  const done = boxes.filter(b => b.checked).length;
  doneEl.textContent = String(done);
  leftEl.textContent = String(boxes.length - done);
}

function applyFilter() {
  const q = (filter.value || "").toLocaleLowerCase("tr");
  let visible = 0;
  rows.forEach(row => {
    const show = !q || row.textContent.toLocaleLowerCase("tr").includes(q);
    row.hidden = !show;
    if (show) visible += 1;
  });
  empty.hidden = visible !== 0;
}

boxes.forEach(box => box.addEventListener("change", writeState));
if (filter) filter.addEventListener("input", applyFilter);
document.getElementById("print").addEventListener("click", () => window.print());
document.getElementById("clear").addEventListener("click", () => {
  if (!boxes.some(b => b.checked)) return;
  if (!window.confirm("Tüm indirildi işaretleri temizlensin mi?")) return;
  boxes.forEach(box => { box.checked = false; });
  writeState();
});

const saved = readState();
boxes.forEach(box => { box.checked = saved.has(box.dataset.doi); });
updateStats();
</script>
</body>
</html>
"""


def build_html(data: Dict[str, Any]) -> str:
    candidates: List[Dict[str, Any]] = data["candidates"]
    total = len(candidates)
    oa_count = sum(1 for item in candidates if item.get("open_access"))
    q1_count = sum(1 for item in candidates if item.get("quartile") == "Q1")
    target = data.get("target_count") or total
    generated = data.get("generated_at") or datetime.now(timezone.utc).date().isoformat()

    project = str(data["project"])
    project_js = json.dumps(project, ensure_ascii=False).replace("</", "<\\/")

    notes_html = ""
    if data.get("notes"):
        notes_html = f'<p class="notes"><strong>Not:</strong> {esc(data["notes"])}</p>'

    replacements = {
        "__TITLE__": esc(data["title"]),
        "__QUERY__": esc(data["query"]),
        "__PROJECT__": esc(project),
        "__GENERATED__": esc(generated),
        "__TARGET__": esc(target),
        "__TOTAL__": str(total),
        "__OA_COUNT__": str(oa_count),
        "__Q1_COUNT__": str(q1_count),
        "__ROWS__": render_rows(candidates),
        "__NOTES__": notes_html,
        "__PROJECT_JS__": project_js,
    }
    pattern = re.compile("|".join(re.escape(key) for key in replacements))
    return pattern.sub(lambda match: replacements[match.group(0)], HTML_TEMPLATE)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fulltext indirme listesi HTML üreticisi.")
    parser.add_argument("input", type=Path, help="Girdi JSON dosyası")
    parser.add_argument("-o", "--output", type=Path, help="Çıktı HTML dosyası")
    parser.add_argument("--check", action="store_true", help="Yalnızca doğrula; HTML üretme")
    parser.add_argument("--force", action="store_true", help="Var olan çıktı dosyasının üzerine yaz")
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"Hata: girdi bulunamadı: {args.input}", file=sys.stderr)
        return 2

    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Hata: JSON çözümlenemedi: {exc}", file=sys.stderr)
        return 2

    errors = validate(data)
    if errors:
        print("Girdi doğrulama hataları:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    if args.check:
        print(f"OK: {args.input} geçerli ({len(data['candidates'])} aday).")
        return 0

    if not args.output:
        print("Hata: --check verilmediyse -o/--output zorunludur.", file=sys.stderr)
        return 2

    if args.output.exists() and not args.force:
        print(
            f"Hata: çıktı zaten var: {args.output}\n"
            f"Üzerine yazmak için --force kullanın.",
            file=sys.stderr,
        )
        return 2

    html_text = build_html(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_text, encoding="utf-8")
    print(f"Yazıldı: {args.output} ({len(html_text):,} bayt, {len(data['candidates'])} aday)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
