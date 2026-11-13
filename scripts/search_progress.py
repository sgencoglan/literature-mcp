"""Akış HTML'leri için ortak, salt okunur arama durum paneli."""

from __future__ import annotations

import html
import re
from typing import Any

LABELS = {
    "not_reported": "Durum bildirilmedi",
    "ok": "Sorgu başarılı",
    "partial": "Kısmi",
    "error": "Hata",
    "rate_limited": "Hız sınırı — bekliyor",
    "not_run": "Henüz aranmadı",
    "not_searched": "Henüz aranmadı",
    "unavailable": "Erişilemiyor",
}


def _safe(value: Any) -> str:
    text = str(value if value is not None else "—")
    text = re.sub(
        r"(?i)((?:api_key|apikey|access_token|token)\s*[=:]\s*)[^&\s\"<>]+", r"\1[redacted]", text
    )
    return html.escape(text, quote=True)


def progress_rows(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for report in reports:
        kind, payload = report.get("kind"), report.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Tarama raporu payload nesnesi içermeli")
        if kind == "coverage":
            coverage = payload.get("coverage", payload)
            if not isinstance(coverage.get("per_source"), dict):
                raise ValueError("coverage.per_source gerekli")
            for source, stats in coverage["per_source"].items():
                if not isinstance(stats, dict):
                    raise ValueError("Kaynak durumu nesne olmalı")
                rows.append(
                    {
                        "source": source,
                        "status": stats.get("status") or "not_reported",
                        "returned": stats.get("returned"),
                        "unique": stats.get("unique_dois"),
                        "new": stats.get("new_candidates"),
                        "selected": stats.get("selected"),
                        "duration_ms": stats.get("duration_ms"),
                        "searched_at": stats.get("searched_at") or ("Rapor: " + str(coverage["timestamp"]) if coverage.get("timestamp") else None),
                        "retry_at": stats.get("retry_at"),
                        "retry_seconds": stats.get("retry_after_seconds"),
                        "error": stats.get("error"),
                        "note": stats.get("note"),
                        "query": payload.get("query") or coverage.get("query"),
                    }
                )
            for skipped in coverage.get("skipped_sources", []):
                rows.append(
                    {
                        "source": skipped.get("source"),
                        "status": "not_run",
                        "note": skipped.get("reason"),
                    }
                )
        elif kind == "platform_results":
            if payload.get("schema") != "platform-search-results/1":
                raise ValueError("platform-search-results/1 gerekli")
            for task in payload.get("coverage", []):
                runs = task.get("runs") or []
                rows.append(
                    {
                        "source": task.get("platform") or "Genel web",
                        "status": task.get("status", "not_run"),
                        "returned": sum(r.get("result_count", 0) for r in runs) if runs else None,
                        "unique": None,
                        "searched_at": runs[-1].get("searched_at") if runs else None,
                        "query": task.get("query"),
                        "note": "; ".join(str(r.get("note") or "") for r in runs),
                        "error": "; ".join(
                            str(r.get("note") or r["status"])
                            for r in runs
                            if r["status"] not in {"ok", "partial"}
                        ),
                        "retry_at": (payload.get("resume", {}).get("provider_retry_at") or {}).get(
                            task.get("rate_limit_group", "host_web_search")
                        ),
                        "engines": ", ".join(dict.fromkeys(str(r.get("engine")) for r in runs)),
                    }
                )
        else:
            raise ValueError("Tarama raporu türü coverage veya platform_results olmalı")
    return rows


def render_search_progress(data: dict[str, Any]) -> str:
    reading_html = ""
    if data.get("fulltext_reading"):
        try:
            from fulltext_reading import render_reading
        except ImportError:
            from scripts.fulltext_reading import render_reading
        manifest = data["fulltext_reading"]
        gate = manifest.get("reading_gate") or {
            "complete": False,
            "issues": ["Okuma kapısı raporlanmadı."],
            "reviewed_pages": 0,
            "total_pages": 0,
        }
        reading_html = (
            "<details><summary>Tam metin okuma raporu (kayıt anındaki durum)</summary><p>Güncel PDF kümesi geçiş kontrolünde yeniden doğrulanır.</p>"
            + render_reading(manifest, gate, manifest.get("reading_advice"))
            + "</details>"
        )
    reports = data.get("search_reports") or []
    if not reports and isinstance(data.get("coverage"), dict):
        reports = [{"kind": "coverage", "payload": data}]
    rows = progress_rows(reports)
    if not reports and data.get("database_searches"):
        rows = [
            {
                "source": r.get("database_label") or r.get("database"),
                "status": r.get("status", "not_run"),
                "returned": r.get("result_count"),
                "query": r.get("query"),
                "note": r.get("note"),
                "searched_at": r.get("searched_at"),
                "retry_at": r.get("retry_at"),
                "retry_seconds": r.get("retry_after_seconds"),
                "error": r.get("error"),
            }
            for r in data["database_searches"]
        ]
    if not rows:
        return (
            '<section class="search-progress"><h2>Tarama durumu</h2><p>Bu HTML’e ayrıntılı tarama günlüğü eklenmedi. Kaynakların tarandığı veya tamamlandığı varsayılmaz.</p></section>'
            + reading_html
        )
    body = []
    for row in rows:
        status = row["status"]
        if status == "rate_limited" or row.get("retry_at"):
            action = (
                "Bildirilen zamana kadar bekle; bağımsız sağlayıcıda ilerle; sonra yeniden dene."
            )
        elif status in {"error", "unavailable"}:
            action = "Erişimi ve hata nedenini kontrol et; kapsam boşluğunu koru."
        elif status in {"not_run", "not_searched"}:
            action = "Aramayı çalıştır ve sonucu kaydet."
        elif status == "not_reported":
            action = "Arama durumunu ve hata günlüğünü tamamla."
        elif status == "partial":
            action = "Başarısız sorguları tamamla; bulunan kayıtları koru."
        elif row.get("returned") == 0:
            action = "Sorgu varyantlarını ve eş anlamlıları genişlet."
        else:
            action = "Konu uygunluğunu ve bilinen kaynakların bulunmasını kontrol et."
        counts = [
            row.get(k) if status not in {"not_run", "not_searched"} else None
            for k in ("returned", "unique", "new", "selected")
        ]
        details = f"<details><summary>Sorgu / hata / sonraki işlem</summary><p><code>{_safe(row.get('query'))}</code></p><p>Servis: {_safe(row.get('engines'))}</p><p>Hata: {_safe(row.get('error'))}</p><p>Not: {_safe(row.get('note'))}</p><p>{_safe(action)}</p></details>"
        wait = row.get("retry_at") or (
            str(row["retry_seconds"]) + " saniye" if row.get("retry_seconds") is not None else None
        )
        body.append(
            "<tr>"
            + "".join(
                f"<td>{_safe(v)}</td>"
                for v in [
                    row["source"],
                    LABELS.get(status, status),
                    *counts,
                    row.get("duration_ms"),
                    row.get("searched_at"),
                    wait,
                ]
            )
            + f"<td>{details}</td></tr>"
        )
    headers = [
        "Kaynak",
        "Durum",
        "Dönen kayıt",
        "Tekil DOI",
        "Yeni aday",
        "Listede",
        "Süre (ms)",
        "Son deneme",
        "Yeniden deneme",
        "Ayrıntı",
    ]
    return (
        '<section class="search-progress"><h2>Tarama durumu ve kalan işler</h2><p>—: veri bildirilmedi. Dönen kayıt sayıları tekrar içerebilir. Sorgu başarısı, veritabanının eksiksiz tarandığı anlamına gelmez.</p><div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse"><thead><tr>'
        + "".join(f"<th>{h}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></section>"
        + reading_html
    )
