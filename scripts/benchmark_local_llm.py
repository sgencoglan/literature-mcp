#!/usr/bin/env python3
"""llama.cpp üzerinde küçük GGUF modellerini hız ve Türkçe çıktı açısından dener.

Örnek:

    python3 scripts/benchmark_local_llm.py \
        --threads 2,4 --n-predict 160 \
        --json-out /tmp/opencode/llamacpp-benchmark.json

Model yolları verilmezse ``~/.local/share/llama-models`` altında bilinen
dosya adları aranır. Çıktı, elle kalite değerlendirmesi için saklanır; bu
betik otomatik "kalite puanı" üretmez.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_MODELS = {
    "qwen2.5-3b": "qwen2.5-3b-instruct-q4_k_m.gguf",
}

PROMPT = (
    "Türkçe, akademik ve akıcı bir paragraf yaz. "
    "Konu: Ergenlerde sosyal medya kullanımı ile kaygı arasındaki ilişki. "
    "Yalnızca üç cümle kullan; sayı, kaynak veya atıf uydurma."
)

EVAL_RE = re.compile(
    r"eval time\s*=.*?/\s*(\d+)\s+runs.*?([\d.]+)\s+tokens per second",
    re.IGNORECASE,
)
PROMPT_EVAL_RE = re.compile(
    r"prompt eval time\s*=.*?/\s*(\d+)\s+tokens.*?([\d.]+)\s+tokens per second",
    re.IGNORECASE,
)
# llama-cli, ayrıntılı perf satırları kapalıyken özet satırı yazar. Ondalık
# ayırıcı yerel ayara göre virgül olabilir: [ Prompt: 21,5 t/s | Generation: 7,2 t/s ]
SUMMARY_RE = re.compile(
    r"\[\s*Prompt:\s*([\d.,]+)\s*t/s\s*\|\s*Generation:\s*([\d.,]+)\s*t/s\s*\]",
    re.IGNORECASE,
)


def _as_float(value: str) -> float:
    return float(value.replace(".", "").replace(",", ".")) if "," in value else float(value)


def _find_models(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for name, filename in DEFAULT_MODELS.items():
        path = root / filename
        if path.is_file():
            found[name] = path
    return found


def _parse_perf(stderr: str) -> dict[str, Any]:
    perf: dict[str, Any] = {}
    summary = SUMMARY_RE.search(stderr)
    if summary:
        perf["prompt_tokens_per_second"] = _as_float(summary.group(1))
        perf["eval_tokens_per_second"] = _as_float(summary.group(2))
    eval_match = EVAL_RE.search(stderr)
    if eval_match:
        perf["eval_tokens"] = int(eval_match.group(1))
        perf["eval_tokens_per_second"] = float(eval_match.group(2))
    prompt_match = PROMPT_EVAL_RE.search(stderr)
    if prompt_match:
        perf["prompt_tokens"] = int(prompt_match.group(1))
        perf["prompt_tokens_per_second"] = float(prompt_match.group(2))
    return perf


def _clean_output(stdout: str) -> str:
    # llama-cli banner, yükleme animasyonu ve prompt'u da basar; rapor için
    # yalnızca prompt'tan sonraki görünür metni tut.
    text = re.sub(r"\x1b\[[0-9;]*m", "", stdout)
    text = text.replace("\r", "")
    marker = f"> {PROMPT}"
    if marker in text:
        text = text.split(marker, 1)[1]
    text = re.split(r"\n\s*\[\s*Prompt:", text, maxsplit=1)[0]
    text = re.split(r"\n\s*Exiting\.\.\.", text, maxsplit=1)[0]
    return text.strip()


def run_one(
    llama_cli: Path,
    model: Path,
    threads: int,
    ctx: int,
    n_predict: int,
    temperature: float,
    timeout: int,
) -> dict[str, Any]:
    command = [
        str(llama_cli),
        "-m",
        str(model),
        "-c",
        str(ctx),
        "-t",
        str(threads),
        "-ngl",
        "0",
        "--temp",
        str(temperature),
        "-n",
        str(n_predict),
        "--no-display-prompt",
        "--single-turn",
        "--no-warmup",
        "-p",
        PROMPT,
    ]
    env = dict(os.environ)
    lib_dir = llama_cli.parent / "lib"
    env["LD_LIBRARY_PATH"] = (
        f"{lib_dir}:{env['LD_LIBRARY_PATH']}" if env.get("LD_LIBRARY_PATH") else str(lib_dir)
    )
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "model": model.name,
            "threads": threads,
            "ok": False,
            "error": f"timeout after {timeout}s",
            "stdout": _clean_output(exc.stdout or ""),
        }
    elapsed = time.perf_counter() - started
    result: dict[str, Any] = {
        "model": model.name,
        "threads": threads,
        "ok": completed.returncode == 0,
        "elapsed_seconds": round(elapsed, 2),
        "output": _clean_output(completed.stdout),
    }
    perf_text = re.sub(
        r"\x1b\[[0-9;]*m", "", f"{completed.stdout}\n{completed.stderr}"
    )
    result.update(_parse_perf(perf_text))
    if completed.returncode != 0:
        result["error"] = completed.stderr.strip()[-2000:]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--llama-cli",
        default=str(
            Path.home()
            / ".local/share/llama.cpp/llama-b11954/llama-cli"
        ),
    )
    parser.add_argument(
        "--model-root",
        default=str(Path.home() / ".local/share/llama-models"),
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="AD=YOL",
        help="Model adı ve GGUF yolu; birden çok kez verilebilir.",
    )
    parser.add_argument("--threads", default="2,4")
    parser.add_argument("--ctx", type=int, default=4096)
    parser.add_argument("--n-predict", type=int, default=160)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    llama_cli = Path(args.llama_cli).expanduser()
    if not llama_cli.is_file():
        print(f"llama-cli bulunamadı: {llama_cli}", file=sys.stderr)
        return 2

    models: dict[str, Path] = {}
    for item in args.model:
        if "=" not in item:
            print(f"--model biçimi AD=YOL olmalı: {item}", file=sys.stderr)
            return 2
        name, path = item.split("=", 1)
        models[name] = Path(path).expanduser()
    if not models:
        models = _find_models(Path(args.model_root).expanduser())
    if not models:
        print("GGUF model bulunamadı. Önce scripts/setup_llamacpp.sh çalıştırın.", file=sys.stderr)
        return 2

    thread_counts = [int(value) for value in args.threads.split(",") if value.strip()]
    results: list[dict[str, Any]] = []
    for name, model in models.items():
        if not model.is_file():
            print(f"Atlandı (yok): {name} -> {model}", file=sys.stderr)
            continue
        for threads in thread_counts:
            print(f"Çalışıyor: {name}, {threads} iş parçacığı...", file=sys.stderr, flush=True)
            result = run_one(
                llama_cli,
                model,
                threads,
                args.ctx,
                args.n_predict,
                args.temperature,
                args.timeout,
            )
            result["name"] = name
            results.append(result)
            speed = result.get("eval_tokens_per_second")
            print(
                f"  -> {result['elapsed_seconds']} sn, "
                f"{speed if speed is not None else '?'} tok/s",
                file=sys.stderr,
            )

    print()
    print("| Model | Thread | Süre (sn) | Üretim tok/s | Prompt tok/s |")
    print("|---|---:|---:|---:|---:|")
    for result in results:
        print(
            "| {name} | {threads} | {elapsed} | {speed} | {prompt} |".format(
                name=result["name"],
                threads=result["threads"],
                elapsed=result.get("elapsed_seconds", "?"),
                speed=result.get("eval_tokens_per_second", "?"),
                prompt=result.get("prompt_tokens_per_second", "?"),
            )
        )

    print("\n## Üretilen metinler\n")
    for result in results:
        print(f"### {result['name']} / {result['threads']} thread\n")
        print(result.get("output") or result.get("error") or "(çıktı yok)")
        print()

    if args.json_out:
        output_path = Path(args.json_out).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {"prompt": PROMPT, "results": results},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"JSON: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
