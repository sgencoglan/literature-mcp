#!/usr/bin/env python3
"""Check tracked files without printing potentially private values."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

PATTERNS = {
    "personal home path": re.compile(
        r"/(?:home|Users)/(?!(?:you|user|username|kullanici)(?:/|\b))[\w.-]+/"
        r"|[A-Za-z]:\\Users\\(?!(?:you|user|username|kullanici)\\)[\w.-]+\\"
    ),
    "access token": re.compile(
        r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
        r"|sk-[A-Za-z0-9_-]{24,}|AKIA[0-9A-Z]{16}"
    ),
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "personal email": re.compile(
        r"[\w.+-]+@(?!(?:[\w-]+\.)*example\.(?:com|org|net)\b)[\w.-]+\.[A-Za-z]{2,}"
    ),
}
PRIVATE_FILE = re.compile(
    r"(?:^|/)(?:\.env(?:\..+)?|setup\.txt|projects\.json|manifest\.csv|"
    r"analysis_updates\.json|opencode\.(?:local\.)?json)$"
    r"|(?:^|/)(?:\.literature-mcp|\.venv|indexes|projects|outputs|"
    r"01_konu_belirleme|02_yazim_plani|03_kaynak_kesfi|04_taslak|05_analiz)/"
    r"|\.(?:pdf(?:\.gz)?|gguf|pem|key|log|pid)$", re.I,
)


def check_file(path: str, content: str) -> list[str]:
    findings = []
    if PRIVATE_FILE.search(path) and not path.endswith(".example"):
        findings.append(f"{path}: private runtime/config file")
    for number, line in enumerate(content.splitlines(), 1):
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append(f"{path}:{number}: {label}")
    return findings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root,
    ).decode().split("\0")
    findings = []
    for path in sorted(set(filter(None, paths))):
        file = root / path
        if file.is_file():
            findings.extend(check_file(path, file.read_bytes().decode("utf-8", errors="replace")))
    for finding in findings:
        print(finding)
    print(f"Privacy check: {len(findings)} finding(s)")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
