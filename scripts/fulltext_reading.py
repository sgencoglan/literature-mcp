#!/usr/bin/env python3
"""Her PDF sayfasını çıkar, modelin sayfa incelemelerini kaydet ve geçişi denetle."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from output_naming import add_timestamp, write_versioned_pair
except ImportError:
    from scripts.output_naming import add_timestamp, write_versioned_pair


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pdfs(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.casefold() == ".pdf")


def prepare_reading(root: Path, artifacts: Path, workflow: str) -> dict[str, Any]:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    if workflow not in {"4", "5"} or not root.is_dir():
        raise ValueError("PDF klasörü ve hedef akış 4/5 gerekli")
    documents = []
    for pdf in _pdfs(root):
        record: dict[str, Any] = {
            "filename": str(pdf.relative_to(root)),
            "pages": [],
            "status": "error",
        }
        try:
            if not pdf.resolve().is_relative_to(root.resolve()):
                raise ValueError("Proje dışına yönelen PDF bağlantısı")
            raw = pdf.read_bytes()
            doc_id = _hash(raw)
            record.update({"document_id": doc_id, "sha256": doc_id})
            folder = artifacts / doc_id
            folder.mkdir(parents=True, exist_ok=True)
            with fitz.open(stream=raw, filetype="pdf") as document:
                if document.needs_pass or not len(document):
                    raise ValueError("Şifreli veya sayfasız PDF")
                for number, page in enumerate(document, 1):
                    text = page.get_text()
                    image = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).tobytes("png")
                    text_file, image_file = (
                        folder / f"page-{number}.txt",
                        folder / f"page-{number}.png",
                    )
                    for path, content in ((text_file, text.encode("utf-8")), (image_file, image)):
                        if not path.exists():
                            path.write_bytes(content)
                        elif path.read_bytes() != content:
                            raise ValueError("Mevcut sayfa çıktısı içerikle uyuşmuyor")
                    record["pages"].append(
                        {
                            "page": number,
                            "text_sha256": _hash(text.encode("utf-8")),
                            "image_sha256": _hash(image),
                            "text_file": str(text_file.relative_to(artifacts)),
                            "image_file": str(image_file.relative_to(artifacts)),
                            "text_characters": len(text.strip()),
                            "requires_visual": not text.strip()
                            or bool(page.get_images())
                            or bool(page.get_drawings()),
                            "review": None,
                        }
                    )
                record["page_count"] = len(document)
                record["title_metadata"] = (document.metadata or {}).get("title") or ""
                record["status"] = "extracted"
        except Exception as exc:  # noqa: BLE001 - her dosyanın hatası raporda kalır
            record["error_type"] = type(exc).__name__
        documents.append(record)
    return {
        "schema": "fulltext-reading/1",
        "workflow": workflow,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "documents": documents,
        "semantic_review": "model_declared_page_review",
        "artifact_directory": artifacts.name,
    }


def apply_reviews(manifest: dict[str, Any], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    result = json.loads(json.dumps(manifest))
    pages: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for document in result["documents"]:
        for page in document["pages"]:
            pages.setdefault((document.get("document_id"), page["page"]), []).append(page)
    for review in reviews:
        key = (review.get("document_id"), review.get("page"))
        if key not in pages:
            raise ValueError("İnceleme sayfası bulunamadı")
        page = pages[key][0]
        mode = review.get("mode")
        if mode not in {"text", "visual", "text_and_visual"}:
            raise ValueError("İnceleme modu gerekli")
        if not str(review.get("summary") or "").strip():
            raise ValueError("Her sayfa için içerik inceleme notu gerekli")
        if page["requires_visual"] and mode == "text":
            raise ValueError("Metinsiz veya görsel içeren sayfa görsel incelenmeli")
        for field, required in (
            ("text_sha256", mode != "visual"),
            ("image_sha256", mode != "text"),
        ):
            if required and review.get(field) != page[field]:
                raise ValueError("İnceleme güncel sayfa çıktısıyla eşleşmiyor")
        reviewed = {
            "mode": mode,
            "summary": str(review["summary"]),
            "text_sha256": review.get("text_sha256"),
            "image_sha256": review.get("image_sha256"),
            "terms": [str(t) for t in review.get("terms", [])],
            "sections": [str(s) for s in review.get("sections", [])],
            "limitations": str(review.get("limitations") or ""),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        for matching_page in pages[key]:
            matching_page["review"] = dict(reviewed)
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def reading_gate(
    manifest: dict[str, Any] | None, root: Path | None = None, workflow: str | None = None
) -> dict[str, Any]:
    issues = []
    reviewed = total = 0
    if not manifest or manifest.get("schema") != "fulltext-reading/1":
        return {
            "complete": False,
            "issues": ["Tam metin okuma raporu eklenmedi."],
            "reviewed_pages": 0,
            "total_pages": 0,
        }
    if workflow and manifest.get("workflow") != workflow:
        issues.append("Okuma raporu hedef akış için hazırlanmadı.")
    documents = manifest.get("documents") or []
    if not documents:
        issues.append("Okunacak PDF bulunamadı.")
    actual = {str(p.relative_to(root)): p for p in _pdfs(root)} if root and root.is_dir() else None
    if root is not None and actual is None:
        issues.append("PDF klasörüne erişilemiyor.")
    if root is None:
        issues.append("Güncel PDF kümesi doğrulanmadı; --fulltext-dir gerekli.")
    if actual is not None:
        expected = {d["filename"] for d in documents}
        if set(actual) != expected:
            issues.append("PDF kümesi değişti; eklenen/silinen dosyalar için okuma yenilenmeli.")
    for document in documents:
        name = document["filename"]
        if document.get("status") != "extracted" or len(document["pages"]) != document.get(
            "page_count"
        ):
            issues.append(f"{name}: bütün sayfalar çıkarılamadı.")
        if actual is not None and name in actual:
            path = actual[name]
            if not path.resolve().is_relative_to(root.resolve()) or _hash(
                path.read_bytes()
            ) != document.get("sha256"):
                issues.append(f"{name}: dosya değişti veya proje dışına yöneliyor.")
        for page in document["pages"]:
            total += 1
            review = page.get("review")
            mode = (review or {}).get("mode")
            valid_hashes = (
                bool(review)
                and (mode == "visual" or review.get("text_sha256") == page["text_sha256"])
                and (mode == "text" or review.get("image_sha256") == page["image_sha256"])
            )
            if (
                review
                and mode in {"text", "visual", "text_and_visual"}
                and valid_hashes
                and review.get("summary")
                and (not page["requires_visual"] or mode in {"visual", "text_and_visual"})
            ):
                reviewed += 1
            else:
                issues.append(f"{name} · sayfa {page['page']}: model incelemesi eksik.")
    return {
        "complete": not issues and total > 0,
        "issues": issues,
        "reviewed_pages": reviewed,
        "total_pages": total,
        "verification": "Belge kümesi sağlandıysa SHA-256 kontrol edilir; anlamsal okuma modelin sayfa bazlı beyanıdır.",
    }


def reading_advice(manifest: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    planned_terms = {
        str(t).casefold() for s in plan.get("sections", []) for t in s.get("search_terms", [])
    }
    terms: dict[str, list[dict[str, Any]]] = {}
    section_docs: dict[str, set[str]] = {}
    for doc in manifest.get("documents", []):
        for page in doc.get("pages", []):
            review = page.get("review") or {}
            for term in review.get("terms", []):
                if term.strip() and term.casefold() not in planned_terms:
                    terms.setdefault(term, []).append(
                        {
                            "document_id": doc.get("document_id"),
                            "filename": doc["filename"],
                            "page": page["page"],
                        }
                    )
            for section in review.get("sections", []):
                section_docs.setdefault(section, set()).add(doc.get("document_id"))
    needs = []
    for section in plan.get("sections", []):
        minimum = sum(int(n.get("min_count") or 0) for n in section.get("evidence_needs", []))
        observed = len(section_docs.get(section["id"], set()))
        if observed < max(1, minimum):
            needs.append(
                {
                    "section_id": section["id"],
                    "heading": section.get("heading"),
                    "reviewed_relevant_documents": observed,
                    "requested_minimum": max(1, minimum),
                    "search_terms": section.get("search_terms") or [],
                    "note": "Yeni makale ihtiyacı adayı; modelin ilişkilendirdiği belge sayısı kanıt yeterliliğini göstermez.",
                }
            )
    return {
        "new_term_candidates": [
            {"term": term, "status": "model_proposed", "source_pages": sources}
            for term, sources in terms.items()
        ],
        "new_article_needs": needs,
        "actual_new_publications": [],
        "note": "Yeni yayın başlıkları ancak gerçek aramadan sonra eklenir; kavram ve ihtiyaç önerileri onay bekler.",
    }


def render_reading(
    manifest: dict[str, Any], gate: dict[str, Any], advice: dict[str, Any] | None = None
) -> str:
    esc = lambda v: html.escape(str(v), quote=True)
    document_rows = "".join(
        f"<tr><td>{esc(d['filename'])}</td><td>{esc(d.get('title_metadata') or 'PDF metadata başlığı yok')}</td><td>{esc(d['status'])}</td><td>{d.get('page_count', '—')}</td><td>{sum(bool(p.get('review')) for p in d['pages'])}</td><td>{esc(d.get('error_type') or '—')}</td></tr>"
        for d in manifest.get("documents", [])
    )
    rows = "".join(
        f"<tr><td>{esc(d['filename'])}</td><td>{p['page']}</td><td>{p['text_characters']}</td><td>{'Görsel gerekli' if p['requires_visual'] else 'Metin'}</td><td>{esc((p.get('review') or {}).get('summary') or 'İncelenmedi')}</td></tr>"
        for d in manifest.get("documents", [])
        for p in d["pages"]
    )
    issues = "".join(f"<li>{esc(i)}</li>" for i in gate["issues"])
    extra = ""
    if advice:
        extra = (
            "<h3>Yeni terim adayları</h3><ul>"
            + "".join(
                f"<li>{esc(t['term'])} · öneri · {len(t['source_pages'])} sayfa izi<details><summary>Kaynak sayfalar</summary>{esc('; '.join(str(s['filename']) + ' · s.' + str(s['page']) for s in t['source_pages']))}</details></li>"
                for t in advice["new_term_candidates"]
            )
            + "</ul><h3>Ek kaynak ihtiyacı</h3><ul>"
            + "".join(
                f"<li>{esc(n['section_id'])}: {esc(n['heading'])} · incelenen ilgili belge {n['reviewed_relevant_documents']} / istenen {n['requested_minimum']} · terimler: {esc(', '.join(n['search_terms']))}</li>"
                for n in advice["new_article_needs"]
            )
            + "</ul>"
        )
    return f"<section><h2>Tam metin okuma kontrolü — akış {esc(manifest.get('workflow'))}</h2><p>İncelenen sayfa: {gate['reviewed_pages']}/{gate['total_pages']} · Geçiş: {'okuma tamamlandı' if gate['complete'] else 'engelli'}</p><p>Metin çıkarma, modelin anlamsal okuması sayılmaz. Sayfa notları modelin inceleme beyanlarıdır; iddia doğrulaması ayrıca yapılır.</p><ul>{issues}</ul><h3>Yüklenen fulltext bilgileri</h3><div style='overflow:auto'><table><thead><tr><th>Dosya</th><th>PDF metadata başlığı</th><th>Durum</th><th>Sayfa</th><th>İnceleme kaydı</th><th>Hata</th></tr></thead><tbody>{document_rows}</tbody></table></div><h3>Sayfa incelemeleri</h3><div style='overflow:auto'><table><thead><tr><th>Belge</th><th>Sayfa</th><th>Metin karakteri</th><th>İnceleme türü</th><th>Model notu</th></tr></thead><tbody>{rows}</tbody></table></div>{extra}</section>"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "review", "check"])
    parser.add_argument("--fulltext-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--workflow", choices=["4", "5"])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args(argv)
    if args.action == "prepare":
        if not args.fulltext_dir or not args.output_dir or not args.workflow:
            parser.error("prepare için --fulltext-dir, --output-dir ve --workflow gerekli")
        manifest = prepare_reading(args.fulltext_dir, args.output_dir / "pages", args.workflow)
    else:
        if not args.manifest:
            parser.error("--manifest gerekli")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.action == "review":
            if not args.reviews:
                parser.error("--reviews gerekli")
            manifest = apply_reviews(manifest, json.loads(args.reviews.read_text(encoding="utf-8")))
    gate = reading_gate(manifest, args.fulltext_dir, args.workflow)
    if args.action == "check":
        if not args.fulltext_dir or not args.workflow:
            parser.error("check için --fulltext-dir ve --workflow gerekli")
        print(json.dumps(gate, ensure_ascii=False, indent=2))
        return 0 if gate["complete"] else 1
    advice = (
        reading_advice(manifest, json.loads(args.plan.read_text(encoding="utf-8")))
        if args.plan
        else None
    )
    directory = args.output_dir or args.manifest.parent
    target = add_timestamp(directory / "03_fulltext_okuma.json")
    manifest["reading_gate"] = gate
    if advice:
        manifest["reading_advice"] = advice
    result = write_versioned_pair(
        target,
        {
            ".json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            ".html": '<!doctype html><meta charset="utf-8"><title>Tam metin okuma</title>'
            + render_reading(manifest, gate, advice),
        },
    )
    print(f"Yazıldı: {result['path']}")
    print(f"Yazıldı: {result['path'].with_suffix('.html')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
