"""Quality gate for the golden-standard chapter report.

The gate is intentionally stricter than "the HTML renders". It checks that every
claim of correction is tied to a DOI, a page and a verbatim quotation, and that
no public deliverable leaks local paths or executable content.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
LOCAL_PATH_PATTERNS = [
    re.compile(r"file://", re.I),
    re.compile(r"/home/", re.I),
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"/Users/", re.I),
    re.compile(r"(?:^|[\s\"'(])([^\s\"')]+\.pdf)(?:$|[\s\"')])", re.I),
]
PAGE_RE = re.compile(r"(?:^|\b)(?:s\.|ss\.|s\.\s*\d|sayfa|p\.|pp\.)\s*\d", re.I)
SCRIPT_RE = re.compile(r"<script\b|<iframe\b|\son[a-z]+\s*=", re.I)
TAG_RE = re.compile(r"<(/)?([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*?(/?)>")
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
BALANCE_TAGS = {
    "html", "head", "body", "div", "section", "table", "thead", "tbody",
    "tr", "th", "td", "blockquote", "ul", "ol", "li", "h1", "h2", "h3",
    "h4", "h5", "h6", "p", "span", "a", "b", "i", "strong", "em", "style",
}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def merge(self, other: "ValidationResult") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def summary(self) -> str:
        status = "GEÇTİ" if self.ok else "KALDI"
        return f"Kalite kapısı: {status} — {len(self.errors)} hata, {len(self.warnings)} uyarı"


def _iter_strings(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_strings(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _iter_strings(child, f"{path}[{index}]")


def _check_local_paths(data: Any, result: ValidationResult) -> None:
    for path, text in _iter_strings(data):
        for pattern in LOCAL_PATH_PATTERNS:
            match = pattern.search(text)
            if match:
                result.add_error(f"{path}: yerel yol/PDF dosya adı yasak: {match.group(0)!r}")
                break


def _check_doi(value: Any, path: str, result: ValidationResult) -> None:
    doi = str(value or "").strip()
    if not doi:
        result.add_error(f"{path}: DOI boş")
    elif not DOI_RE.match(doi):
        result.add_error(f"{path}: geçersiz DOI {doi!r}; '10.' ile başlamalı")
    elif " " in doi or "\n" in doi:
        result.add_error(f"{path}: DOI boşluk içeremez")


def _require(mapping: dict[str, Any], keys: list[str], path: str, result: ValidationResult) -> None:
    for key in keys:
        value = mapping.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            result.add_error(f"{path}.{key}: zorunlu alan boş")


def _validate_intro(intro: Any, result: ValidationResult) -> None:
    if not isinstance(intro, dict):
        result.add_error("$.intro: nesne olmalı")
        return
    paragraphs = intro.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        result.add_error("$.intro.paragraphs: en az bir paragraf olmalı")
        return
    for index, paragraph in enumerate(paragraphs):
        path = f"$.intro.paragraphs[{index}]"
        if isinstance(paragraph, str):
            if not paragraph.strip():
                result.add_error(f"{path}: boş paragraf")
            continue
        if not isinstance(paragraph, dict):
            result.add_error(f"{path}: metin veya nesne olmalı")
            continue
        segments = paragraph.get("segments")
        if segments is not None:
            if not isinstance(segments, list) or not segments:
                result.add_error(f"{path}.segments: boş olamaz")
                continue
            for sindex, segment in enumerate(segments):
                spath = f"{path}.segments[{sindex}]"
                if not isinstance(segment, dict):
                    result.add_error(f"{spath}: nesne olmalı")
                    continue
                if not str(segment.get("text", "")).strip():
                    result.add_error(f"{spath}.text: boş olamaz")
        elif not str(paragraph.get("text", "")).strip():
            result.add_error(f"{path}: 'text' veya 'segments' zorunlu")


def _validate_cards(cards: Any, result: ValidationResult) -> None:
    if not isinstance(cards, list) or not cards:
        result.add_error("$.change_cards: en az bir değişiklik kartı olmalı")
        return
    for index, card in enumerate(cards):
        path = f"$.change_cards[{index}]"
        if not isinstance(card, dict):
            result.add_error(f"{path}: nesne olmalı")
            continue
        _require(card, ["location", "author_sentence", "rewritten_sentence"], path, result)
        sources = card.get("sources")
        if not isinstance(sources, list) or not sources:
            result.add_error(f"{path}.sources: en az bir kaynak olmalı")
        else:
            for sindex, source in enumerate(sources):
                spath = f"{path}.sources[{sindex}]"
                if not isinstance(source, dict):
                    result.add_error(f"{spath}: nesne olmalı")
                    continue
                _require(source, ["citation", "page", "doi", "quote", "translation"], spath, result)
                _check_doi(source.get("doi"), f"{spath}.doi", result)
        notes = card.get("notes")
        if not isinstance(notes, list) or not notes:
            result.add_error(f"{path}.notes: en az bir düzeltme notu olmalı")
        else:
            for nindex, note in enumerate(notes):
                npath = f"{path}.notes[{nindex}]"
                if not isinstance(note, dict):
                    result.add_error(f"{npath}: nesne olmalı")
                    continue
                _require(note, ["what", "why"], npath, result)
        status = card.get("evidence_status")
        if status and str(status).lower() not in {
            "supported", "partially_supported", "partial", "contradicted",
            "not_found", "out_of_scope",
        }:
            result.add_warning(f"{path}.evidence_status: bilinmeyen durum {status!r}")


def _validate_sources(items: Any, result: ValidationResult) -> None:
    if not isinstance(items, list) or not items:
        result.add_error("$.source_audit: en az bir kaynak olmalı")
        return
    seen: set[str] = set()
    for index, item in enumerate(items):
        path = f"$.source_audit[{index}]"
        if not isinstance(item, dict):
            result.add_error(f"{path}: nesne olmalı")
            continue
        _require(item, ["no", "citation", "doi", "journal", "year", "quartile", "role", "limitation"], path, result)
        _check_doi(item.get("doi"), f"{path}.doi", result)
        doi = str(item.get("doi") or "").strip().lower()
        if doi:
            if doi in seen:
                result.add_error(f"{path}.doi: aynı DOI birden fazla kez listelenmiş: {doi}")
            seen.add(doi)
        if not str(item.get("quartile") or "").strip():
            result.add_warning(f"{path}.quartile: boş; bilinmiyorsa '-' yazın")
        if not str(item.get("role") or "").strip():
            result.add_error(f"{path}.role: kaynak kullanım rolü zorunlu")
        if not str(item.get("limitation") or "").strip():
            result.add_warning(f"{path}.limitation: sınırlılık boş")


def _validate_claims(items: Any, result: ValidationResult) -> None:
    if not isinstance(items, list) or not items:
        result.add_error("$.claim_matrix: en az bir iddia olmalı")
        return
    for index, item in enumerate(items):
        path = f"$.claim_matrix[{index}]"
        if not isinstance(item, dict):
            result.add_error(f"{path}: nesne olmalı")
            continue
        _require(item, ["claim_id", "claim", "status", "evidence"], path, result)
        status = str(item.get("status") or "").strip().lower()
        evidence = str(item.get("evidence") or "")
        citations = item.get("citations")
        if status in {"supported", "full", "partial", "partially_supported", "contradicted", "contradicts"}:
            if not citations:
                result.add_error(f"{path}.citations: destekli/kısmi iddiada atıf zorunlu")
            if not PAGE_RE.search(evidence):
                result.add_error(f"{path}.evidence: sayfa numarası (s. / sayfa / p.) zorunlu")
        elif status in {"not_found", "none"}:
            if not str(item.get("note") or "").strip() and "yok" not in evidence.lower():
                result.add_warning(f"{path}: kaynakta bulunamayan iddia için kısa gerekçe/not ekleyin")
        elif status in {"out_of_scope", "scope", "interpretation"}:
            pass
        else:
            result.add_warning(f"{path}.status: bilinmeyen durum {status!r}")


def _validate_references(items: Any, result: ValidationResult) -> None:
    if items is None:
        return
    if not isinstance(items, list):
        result.add_error("$.references: dizi olmalı")
        return
    for index, item in enumerate(items):
        path = f"$.references[{index}]"
        if not isinstance(item, dict):
            result.add_error(f"{path}: nesne olmalı")
            continue
        _require(item, ["authors", "year", "title", "doi"], path, result)
        _check_doi(item.get("doi"), f"{path}.doi", result)


def validate_data(data: Any, strict: bool = False) -> ValidationResult:
    result = ValidationResult()
    if not isinstance(data, dict):
        result.add_error("$: üst düzey JSON nesnesi olmalı")
        return result

    if data.get("schema") != 2:
        result.add_error("$.schema: 2 olmalı")
    _require(data, ["project", "title", "intro", "change_cards", "source_audit", "claim_matrix"], "$", result)
    if not str(data.get("generated_at") or "").strip():
        result.add_warning("$.generated_at: tarih yok; teslimde eklenmesi önerilir")

    _validate_intro(data.get("intro"), result)
    _validate_cards(data.get("change_cards"), result)
    _validate_sources(data.get("source_audit"), result)
    _validate_claims(data.get("claim_matrix"), result)
    _validate_references(data.get("references"), result)
    _check_local_paths(data, result)

    # Every card source must be present in the audited source inventory. This
    # prevents a report from citing a DOI that was never quality-checked.
    audit_dois = {
        str(item.get("doi") or "").strip().lower()
        for item in (data.get("source_audit") or [])
        if isinstance(item, dict) and str(item.get("doi") or "").strip()
    }
    if audit_dois:
        for cindex, card in enumerate(data.get("change_cards") or []):
            if not isinstance(card, dict):
                continue
            for sindex, source in enumerate(card.get("sources") or []):
                if not isinstance(source, dict):
                    continue
                doi = str(source.get("doi") or "").strip().lower()
                if doi and doi not in audit_dois:
                    result.add_error(
                        f"$.change_cards[{cindex}].sources[{sindex}].doi: "
                        f"DOI kaynak envanterinde yok: {doi}"
                    )

    summary = data.get("summary")
    if summary is not None:
        if not isinstance(summary, dict):
            result.add_error("$.summary: nesne olmalı")
        else:
            expected = {
                "change_cards": len(data.get("change_cards") or []),
                "sources": len(data.get("source_audit") or []),
                "claims": len(data.get("claim_matrix") or []),
                "not_found": sum(
                    1 for item in (data.get("claim_matrix") or [])
                    if isinstance(item, dict)
                    and str(item.get("status") or "").lower() in {"not_found", "none"}
                ),
            }
            for key, value in expected.items():
                if key in summary and summary.get(key) != value:
                    result.add_error(
                        f"$.summary.{key}: {summary.get(key)!r} yazılmış, gerçek değer {value}"
                    )

    method = str(data.get("method") or "")
    method_lower = method.lower()
    if "paperqa_ask" in method_lower and not any(
        phrase in method_lower
        for phrase in ("kullanılmadı", "kullanılmaz", "not used")
    ):
        result.add_warning("$.method: paperqa_ask kanıt olarak kullanılmamalı; yalnızca taslak/özet içindir")
    if not data.get("limitations"):
        result.add_warning("$.limitations: en az bir sınırlılık/not önerilir")
    if not data.get("correction_summary"):
        result.add_warning("$.correction_summary: düzeltme özeti önerilir")

    if strict:
        result.errors.extend(result.warnings)
        result.warnings = []
    return result


def validate_html(html_text: str) -> ValidationResult:
    result = ValidationResult()
    if "<meta charset=\"utf-8\">" not in html_text.lower().replace("'", '"'):
        result.add_error("HTML: <meta charset=\"utf-8\"> eksik")
    if "<style" not in html_text.lower():
        result.add_error("HTML: gömülü <style> bloğu yok")
    if SCRIPT_RE.search(html_text):
        result.add_error("HTML: <script>, <iframe> veya on* olay özniteliği yasak")
    for pattern in LOCAL_PATH_PATTERNS[:4]:
        if pattern.search(html_text):
            result.add_error(f"HTML: yerel yol sızıntısı: {pattern.pattern}")

    stack: list[str] = []
    for match in TAG_RE.finditer(html_text):
        closing, tag, self_closing = match.group(1), match.group(2).lower(), match.group(3)
        if tag not in BALANCE_TAGS or tag in VOID_TAGS or self_closing:
            continue
        if closing:
            if not stack:
                result.add_error(f"HTML: fazla kapanış etiketi </{tag}>")
            elif stack[-1] != tag:
                result.add_error(f"HTML: kapanış sırası hatalı: beklenen </{stack[-1]}>, gelen </{tag}>")
                while stack and stack[-1] != tag:
                    stack.pop()
                if stack:
                    stack.pop()
            else:
                stack.pop()
        else:
            stack.append(tag)
    if stack:
        result.add_error("HTML: kapanmamış etiketler: " + ", ".join(f"<{t}>" for t in stack))

    return result


def validate_report(data: Any, html_text: str | None = None, strict: bool = False) -> ValidationResult:
    result = validate_data(data, strict=strict)
    if html_text is not None:
        result.merge(validate_html(html_text))
    return result


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def schema_validate(data: Any, schema_path: str | Path) -> ValidationResult:
    """Validate against JSON Schema when jsonschema is installed."""
    result = ValidationResult()
    try:
        import jsonschema  # type: ignore
    except ImportError:
        result.add_warning("jsonschema yüklü değil; şema doğrulaması atlandı")
        return result
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        location = "$." + ".".join(str(part) for part in error.absolute_path) if error.absolute_path else "$"
        result.add_error(f"{location}: {error.message}")
    return result
