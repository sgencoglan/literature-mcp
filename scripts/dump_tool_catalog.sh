#!/usr/bin/env bash
# 26 MCP aracının ad + açıklama + JSON girdi şemasını docs/tool-catalog.json'a yazar.
# İki paketin bağımlılıkları kurulu olmalıdır.
#
# Kullanım:
#   bash scripts/dump_tool_catalog.sh
#   META_PY=/path/to/venv/bin/python PAPER_PY=/path/to/venv/bin/python bash scripts/dump_tool_catalog.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
META_PY="${META_PY:-$PY}"
PAPER_PY="${PAPER_PY:-$PY}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if ! PYTHONPATH="$ROOT/packages/sciencedirect-meta/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$META_PY" -c 'import sciencedirect_meta.unified' 2>/dev/null; then
  echo "sciencedirect-meta içe aktarılamadı. META_PY ve PYTHONPATH'i kontrol edin." >&2
  exit 1
fi

PYTHONPATH="$ROOT/packages/sciencedirect-meta/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$META_PY" - <<'PY' > "$TMP/meta.json"
import asyncio
import json

from sciencedirect_meta import unified


async def main():
    tools = await unified.handle_list_tools()
    out = []
    for tool in tools:
        out.append({
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema or {},
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))


asyncio.run(main())
PY

(
  cd "$ROOT/packages/paperqa-local"
  if ! "$PAPER_PY" -c 'import paperqa_mcp' 2>/dev/null; then
    echo "paperqa-local içe aktarılamadı. PAPER_PY ve PaperQA2 kurulumunu kontrol edin." >&2
    exit 1
  fi
  "$PAPER_PY" - <<'PY' > "$TMP/paperqa.json"
import asyncio
import json

import paperqa_mcp


async def main():
    tools = await paperqa_mcp.mcp.list_tools()
    out = []
    for tool in tools:
        out.append({
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": getattr(tool, "inputSchema", None) or {},
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))


asyncio.run(main())
PY
)

"$PY" - "$TMP/meta.json" "$TMP/paperqa.json" "$ROOT/docs/tool-catalog.json" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

meta_path, paper_path, out_path = map(Path, sys.argv[1:])
meta = json.loads(meta_path.read_text(encoding="utf-8"))
paper = json.loads(paper_path.read_text(encoding="utf-8"))

payload = {
    "schema": 1,
    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "description": (
        "İki MCP sunucusunun araç kataloğu. input_schema alanı MCP JSON Schema'dır; "
        "ajanlar araç seçimi ve parametre doğrulaması için kullanır."
    ),
    "servers": {
        "sciencedirect-meta": {"tool_count": len(meta), "tools": meta},
        "paperqa-local": {"tool_count": len(paper), "tools": paper},
    },
    "total_tools": len(meta) + len(paper),
}

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Yazıldı: {out_path} ({payload['total_tools']} araç)")
PY
