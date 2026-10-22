"""Command line interface for the golden-standard chapter report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .cleanup import CleanupError, cleanup_manifest, write_manifest
from .markdown import render_markdown
from .render import render_report
from .validate import (
    ValidationResult,
    schema_validate,
    validate_data,
    validate_html,
)


def _find_schema() -> Path | None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "schemas" / "chapter-report.schema.json"
        if candidate.is_file():
            return candidate
    return None


def _load_json(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Girdi bulunamadı: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Geçersiz JSON: {path}: {exc}") from exc


def _print_result(result: ValidationResult) -> None:
    for warning in result.warnings:
        print(f"UYARI: {warning}")
    for error in result.errors:
        print(f"HATA: {error}", file=sys.stderr)
    print(result.summary())


def _validate_all(data: dict, schema: Path | None, strict: bool) -> ValidationResult:
    result = validate_data(data, strict=strict)
    if schema and schema.is_file():
        result.merge(schema_validate(data, schema))
    return result


def _cmd_build(args: argparse.Namespace) -> int:
    data = _load_json(args.input)
    schema = Path(args.schema) if args.schema else _find_schema()
    result = _validate_all(data, schema, args.strict)
    if result.errors:
        _print_result(result)
        return 2

    html_text = render_report(data)
    html_result = validate_html(html_text)
    result.merge(html_result)
    if result.errors:
        _print_result(result)
        return 2
    _print_result(result)

    if args.check:
        print("Kontrol tamam; dosya yazılmadı.")
        return 0

    output = Path(args.output)
    if output.exists() and not args.force:
        print(f"HATA: çıktı zaten var: {output} (üzerine yazmak için --force)", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    print(f"HTML yazıldı: {output} ({len(html_text.encode('utf-8'))} bayt)")

    files: list[tuple[str | Path, str]] = [(output, "html")]
    if args.markdown:
        markdown_path = Path(args.markdown)
        if markdown_path.exists() and not args.force:
            print(
                f"HATA: Markdown çıktısı zaten var: {markdown_path} (üzerine yazmak için --force)",
                file=sys.stderr,
            )
            return 2
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_text = render_markdown(data)
        markdown_path.write_text(markdown_text, encoding="utf-8")
        print(f"Markdown yazıldı: {markdown_path} ({len(markdown_text.encode('utf-8'))} bayt)")
        files.append((markdown_path, "markdown"))

    manifest = Path(args.manifest) if args.manifest else output.with_name(output.stem + ".manifest.json")
    for raw in args.artifact or []:
        for part in str(raw).split(","):
            part = part.strip()
            if not part:
                continue
            artifact = Path(part)
            if not artifact.exists():
                print(f"UYARI: artifact bulunamadı, manifeste eklenmedi: {artifact}")
                continue
            files.append((artifact, "intermediate"))
    try:
        write_manifest(manifest, str(data.get("project") or ""), files)
    except CleanupError as exc:
        print(f"HATA: manifest yazılamadı: {exc}", file=sys.stderr)
        return 2
    print(f"Manifest yazıldı: {manifest}")

    if args.cleanup != "keep":
        try:
            cleanup_manifest(
                manifest,
                scope="all" if args.cleanup == "all" else "intermediate",
                dry_run=args.dry_run,
                yes=args.yes,
            )
        except CleanupError as exc:
            print(f"HATA: temizlik yapılamadı: {exc}", file=sys.stderr)
            return 2
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    data = _load_json(args.input)
    schema = Path(args.schema) if args.schema else _find_schema()
    result = _validate_all(data, schema, args.strict)
    html_text = render_report(data)
    result.merge(validate_html(html_text))
    _print_result(result)
    return 0 if result.ok else 1


def _cmd_cleanup(args: argparse.Namespace) -> int:
    try:
        cleanup_manifest(
            args.manifest,
            scope=args.scope,
            dry_run=args.dry_run,
            yes=args.yes,
            force=args.force,
            delete_manifest=args.delete_manifest,
        )
    except CleanupError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chapter-report",
        description="Altın standart kitap bölümü raporu üretir ve doğrular.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="JSON verisinden HTML rapor üret")
    build.add_argument("input", help="Rapor JSON dosyası")
    build.add_argument("-o", "--output", help="Çıktı HTML dosyası")
    build.add_argument("--markdown", help="Opsiyonel Markdown çıktısı (düzenleme katmanı)")
    build.add_argument("--manifest", help="Manifest yolu (varsayılan: <html>.manifest.json)")
    build.add_argument("--artifact", action="append", help="Manifeste eklenecek ara dosya; birden çok kez veya virgülle")
    build.add_argument("--schema", help="JSON Schema yolu")
    build.add_argument("--strict", action="store_true", help="Uyarıları da hata say")
    build.add_argument("--check", action="store_true", help="Yalnızca doğrula; HTML yazma")
    build.add_argument("--force", action="store_true", help="Mevcut HTML'in üzerine yaz")
    build.add_argument("--cleanup", choices=["keep", "ask", "intermediate", "all"], default="keep")
    build.add_argument("--dry-run", action="store_true", help="Temizlikte yalnızca listele")
    build.add_argument("--yes", action="store_true", help="Temizlikte onay sorma")
    build.set_defaults(func=_cmd_build)

    validate = sub.add_parser("validate", help="JSON ve üretilecek HTML'i doğrula")
    validate.add_argument("input", help="Rapor JSON dosyası")
    validate.add_argument("--schema", help="JSON Schema yolu")
    validate.add_argument("--strict", action="store_true", help="Uyarıları da hata say")
    validate.set_defaults(func=_cmd_validate)

    cleanup = sub.add_parser("cleanup", help="Manifestteki üretilmiş dosyaları temizle")
    cleanup.add_argument("--manifest", required=True, help="Rapor manifest dosyası")
    cleanup.add_argument("--scope", choices=["intermediate", "all"], default="intermediate")
    cleanup.add_argument("--dry-run", action="store_true")
    cleanup.add_argument("--yes", action="store_true")
    cleanup.add_argument("--force", action="store_true", help="Hash değişmiş olsa da sil")
    cleanup.add_argument("--delete-manifest", action="store_true", help="scope=all ise manifesti de sil")
    cleanup.set_defaults(func=_cmd_cleanup)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "build" and not args.check and not args.output:
        parser.error("build için -o/--output gerekli (veya --check kullanın)")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
