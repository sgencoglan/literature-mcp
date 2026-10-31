"""Local PaperQA2 MCP server — multi-project, project-isolated.

Kavramlar
---------
- **Proje kaydı** (``projects.json``): her proje için ``paper_directory``,
  ``manifest`` (CSV), ``index_directory`` ve ``index_name`` tutar.
- **İzolasyon:** Her projenin kendi manifesti ve kendi Tantivy indeksi vardır.
  Bir projedeki arama/okuma/indeksleme diğer projelere taşmaz.
- Araçlar ``project`` parametresini açıkça ister; bilinmeyen proje adı kayıtlı
  projeleri listeleyen bir hata döndürür.
- **İndeks üyeliği manifest tarafından belirlenir** (klasör taraması değil):
  klasöre sonradan bırakılan bir PDF, manifeste eklenmedikçe indekse girmez.
  Böylece eski projeler sonradan eklenen dosyalarla karışmaz.

Araçlar
-------
``paperqa_projects``          — kayıtlı projeler ve durumları
``paperqa_register_project``  — klasörü proje olarak kaydet + manifest üret
``paperqa_build_index``       — proje indeksini kur/güncelle (manifest üyeliği)
``paperqa_status``            — proje indeks durumu
``paperqa_search``            — proje içinde semantik arama (LLM'siz)
``paperqa_read_pages``        — projedeki PDF'ten sayfa okuma (DOI ile)
``paperqa_llm_status``        — yerel llama.cpp sunucusunun durumu
``paperqa_ask``               — yerel LLM ile soru (taslak; doğrulama gerekir)
"""

from __future__ import annotations

import asyncio
import atexit
import copy
import csv
import json
import logging
import math
import os
import re
import shutil
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

# PyMuPDF ve PaperQA2 ağır bağımlılıklar içe aktarır. MCP sunucusu OpenCode'un
# başlangıç zaman aşımına takılmamak için bunlar yalnızca gerektiğinde yüklenir;
# aşağıdaki fonksiyonlar kendi importlarını yapar.

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_REGISTRY = str(Path.home() / ".literature-mcp" / "projects.json")
REGISTRY_PATH = Path(
    os.environ.get("LIT_PROJECTS_REGISTRY", DEFAULT_REGISTRY)
).expanduser()
DEFAULT_INDEX_ROOT = Path(
    os.environ.get("PAPERQA_INDEX_ROOT", str(Path.home() / ".literature-mcp" / "indexes"))
).expanduser()
DEFAULT_PROJECTS_ROOT = Path(
    os.environ.get("PAPERQA_PROJECTS_ROOT", str(Path.home() / ".literature-mcp" / "projects"))
).expanduser()

EMBEDDING = "st-multi-qa-MiniLM-L6-cos-v1"
MAX_PAGES_PER_READ = 50

# Yerel LLM arka ucu: llama.cpp. Sunucu OpenAI uyumlu /v1 uç noktası sunduğu
# için LiteLLM tarafında "openai/" öneki kullanılır.
LOCAL_BACKEND = "llamacpp"
LOCAL_PREFIX = "openai/"


def _model_name(value: str) -> str:
    """Kullanıcı LiteLLM önekini de yazdıysa model adını ayır."""
    return value[len(LOCAL_PREFIX) :] if value.startswith(LOCAL_PREFIX) else value


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "hayır", "hayir"}


LOCAL_MODEL = _model_name(
    os.environ.get("PAPERQA_LOCAL_LLM") or "qwen2.5-3b-instruct"
)
LOCAL_API_BASE = (
    os.environ.get("PAPERQA_LOCAL_API_BASE") or "http://127.0.0.1:8080/v1"
).rstrip("/")
LOCAL_API_KEY = os.environ.get("PAPERQA_LOCAL_API_KEY", "").strip()
LOCAL_MAX_TOKENS = _env_int("PAPERQA_LOCAL_MAX_TOKENS", 400, 64)
LOCAL_TIMEOUT = _env_int("PAPERQA_LOCAL_TIMEOUT", 600, 30)
LOCAL_TEMPERATURE = _env_float("PAPERQA_LOCAL_TEMPERATURE", 0.1)
LOCAL_LLM = f"{LOCAL_PREFIX}{LOCAL_MODEL}"

# Otomatik llama.cpp yönetimi. MCP, paperqa_ask çağrıldığında sunucuyu
# başlatır; yalnızca kendisi başlattıysa boşta kalınca durdurur.
AUTO_START_LLAMA = _env_bool("PAPERQA_AUTO_START", True)
AUTO_STOP_IDLE = _env_int("PAPERQA_AUTO_STOP_IDLE", 300, 0)
LLAMA_START_TIMEOUT = _env_int("PAPERQA_LLAMA_START_TIMEOUT", 120, 10)
LLAMA_MIN_FREE_MB = _env_int("PAPERQA_LLAMA_MIN_FREE_MB", 1200, 0)
LLAMA_MODEL_CHOICE = os.environ.get("PAPERQA_LLAMACPP_MODEL", "qwen").strip() or "qwen"
LLAMA_SCRIPT = Path(
    os.environ.get(
        "PAPERQA_LLAMACPP_SCRIPT",
        str(Path(__file__).resolve().parents[2] / "scripts" / "start_llamacpp.sh"),
    )
).expanduser()
LLAMA_RUNTIME_DIR = Path(
    os.environ.get("PAPERQA_RUNTIME_DIR", "/tmp/opencode")
).expanduser()
LLAMA_LOG = Path(
    os.environ.get("PAPERQA_LLAMACPP_LOG", str(LLAMA_RUNTIME_DIR / "llama-server-auto.log"))
).expanduser()
LLAMA_PIDFILE = Path(
    os.environ.get(
        "PAPERQA_LLAMACPP_PIDFILE",
        str(Path.home() / ".literature-mcp" / "llama-server.pid"),
    )
).expanduser()


def _local_llm_params() -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": LOCAL_LLM,
        "api_base": LOCAL_API_BASE,
        "timeout": LOCAL_TIMEOUT,
        "max_tokens": LOCAL_MAX_TOKENS,
        "temperature": LOCAL_TEMPERATURE,
    }
    # llama.cpp kimlik doğrulaması istemez; LiteLLM'in openai sağlayıcısı
    # yine de bir anahtar bekler.
    params["api_key"] = LOCAL_API_KEY or "sk-no-key-required"
    return params


LOCAL_LLM_CONFIG = {
    "model_list": [
        {
            "model_name": LOCAL_LLM,
            "litellm_params": _local_llm_params(),
        }
    ]
}

MAILTO = os.environ.get("CROSSREF_MAILTO", "research@example.org")
HTTP_TIMEOUT = 25.0
MANIFEST_FIELDS = ["file_location", "doi", "title", "journal", "year", "authors"]
INDEX_FIELDS = ["file_location", "body", "title", "year"]
PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,60}$")
PDF_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)

logger = logging.getLogger("paperqa-local")

mcp = FastMCP("paperqa-local")

_registry_cache: dict[str, Any] = {"mtime": None, "data": None}
_settings_cache: dict[str, Any] = {}
_docs_cache: dict[str, Any] = {}
_doc_meta: dict[str, dict[str, dict[str, Any]]] = {}
_load_locks: dict[str, asyncio.Lock] = {}
_http_client: Optional[httpx.AsyncClient] = None
_llama_lock: Optional[asyncio.Lock] = None
_llama_process: Optional[asyncio.subprocess.Process] = None
_llama_started_by_us = False
_llama_active_asks = 0
_llama_last_used = 0.0
_llama_stop_task: Optional[asyncio.Task] = None


def _client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={
                "User-Agent": f"paperqa-local-mcp/0.2 (mailto:{MAILTO})",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )
    return _http_client


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Automatic llama.cpp lifecycle
# --------------------------------------------------------------------------- #

def _llama_guard() -> asyncio.Lock:
    global _llama_lock
    if _llama_lock is None:
        _llama_lock = asyncio.Lock()
    return _llama_lock


def _available_memory_mb() -> int | None:
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        return None
    return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_is_llama(pid: int) -> bool:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    command = raw.replace(b"\0", b" ").decode("utf-8", errors="replace")
    return "llama-server" in command and LOCAL_MODEL in command


def _read_pidfile() -> dict[str, Any] | None:
    try:
        data = json.loads(LLAMA_PIDFILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_pidfile(proc: asyncio.subprocess.Process) -> None:
    LLAMA_PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": proc.pid,
        "started_at": _now(),
        "api_base": LOCAL_API_BASE,
        "model": LOCAL_MODEL,
        "log": str(LLAMA_LOG),
    }
    tmp = LLAMA_PIDFILE.with_name(
        f"{LLAMA_PIDFILE.name}.{os.getpid()}.tmp"
    )
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(LLAMA_PIDFILE)


def _remove_pidfile() -> None:
    try:
        LLAMA_PIDFILE.unlink()
    except FileNotFoundError:
        pass


def _log_tail(limit: int = 20) -> str:
    try:
        lines = LLAMA_LOG.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-limit:])


def _adopt_pidfile() -> None:
    """Önceki MCP sürecinin başlattığı sunucuyu sahiplen."""
    global _llama_started_by_us
    data = _read_pidfile()
    if not data:
        return
    try:
        pid = int(data.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid and _pid_alive(pid) and _pid_is_llama(pid):
        _llama_started_by_us = True


async def _terminate_pid(pid: int, timeout: float = 10.0) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        await asyncio.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


async def _cleanup_stale_pidfile() -> dict[str, Any] | None:
    """Önceki otomatik sunucu hâlâ açılıyorsa bekle; hazırsa sahiplen."""
    global _llama_started_by_us
    data = _read_pidfile()
    if not data:
        return None
    try:
        pid = int(data.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if not pid or not _pid_alive(pid) or not _pid_is_llama(pid):
        _remove_pidfile()
        return None
    deadline = time.monotonic() + min(30, LLAMA_START_TIMEOUT)
    while time.monotonic() < deadline:
        poll = await paperqa_llm_status(timeout_seconds=1.0)
        if poll.get("reachable") and poll.get("model_available"):
            _llama_started_by_us = True
            return poll
        if not _pid_alive(pid):
            break
        await asyncio.sleep(0.5)
    await _terminate_pid(pid)
    _remove_pidfile()
    return None


async def _stop_llama_server(reason: str = "") -> dict[str, Any]:
    global _llama_process, _llama_started_by_us, _llama_stop_task
    async with _llama_guard():
        task = _llama_stop_task
        _llama_stop_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        proc = _llama_process
        if proc is not None:
            await _terminate_process(proc)
            _llama_process = None
            _llama_started_by_us = False
            _remove_pidfile()
            return {"stopped": True, "pid": proc.pid, "reason": reason}
        data = _read_pidfile()
        try:
            pid = int(data.get("pid") or 0) if data else 0
        except (TypeError, ValueError):
            pid = 0
        if pid and _pid_alive(pid) and _pid_is_llama(pid):
            await _terminate_pid(pid)
            _llama_started_by_us = False
            _remove_pidfile()
            return {
                "stopped": True,
                "pid": pid,
                "reason": reason,
                "orphan": True,
            }
        _remove_pidfile()
        return {"stopped": False, "reason": reason or "not running"}


def _atexit_stop_llama() -> None:
    if not _llama_started_by_us:
        return
    proc = _llama_process
    if proc is not None and proc.returncode is None:
        try:
            proc.terminate()
        except (ProcessLookupError, RuntimeError):
            pass
    data = _read_pidfile()
    try:
        pid = int(data.get("pid") or 0) if data else 0
    except (TypeError, ValueError):
        pid = 0
    if pid and _pid_alive(pid) and _pid_is_llama(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    _remove_pidfile()


atexit.register(_atexit_stop_llama)


async def _idle_stop_after(delay: float, stamp: float) -> None:
    try:
        await asyncio.sleep(delay)
        if _llama_active_asks > 0 or _llama_last_used != stamp:
            return
        await _stop_llama_server("idle timeout")
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("llama.cpp idle stop failed")


def _schedule_idle_stop() -> None:
    global _llama_stop_task
    if AUTO_STOP_IDLE <= 0 or not _llama_started_by_us:
        return
    if _llama_stop_task is not None:
        _llama_stop_task.cancel()
    _llama_stop_task = asyncio.create_task(
        _idle_stop_after(AUTO_STOP_IDLE, _llama_last_used)
    )


def _touch_llama() -> None:
    global _llama_last_used
    _llama_last_used = time.monotonic()
    _schedule_idle_stop()


async def _ensure_llama_server() -> dict[str, Any]:
    """Sunucu hazırsa döndür; değilse otomatik başlat ve hazır olmasını bekle."""
    global _llama_process, _llama_started_by_us
    status = await paperqa_llm_status(timeout_seconds=2.0)
    if status.get("reachable") and status.get("model_available"):
        _adopt_pidfile()
        if _llama_started_by_us:
            _touch_llama()
        return status
    if not AUTO_START_LLAMA:
        return status

    async with _llama_guard():
        status = await paperqa_llm_status(timeout_seconds=2.0)
        if status.get("reachable") and status.get("model_available"):
            _adopt_pidfile()
            if _llama_started_by_us:
                _touch_llama()
            return status
        if status.get("reachable") and not status.get("model_available"):
            status["error"] = (
                "Sunucu erişilebilir ama beklenen model yüklü değil: "
                f"{LOCAL_MODEL}"
            )
            status["hint"] = (
                "Sunucuyu durdurup paperqa_ask'ı yeniden deneyin; MCP doğru "
                "modeli otomatik başlatacaktır."
            )
            return status

        adopted = await _cleanup_stale_pidfile()
        if adopted is not None:
            _touch_llama()
            return adopted

        free_mb = _available_memory_mb()
        if free_mb is not None and free_mb < LLAMA_MIN_FREE_MB:
            status["error"] = (
                f"Yetersiz boş RAM: {free_mb} MB; en az "
                f"{LLAMA_MIN_FREE_MB} MB gerekiyor."
            )
            status["hint"] = (
                "Bellek kullanan uygulamaları kapatın veya "
                "PAPERQA_LLAMA_MIN_FREE_MB değerini düşürün."
            )
            return status
        if not LLAMA_SCRIPT.is_file():
            status["error"] = f"Başlatma betiği bulunamadı: {LLAMA_SCRIPT}"
            status["hint"] = "Depoyu ve PAPERQA_LLAMACPP_SCRIPT ayarını kontrol edin."
            return status

        LLAMA_LOG.parent.mkdir(parents=True, exist_ok=True)
        try:
            log_file = LLAMA_LOG.open("ab")
        except OSError as exc:
            status["error"] = f"llama.cpp log dosyası açılamadı: {exc}"
            return status
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                str(LLAMA_SCRIPT),
                LLAMA_MODEL_CHOICE,
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
            )
        except Exception as exc:  # noqa: BLE001
            status["error"] = (
                f"llama.cpp başlatılamadı: {type(exc).__name__}: {exc}"
            )
            return status
        finally:
            log_file.close()

        _llama_process = proc
        _llama_started_by_us = True
        _write_pidfile(proc)
        logger.info(
            "llama.cpp auto-start: pid=%s model=%s log=%s",
            proc.pid,
            LOCAL_MODEL,
            LLAMA_LOG,
        )

        deadline = time.monotonic() + LLAMA_START_TIMEOUT
        while time.monotonic() < deadline:
            if proc.returncode is not None:
                break
            poll = await paperqa_llm_status(timeout_seconds=2.0)
            if poll.get("reachable") and poll.get("model_available"):
                _touch_llama()
                return poll
            await asyncio.sleep(0.5)

        await _terminate_process(proc)
        _llama_process = None
        _llama_started_by_us = False
        _remove_pidfile()
        status = await paperqa_llm_status(timeout_seconds=1.0)
        status["error"] = "llama.cpp otomatik başlatılamadı."
        status["log"] = str(LLAMA_LOG)
        tail = _log_tail()
        if tail:
            status["log_tail"] = tail
        return status


# --------------------------------------------------------------------------- #
# Project registry (shared with the sciencedirect-meta MCP)
# --------------------------------------------------------------------------- #

def _load_registry(force: bool = False) -> dict[str, Any]:
    global _registry_cache
    try:
        mtime = REGISTRY_PATH.stat().st_mtime
    except OSError:
        data = {"schema": 1, "projects": {}}
        _registry_cache = {"mtime": None, "data": data}
        return data
    if (
        not force
        and _registry_cache["data"] is not None
        and _registry_cache["mtime"] == mtime
    ):
        return _registry_cache["data"]
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    data.setdefault("schema", 1)
    data.setdefault("projects", {})
    _registry_cache = {"mtime": mtime, "data": data}
    return data


def _save_registry(data: dict[str, Any]) -> None:
    global _registry_cache
    data["updated_at"] = _now()
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_PATH.with_name(f"{REGISTRY_PATH.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(REGISTRY_PATH)
    _registry_cache = {"mtime": REGISTRY_PATH.stat().st_mtime, "data": data}


def _project_config(name: str) -> dict[str, Any]:
    name = (name or "").strip()
    registry = _load_registry()
    projects = registry.get("projects") or {}
    if name not in projects:
        available = ", ".join(sorted(projects)) or "(kayıtlı proje yok)"
        raise ValueError(
            f"Bilinmeyen proje: {name!r}. Kayıtlı projeler: {available}"
        )
    return projects[name]


def _validate_index_name(value: str) -> str:
    value = (value or "").strip()
    if value in {".", ".."} or not PROJECT_NAME_RE.match(value):
        raise ValueError(
            "index_name 2-61 karakter olmalı ve yalnızca harf, rakam, '.', "
            "'_', '-' içermelidir."
        )
    return value


def _index_root(cfg: dict[str, Any]) -> tuple[Path, Path]:
    """İndeks kökünü doğrular; (index_directory, index_root) döndürür."""
    index_dir = Path(cfg["index_directory"]).expanduser().resolve()
    index_name = _validate_index_name(str(cfg.get("index_name") or ""))
    root = index_dir / index_name
    resolved = root.resolve()
    if resolved == index_dir or not resolved.is_relative_to(index_dir):
        raise ValueError(
            f"Geçersiz indeks yolu: {root}. index_name proje klasörü dışına çıkamaz."
        )
    return index_dir, root


def _invalidate_project_cache(name: str) -> None:
    """Proje ayarları/indeksi değişince bellek içi türevleri temizler."""
    _settings_cache.pop(name, None)
    _docs_cache.pop(name, None)
    _doc_meta.pop(name, None)


def _backup_index_root(index_root: Path) -> Path:
    """Mevcut indeks klasörünü silmek yerine zaman damgalı yedeğe taşır."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = index_root.with_name(f"{index_root.name}.bak-{stamp}")
    counter = 1
    while backup.exists():
        backup = index_root.with_name(f"{index_root.name}.bak-{stamp}-{counter}")
        counter += 1
    index_root.rename(backup)
    return backup


def _paper_directory(cfg: dict[str, Any]) -> Path:
    return Path(cfg["paper_directory"]).expanduser()


def _manifest_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg["manifest"]).expanduser()


def _recurse(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("include_subdirectories", False))


def _project_summary(name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    directory = _paper_directory(cfg)
    manifest = _manifest_path(cfg)
    pdfs = _scan_pdfs(directory, _recurse(cfg)) if directory.exists() else []
    manifest_rows: list[dict[str, Any]] = []
    manifest_error: str | None = None
    if manifest.exists():
        try:
            manifest_rows = _read_manifest(cfg)
        except Exception as exc:  # noqa: BLE001
            manifest_rows = []
            manifest_error = f"{type(exc).__name__}: {exc}"
    return {
        "project": name,
        "title": cfg.get("title"),
        "description": cfg.get("description"),
        "paper_directory": str(directory),
        "directory_exists": directory.exists(),
        "recurse_subdirectories": _recurse(cfg),
        "pdf_files_in_directory": len(pdfs),
        "manifest": str(manifest),
        "manifest_rows": len(manifest_rows),
        "manifest_error": manifest_error,
        "index_name": cfg.get("index_name"),
        "index_directory": cfg.get("index_directory"),
        "output_directory": cfg.get("output_directory") or str(directory),
        "analysis_json": cfg.get("analysis_json"),
        "created_at": cfg.get("created_at"),
        "updated_at": cfg.get("updated_at"),
    }


# --------------------------------------------------------------------------- #
# Settings per project
# --------------------------------------------------------------------------- #

def _settings_for(name: str, cfg: dict[str, Any]) -> Settings:
    from paperqa.settings import AgentSettings, IndexSettings, ParsingSettings, Settings

    if name in _settings_cache:
        return _settings_cache[name]
    index_dir, _ = _index_root(cfg)
    index_name = _validate_index_name(str(cfg["index_name"]))
    settings = Settings(
        llm=LOCAL_LLM,
        llm_config=LOCAL_LLM_CONFIG,
        summary_llm=LOCAL_LLM,
        summary_llm_config=LOCAL_LLM_CONFIG,
        embedding=EMBEDDING,
        parsing=ParsingSettings(
            use_doc_details=False,
            multimodal=False,
            reader_config={
                "chunk_chars": 5000,
                "overlap": 250,
                "use_block_parsing": True,
            },
        ),
        agent=AgentSettings(
            agent_llm=LOCAL_LLM,
            agent_llm_config=LOCAL_LLM_CONFIG,
            agent_type="fake",
            index=IndexSettings(
                name=index_name,
                paper_directory=str(_paper_directory(cfg)),
                manifest_file=str(_manifest_path(cfg)),
                index_directory=str(index_dir),
                use_absolute_paper_directory=False,
                recurse_subdirectories=False,
            ),
            rebuild_index=False,
        ),
    )
    settings.answer.evidence_k = 4
    settings.answer.answer_max_sources = 3
    settings.answer.evidence_skip_summary = True
    settings.answer.answer_length = "about 150 words"
    settings.answer.max_concurrent_requests = 1
    _settings_cache[name] = settings
    return settings


def _search_index(cfg: dict[str, Any]) -> SearchIndex:
    from paperqa.agents.search import SearchIndex

    index_dir, _ = _index_root(cfg)
    index_name = _validate_index_name(str(cfg["index_name"]))
    return SearchIndex(
        fields=INDEX_FIELDS,
        index_name=index_name,
        index_directory=str(index_dir),
    )


# --------------------------------------------------------------------------- #
# Manifest helpers
# --------------------------------------------------------------------------- #

def _read_manifest(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Manifesti okur; yol kaçışı ve çift kayıtları reddeder."""
    path = _manifest_path(cfg)
    base = _paper_directory(cfg).resolve()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            file_location = (row.get("file_location") or "").strip()
            if not file_location:
                continue
            relative = Path(file_location)
            if relative.is_absolute():
                raise ValueError(
                    f"Manifest {line_number}. satır: mutlak yol kullanılamaz: "
                    f"{file_location!r}"
                )
            resolved = (base / relative).resolve()
            if not resolved.is_relative_to(base):
                raise ValueError(
                    f"Manifest {line_number}. satır: proje klasörü dışına çıkan "
                    f"yol reddedildi: {file_location!r}"
                )
            if file_location in seen:
                raise ValueError(
                    f"Manifest {line_number}. satır: çift kayıt: {file_location!r}"
                )
            seen.add(file_location)
            row["file_location"] = file_location
            rows.append(row)
    return rows


def _manifest_by_location(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["file_location"]: row for row in _read_manifest(cfg)}


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) or "" for field in MANIFEST_FIELDS})
    tmp.replace(path)


def _parse_authors(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(a).strip() for a in value if str(a).strip()]
    text = str(value).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(a).strip() for a in parsed if str(a).strip()]
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in text.split(",") if part.strip()]


def _format_authors(authors: list[str], limit: int = 6) -> str:
    if not authors:
        return ""
    shown = authors[:limit]
    if len(authors) == 1:
        return shown[0]
    if len(authors) == 2:
        return f"{shown[0]} and {shown[1]}"
    text = ", ".join(shown[:-1]) + f", and {shown[-1]}"
    if len(authors) > limit:
        text += " et al."
    return text


def _citation_for_row(file_location: str, row: dict[str, Any]) -> str:
    pieces: list[str] = []
    authors = _format_authors(_parse_authors(row.get("authors")))
    if authors:
        pieces.append(authors)
    title = (row.get("title") or "").strip()
    if title:
        pieces.append(title)
    journal = (row.get("journal") or "").strip()
    year = str(row.get("year") or "").strip()
    tail = ", ".join(part for part in (journal, year) if part)
    if tail:
        pieces.append(tail)
    if not pieces:
        pieces.append(Path(file_location).stem)
    citation = ". ".join(pieces)
    if not citation.endswith("."):
        citation += "."
    return citation


# --------------------------------------------------------------------------- #
# PDF / DOI helpers
# --------------------------------------------------------------------------- #

def _scan_pdfs(directory: Path, recurse: bool) -> list[Path]:
    if not directory.exists():
        return []
    iterator = directory.rglob("*") if recurse else directory.iterdir()
    return sorted(
        (
            path
            for path in iterator
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda p: str(p).lower(),
    )


def _doi_candidates_from_filename(name: str) -> list[str]:
    """Dosya adından olası DOI adayları üretir (kayıt numarası belirsizliği için).

    ``10.117701430343231202923.pdf`` gibi dosyalarda kayıt numarası 4, 5, ...
    haneli olabilir; adayları sırayla üretiriz ve Crossref ile doğrularız.
    """
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    match = re.match(r"^(10\.)(\d{4,9})(.*)$", stem)
    if not match:
        return []
    run, tail = match.group(2), match.group(3)
    candidates: list[str] = []
    for length in range(4, min(9, len(run)) + 1):
        rest = (run[length:] + tail).strip(" ._-")
        if not rest:
            continue
        doi = f"10.{run[:length]}/{rest}".rstrip(".,;:)]}\"'").lower()
        if doi not in candidates:
            candidates.append(doi)
    return candidates


async def _validate_doi(doi: str) -> bool:
    try:
        response = await _client().get(
            f"https://api.crossref.org/works/{quote(doi, safe='')}",
            params={"mailto": MAILTO},
        )
        return response.status_code == 200
    except Exception:  # noqa: BLE001
        return False


async def _resolve_doi_for_pdf(path: Path, probe: dict[str, Any]) -> tuple[str, bool]:
    """(doi, validasyon_yapıldı) döndürür. Önce doğrulanmış dosya adı adayı."""
    candidates = _doi_candidates_from_filename(path.name)
    validated = False
    if len(candidates) > 1:
        validated = True
        for candidate in candidates:
            if await _validate_doi(candidate):
                return candidate, validated
    probe_doi = (probe.get("doi") or "").strip().lower()
    if probe_doi:
        return probe_doi, validated
    if candidates:
        return candidates[0], validated
    return "", validated


def _pdf_probe(path: Path) -> dict[str, Any]:
    """İlk iki sayfa metni + PDF meta başlığı + DOI tahmini döndürür."""
    import pymupdf

    probe: dict[str, Any] = {"text": "", "title": "", "doi": ""}
    try:
        with pymupdf.open(str(path)) as document:
            chunks: list[str] = []
            for page_index in range(min(2, document.page_count)):
                try:
                    chunks.append(document.load_page(page_index).get_text("text") or "")
                except Exception:  # noqa: BLE001
                    continue
            probe["text"] = re.sub(r"\s+", " ", "\n".join(chunks)).strip()
            metadata = document.metadata or {}
            probe["title"] = (metadata.get("title") or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.info("PDF probe failed for %s: %s", path, exc)
    match = PDF_DOI_RE.search(probe["text"])
    if match:
        probe["doi"] = match.group(0).rstrip(".,;:)]}\"'").lower()
    return probe


# --------------------------------------------------------------------------- #
# Metadata enrichment (Crossref -> OpenAlex, no API key)
# --------------------------------------------------------------------------- #

async def _enrich_crossref(doi: str) -> Optional[dict[str, Any]]:
    try:
        response = await _client().get(
            f"https://api.crossref.org/works/{quote(doi, safe='')}",
            params={"mailto": MAILTO},
        )
        if response.status_code != 200:
            return None
        message = response.json().get("message", {})
        year = None
        for key in ("published-print", "published-online", "issued"):
            parts = (message.get(key) or {}).get("date-parts") or []
            if parts and parts[0] and parts[0][0]:
                year = parts[0][0]
                break
        authors = []
        for author in message.get("author") or []:
            name = " ".join(
                part for part in (author.get("given"), author.get("family")) if part
            ) or author.get("name")
            if name:
                authors.append(name.strip())
        return {
            "title": (message.get("title") or [None])[0],
            "journal": (message.get("container-title") or [None])[0],
            "year": year,
            "authors": authors,
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("Crossref enrichment failed for %s: %s", doi, exc)
        return None


async def _enrich_openalex(doi: str) -> Optional[dict[str, Any]]:
    try:
        response = await _client().get(
            f"https://api.openalex.org/works/doi:{quote(doi, safe='')}",
            params={"mailto": MAILTO},
        )
        if response.status_code != 200:
            return None
        work = response.json()
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        return {
            "title": work.get("title"),
            "journal": source.get("display_name"),
            "year": work.get("publication_year"),
            "authors": [
                a.get("author", {}).get("display_name")
                for a in work.get("authorships", [])
                if a.get("author", {}).get("display_name")
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("OpenAlex enrichment failed for %s: %s", doi, exc)
        return None


async def _enrich(doi: str) -> dict[str, Any]:
    meta = await _enrich_crossref(doi) if doi else None
    if not meta or not meta.get("title"):
        fallback = await _enrich_openalex(doi) if doi else None
        if fallback:
            meta = {
                key: (meta or {}).get(key) or fallback.get(key)
                for key in ("title", "journal", "year", "authors")
            }
    return meta or {}


# --------------------------------------------------------------------------- #
# Docs loading per project
# --------------------------------------------------------------------------- #

def _load_lock(name: str) -> asyncio.Lock:
    if name not in _load_locks:
        _load_locks[name] = asyncio.Lock()
    return _load_locks[name]


async def _load_docs(name: str, cfg: dict[str, Any]) -> Docs:
    from paperqa.docs import Docs

    if name in _docs_cache:
        return _docs_cache[name]
    async with _load_lock(name):
        if name in _docs_cache:
            return _docs_cache[name]
        index = _search_index(cfg)
        files = await index.index_files
        if not files:
            raise RuntimeError(
                f"{name!r} projesinin indeksi boş. Önce paperqa_build_index çağırın."
            )
        docs = Docs()
        meta_map: dict[str, dict[str, Any]] = {}
        try:
            manifest = _manifest_by_location(cfg)
        except Exception:  # noqa: BLE001
            manifest = {}
        for file_location in files:
            saved = await index.get_saved_object(file_location)
            if saved is None:
                continue
            row = manifest.get(file_location)
            if row:
                meta = {
                    "title": row.get("title") or None,
                    "authors": _parse_authors(row.get("authors")) or None,
                    "year": int(row["year"]) if str(row.get("year") or "").isdigit() else None,
                    "journal": row.get("journal") or None,
                    "doi": (row.get("doi") or "").strip().lower() or None,
                }
            else:
                meta = {}
            for dockey in saved.docs:
                meta_map[dockey] = meta
            docs.docs.update(saved.docs)
            docs.texts.extend(saved.texts)
        if not docs.texts:
            raise RuntimeError(f"{name!r} projesinin indeksi metin içermiyor.")
        _docs_cache[name] = docs
        _doc_meta[name] = meta_map
        return docs


def _page_range(name: str) -> str:
    match = re.search(r"pages\s+(\d+)(?:\s*-\s*(\d+))?", name)
    if not match:
        return ""
    if match.group(2) and match.group(2) != match.group(1):
        return f"{match.group(1)}-{match.group(2)}"
    return match.group(1)


def _text_payload(name: str, text: Any, rank: int, max_chars: int) -> dict[str, Any]:
    doc = text.doc
    meta = _doc_meta.get(name, {}).get(getattr(doc, "dockey", ""), {})
    return {
        "rank": rank,
        "pages": _page_range(text.name),
        "title": meta.get("title") or getattr(doc, "title", None),
        "authors": meta.get("authors") or getattr(doc, "authors", None),
        "year": meta.get("year") or getattr(doc, "year", None),
        "journal": meta.get("journal") or getattr(doc, "journal", None),
        "doi": meta.get("doi") or getattr(doc, "doi", None),
        "citation": getattr(doc, "citation", None),
        "text": text.text[:max_chars],
    }


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was",
    "were", "have", "has", "had", "not", "but", "can", "could", "should",
    "would", "their", "they", "them", "who", "whom", "which", "what",
    "when", "where", "why", "how", "into", "than", "then", "also", "such",
}


def _lexical_payloads(
    name: str,
    docs: Any,
    query: str,
    limit: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    """Keyword fallback for chunks the embedding index ranks poorly.

    Rare query terms get more weight than ubiquitous ones, and exact bigrams
    (e.g. ``risky behavior``) get a bonus, so table-heavy or boilerplate chunks
    do not outrank the substantive paragraph.
    """
    words = [
        token
        for token in re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]{4,}", query.lower())
        if token not in _STOPWORDS
    ]
    tokens = set(words)
    if not tokens:
        return []
    texts = list(docs.texts)
    total = max(1, len(texts))
    df = {
        token: sum(1 for text in texts if token in text.text.lower())
        for token in tokens
    }
    weights = {
        token: math.log((total + 1) / (df[token] + 1)) + 1.0
        for token in tokens
    }
    bigrams = {
        f"{words[i]} {words[i + 1]}"
        for i in range(len(words) - 1)
        if words[i] != words[i + 1]
    }
    scored: list[tuple[float, Any]] = []
    for text in texts:
        body = text.text.lower()
        score = sum(weights[token] for token in tokens if token in body)
        score += sum(3.0 for bigram in bigrams if bigram in body)
        if score < 3 or _looks_like_backmatter(text.text):
            continue
        scored.append((score, text))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    payloads: list[dict[str, Any]] = []
    for rank, (score, text) in enumerate(scored[:limit], start=1):
        payload = _text_payload(name, text, rank, max_chars)
        payload["lexical_score"] = score
        payloads.append(payload)
    return payloads


def _looks_like_references(text: str) -> bool:
    """Heuristic filter for reference-list chunks returned by semantic search."""
    head = text[:600].lower()
    year_hits = len(re.findall(r"\b(?:19|20)\d{2}\b", text))
    doi_hits = len(re.findall(r"\bdoi\b|https?://", text, flags=re.IGNORECASE))
    if "references" in head and year_hits >= 4:
        return True
    return year_hits >= 14 and doi_hits >= 2


def _looks_like_backmatter(text: str) -> bool:
    """Filter reference lists, affiliation blocks and journal boilerplate.

    Semantic search sometimes ranks author affiliations, reference lists or
    publisher footers above substantive paragraphs.  These chunks are useless
    as evidence even when lexically close to the query.
    """
    low = text.lower()
    tokens = text.split()
    numeric_ratio = sum(1 for token in tokens if any(ch.isdigit() for ch in token)) / max(1, len(tokens))
    digit_ratio = sum(1 for ch in text if ch.isdigit()) / max(1, len(text))
    if numeric_ratio >= 0.30 or digit_ratio >= 0.16:
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    short_numeric = sum(
        1 for line in lines
        if len(line.split()) <= 2 and any(ch.isdigit() for ch in line)
    )
    if lines and short_numeric / len(lines) >= 0.35:
        return True
    stats_hits = len(re.findall(r"\b(?:CFI|RMSEA|TLI|SRMR)\b|p\s*[<=]|γ\s*=|β\s*=", text, re.IGNORECASE))
    if stats_hits >= 4:
        return True
    # Correlation/mean tables: many "0.60 (0.06)"-style cells.
    if len(re.findall(r"\d+\.\d+\s*\(\s*\d+\.\d+\s*\)", text)) >= 6:
        return True
    head = low[:300]
    # Abstract/introduction/method chunks often also contain a reference block
    # at the end; keep them because the prose is still usable evidence.
    if any(marker in head for marker in ("abstract", "introduction", "methods", "results", "discussion", "conclusion")):
        return False
    if _looks_like_references(text):
        return True
    affiliation_hits = (
        low.count("department of")
        + low.count("university")
        + low.count("faculty of")
    )
    contact_hits = low.count("@") + low.count("corresponding author") + low.count("e-mail")
    if affiliation_hits >= 5 or (affiliation_hits >= 3 and contact_hits >= 1):
        return True
    year_hits = len(re.findall(r"\b(?:19|20)\d{2}\b", text))
    doi_hits = len(re.findall(r"\bdoi\b|https?://", text, flags=re.IGNORECASE))
    if year_hits >= 15:
        return True
    if year_hits >= 8 and doi_hits >= 10:
        return True
    if year_hits >= 8 and doi_hits >= 3:
        return True
    return False


# --------------------------------------------------------------------------- #
# Tools: proje kaydı
# --------------------------------------------------------------------------- #

@mcp.tool()
async def paperqa_create_workspace(
    project_directory: str,
    name: str | None = None,
) -> dict[str, Any]:
    """Proje kökünde 00–03 iş akışı klasörlerini açar; henüz akış/proje kaydı seçmez.

    Var olan dosyaları silmez veya taşımaz. Akış 2 ve 3 için PDF klasörlerini,
    workflow'a göre ayrılmış manifestler ve indeksler için iç klasörleri açar.
    """
    root = Path(project_directory).expanduser().resolve()
    name = (name or "").strip()
    if not name:
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("._-")[:61]
        if len(name) < 2:
            name = "literature-project"
    if not PROJECT_NAME_RE.match(name):
        raise ValueError(
            "Proje adı 2-61 karakter olmalı ve yalnızca harf, rakam, '.', '_', '-' içermelidir."
        )
    paths = {
        "topic_discovery": root / "00_konu_basligi_kesfi",
        "source_discovery": root / "01_kaynak_kesfi",
        "draft": root / "02_bolum_taslagi",
        "draft_fulltext": root / "02_bolum_taslagi" / "fulltext",
        "draft_text": root / "02_bolum_taslagi" / "taslak",
        "draft_audit": root / "03_taslak_denetimi",
        "audit_fulltext": root / "03_taslak_denetimi" / "fulltext",
        "audit_text": root / "03_taslak_denetimi" / "taslak",
        "internal": root / ".literature-mcp",
        "indexes": root / ".literature-mcp" / "indexes",
        "manifests": root / ".literature-mcp" / "projects",
    }
    created: dict[str, bool] = {}
    root.mkdir(parents=True, exist_ok=True)
    for key, path in paths.items():
        created[key] = not path.exists()
        path.mkdir(parents=True, exist_ok=True)

    def scoped_name(suffix: str) -> str:
        tail = f"-{suffix}"
        return f"{name[:61 - len(tail)].rstrip('._-')}{tail}"

    return {
        "project_name": name,
        "project_directory": str(root),
        "next_step": "Kullanıcıya 0–3 arasındaki iş akışlarından hangisini istediğini sor; seçim gelmeden devam etme.",
        "workflow_choices": [
            "0 — Konu, çalışma başlığı ve amaç keşfi",
            "1 — Kaynak keşfi ve PDF listesi",
            "2 — PDF'lerden sayfa doğrulamalı bölüm taslağı",
            "3 — Mevcut taslağı PDF kanıtlarıyla denetleme",
        ],
        "workflow_directories": {
            "0_topic_discovery": str(paths["topic_discovery"]),
            "1_source_discovery": str(paths["source_discovery"]),
            "2_draft": str(paths["draft"]),
            "3_draft_audit": str(paths["draft_audit"]),
        },
        "fulltext_directories": {
            "draft": str(paths["draft_fulltext"]),
            "audit": str(paths["audit_fulltext"]),
        },
        "draft_directories": {
            "draft": str(paths["draft_text"]),
            "audit": str(paths["audit_text"]),
        },
        "workflow_project_names": {
            "draft": scoped_name("draft"),
            "audit": scoped_name("audit"),
        },
        "internal_directory": str(paths["internal"]),
        "created": created,
        "registered": False,
    }


@mcp.tool()
async def paperqa_projects() -> dict[str, Any]:
    """Kayıtlı projeleri durumlarıyla listeler (izole PDF klasörü + manifest + indeks)."""
    registry = _load_registry()
    projects = [
        _project_summary(name, cfg)
        for name, cfg in sorted((registry.get("projects") or {}).items())
    ]
    return {
        "registry": str(REGISTRY_PATH),
        "count": len(projects),
        "projects": projects,
        "notes": [
            "Her proje kendi manifesti ve indeksiyle izole çalışır.",
            "paperqa_search/read_pages/ask çağrılarında project adı zorunludur.",
        ],
    }


@mcp.tool()
async def paperqa_register_project(
    name: str,
    paper_directory: str,
    output_directory: str,
    title: str | None = None,
    description: str | None = None,
    include_subdirectories: bool = False,
    include_files_without_doi: bool = False,
    refresh_manifest: bool = False,
    enrich_metadata: bool = True,
    index_directory: str | None = None,
    index_name: str | None = None,
) -> dict[str, Any]:
    """Bir PDF klasörünü izole proje olarak kaydeder ve manifest CSV üretir.

    - DOI, dosya adından (``10.1007s...pdf`` gibi) veya ilk iki sayfadan algılanır.
    - Metadata Crossref (yedek: OpenAlex) ile zenginleştirilir; API anahtarı gerekmez.
    - Mevcut manifest ``refresh_manifest=True`` verilmedikçe korunur.
    - Kayıtlı bir projenin klasörü veya alt klasör taraması değiştirilecekse
      ``refresh_manifest=True`` zorunludur; aksi hâlde eski manifest yeni
      klasörle karışır.
    - DOI'si olmayan dosyalar varsayılan olarak manifeste alınmaz
      (``include_files_without_doi=True`` ile dahil edilir).
    - Aynı DOI'ye çözülen ikinci dosya manifeste alınmaz; ``skipped_duplicate_doi``
      alanında raporlanır.
    - Kullanıcının proje klasörü ``output_directory`` olarak zorunludur.
      Ana çıktılar burada, yeni manifest ve indeks ise buradaki
      ``.literature-mcp/`` alt klasöründe tutulur.
    - İndeks kurmak ayrı bir adımdır: ``paperqa_build_index``.
    """
    name = (name or "").strip()
    if not PROJECT_NAME_RE.match(name):
        raise ValueError(
            "Proje adı 2-61 karakter olmalı ve yalnızca harf, rakam, '.', '_', '-' içermelidir."
        )
    directory = Path(paper_directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"Klasör bulunamadı: {directory}")
    registry = _load_registry(force=True)
    projects = registry.setdefault("projects", {})
    existing = projects.get(name) or {}
    project_root = Path(output_directory).expanduser().resolve()
    registered_output = existing.get("output_directory")
    if registered_output and Path(registered_output).expanduser().resolve() != project_root:
        raise ValueError(
            f"{name!r} projesi farklı bir output_directory ile kayıtlı. "
            "Kayıtlı proje klasörünü kullanın; başka bir klasör için yeni proje adı açın."
        )
    project_root.mkdir(parents=True, exist_ok=True)

    pdfs = _scan_pdfs(directory, include_subdirectories)
    if not pdfs:
        raise ValueError(f"Klasörde PDF yok: {directory}")
    existing_directory = (
        Path(existing["paper_directory"]).expanduser().resolve()
        if existing.get("paper_directory")
        else None
    )
    existing_recurse = bool(existing.get("include_subdirectories", False))
    if (
        existing
        and not refresh_manifest
        and (
            existing_directory != directory
            or existing_recurse != bool(include_subdirectories)
        )
    ):
        raise ValueError(
            f"{name!r} projesi farklı bir klasör/tarama ayarıyla kayıtlı. "
            "Yeni klasör için yeni proje adı kullanın veya "
            "refresh_manifest=True verin."
        )
    manifest = (
        Path(existing["manifest"]).expanduser()
        if existing.get("manifest")
        else project_root / ".literature-mcp" / "projects" / name / "manifest.csv"
    )
    build_manifest = refresh_manifest or not existing.get("manifest") or not manifest.exists()

    rows: list[dict[str, Any]] = []
    skipped_no_doi: list[str] = []
    skipped_duplicate_doi: list[dict[str, str]] = []
    seen_dois: dict[str, str] = {}
    if build_manifest:
        for path in pdfs:
            rel = path.relative_to(directory).as_posix()
            probe = await asyncio.to_thread(_pdf_probe, path)
            doi, _validated = await _resolve_doi_for_pdf(path, probe)
            if not doi and not include_files_without_doi:
                skipped_no_doi.append(rel)
                continue
            doi_key = doi.strip().lower()
            if doi_key and doi_key in seen_dois:
                skipped_duplicate_doi.append(
                    {"file": rel, "doi": doi, "kept": seen_dois[doi_key]}
                )
                continue
            if doi_key:
                seen_dois[doi_key] = rel
            row = {
                "file_location": rel,
                "doi": doi,
                "title": probe.get("title") or path.stem,
                "journal": "",
                "year": "",
                "authors": "",
            }
            if doi and enrich_metadata:
                meta = await _enrich(doi)
                for key in ("title", "journal", "year", "authors"):
                    value = meta.get(key)
                    if key == "authors":
                        row[key] = json.dumps(value, ensure_ascii=False) if value else ""
                    elif value:
                        row[key] = value
            rows.append(row)
        _write_manifest(manifest, rows)
    else:
        rows = _read_manifest(existing)

    entry = {
        **(existing or {}),
        "title": title or existing.get("title") or name,
        "description": description or existing.get("description") or "",
        "paper_directory": str(directory),
        "include_subdirectories": bool(include_subdirectories),
        "manifest": str(manifest),
        "index_directory": str(
            Path(index_directory).expanduser()
            if index_directory
            else existing.get("index_directory")
            or project_root / ".literature-mcp" / "indexes"
        ),
        "index_name": _validate_index_name(
            index_name or existing.get("index_name") or name
        ),
        "output_directory": str(
            project_root
        ),
        "analysis_json": existing.get("analysis_json"),
        "created_at": existing.get("created_at") or _now(),
        "updated_at": _now(),
    }
    proposed_index_dir = Path(entry["index_directory"]).expanduser().resolve()
    proposed_root = (proposed_index_dir / entry["index_name"]).resolve()
    for other_name, other in projects.items():
        if other_name == name:
            continue
        other_index_dir = other.get("index_directory")
        other_index_name = other.get("index_name")
        if not other_index_dir or not other_index_name:
            continue
        other_root = (
            Path(other_index_dir).expanduser().resolve() / other_index_name
        ).resolve()
        if (
            proposed_root == other_root
            or proposed_root.is_relative_to(other_root)
            or other_root.is_relative_to(proposed_root)
        ):
            raise ValueError(
                f"İndeks yolu çakışması: {other_name!r} projesinin indeksi "
                f"({other_root}) ile yeni projenin indeksi ({proposed_root}) "
                "aynı veya iç içe. Her proje için ayrı index_directory ve "
                "index_name kullanın."
            )
    projects[name] = entry
    _save_registry(registry)
    _invalidate_project_cache(name)

    return {
        "registered": name,
        "paper_directory": str(directory),
        "output_directory": entry["output_directory"],
        "pdf_files": len(pdfs),
        "manifest": str(manifest),
        "manifest_built": build_manifest,
        "manifest_rows": len(rows),
        "skipped_no_doi": skipped_no_doi,
        "skipped_duplicate_doi": skipped_duplicate_doi,
        "index": {
            "index_name": entry["index_name"],
            "index_directory": entry["index_directory"],
            "next_step": f"paperqa_build_index(project='{name}')",
        },
        "notes": [
            "Her proje ayrı manifest ve ayrı indeks kullanır; projeler karışmaz.",
            "Çıktılar varsayılan olarak proje klasörüne yazılır.",
            "DOI'si olmayan dosyalar varsayılan olarak dışarıda bırakıldı.",
            "Aynı DOI'ye çözülen yinelenen dosyalar manifeste alınmadı.",
        ],
    }


@mcp.tool()
async def paperqa_build_index(project: str, rebuild: bool = False) -> dict[str, Any]:
    """Projenin indeksini manifest üyeliğine göre kurar/günceller.

    - İndekse yalnızca manifestteki dosyalar girer (klasör taraması değil).
    - ``rebuild=True`` proje indeks klasörünü önce yedeğe taşır; kurulum
      başarısız olursa eski indeks geri getirilir.
    - Diğer projelerin indekslerine dokunulmaz.
    """
    from paperqa.docs import Docs

    name = (project or "").strip()
    cfg = _project_config(name)
    directory = _paper_directory(cfg)
    if not directory.is_dir():
        raise ValueError(f"Proje klasörü yok: {directory}")
    rows = _read_manifest(cfg)
    if not rows:
        raise ValueError(f"{name!r} manifesti boş: {_manifest_path(cfg)}")

    _, index_root = _index_root(cfg)

    backup: Path | None = None
    backup_kept = False
    if rebuild and index_root.exists():
        backup = _backup_index_root(index_root)
        logger.info("Index rebuild: %s -> %s", index_root, backup)

    try:
        settings = _settings_for(name, cfg)
        index = _search_index(cfg)
        existing = dict(await index.index_files)
        target = {row["file_location"] for row in rows}

        removed: list[str] = []
        for extra in sorted(set(existing) - target):
            await index.remove_from_index(extra)
            removed.append(extra)

        added: list[str] = []
        unchanged: list[str] = []
        missing: list[str] = []
        failed: list[dict[str, str]] = []
        for row in rows:
            rel = row["file_location"]
            path = directory / rel
            if not path.is_file():
                missing.append(rel)
                continue
            if await index.filecheck(rel):
                unchanged.append(rel)
                continue
            try:
                tmp_docs = Docs()
                await tmp_docs.aadd(
                    path=path,
                    citation=_citation_for_row(rel, row),
                    settings=settings,
                    file_location=rel,
                )
                body = "".join(t.text for t in tmp_docs.texts)
                await index.add_document(
                    {
                        "title": row.get("title") or Path(rel).name,
                        "year": str(row.get("year") or "Unknown year"),
                        "file_location": rel,
                        "body": body,
                    },
                    document=tmp_docs,
                )
                added.append(rel)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Index build failed for %s", rel)
                failed.append({"file": rel, "error": str(exc)})
                await index.mark_failed_document(rel)

        if index.changed:
            await index.save_index()
    except Exception:
        logger.exception("Index build failed for project %s", name)
        if backup is not None:
            shutil.rmtree(index_root, ignore_errors=True)
            backup.rename(index_root)
            logger.info("Index rebuild failed; previous index restored: %s", index_root)
        raise
    else:
        backup_kept = backup is not None and bool(failed or missing)
        if backup is not None and not backup_kept:
            shutil.rmtree(backup, ignore_errors=True)
        elif backup is not None:
            logger.warning(
                "Index rebuild kept previous index backup due to failures: %s",
                backup,
            )

    _invalidate_project_cache(name)

    return {
        "project": name,
        "index_name": cfg["index_name"],
        "index_directory": str(index_root),
        "rebuilt": rebuild,
        "manifest_rows": len(rows),
        "added": added,
        "unchanged": unchanged,
        "removed_not_in_manifest": removed,
        "missing_files": missing,
        "failed": failed,
        "previous_index_backup": str(backup) if backup_kept else None,
        "indexed_files_total": len(await index.index_files),
        "notes": [
            "İndeks üyeliği manifest ile sabitlendi; klasördeki fazladan PDF'ler alınmaz.",
            "Arama/okuma araçları yalnızca bu projenin indeksini görür.",
        ],
    }


# --------------------------------------------------------------------------- #
# Tools: durum / arama / okuma / soru
# --------------------------------------------------------------------------- #

@mcp.tool()
async def paperqa_status(project: str) -> dict[str, Any]:
    """Bir projenin indeks durumunu (dosya, doküman, metin parçası) döndürür.

    Manifest ile indeks arasındaki uyuşmazlıkları da raporlar: indekste eksik
    dosyalar ve manifestte olmayan indeks kayıtları.
    """
    name = (project or "").strip()
    cfg = _project_config(name)
    _, index_root = _index_root(cfg)
    index = _search_index(cfg)
    files = set(await index.index_files)
    documents = 0
    chunks = 0
    docs_error: str | None = None
    try:
        docs = await _load_docs(name, cfg)
        documents = len(docs.docs)
        chunks = len(docs.texts)
    except Exception as exc:  # noqa: BLE001
        docs_error = f"{type(exc).__name__}: {exc}"

    manifest_rows: int | None = None
    missing_from_index: list[str] = []
    index_only_files: list[str] = []
    manifest_error: str | None = None
    try:
        rows = _read_manifest(cfg)
        manifest_rows = len(rows)
        manifest_files = {row["file_location"] for row in rows}
        missing_from_index = sorted(manifest_files - files)
        index_only_files = sorted(files - manifest_files)
    except FileNotFoundError:
        manifest_error = "manifest bulunamadı"
    except Exception as exc:  # noqa: BLE001
        manifest_error = f"{type(exc).__name__}: {exc}"

    result: dict[str, Any] = {
        "project": name,
        "index_name": cfg["index_name"],
        "index_directory": str(index_root),
        "paper_directory": cfg["paper_directory"],
        "manifest": cfg["manifest"],
        "manifest_rows": manifest_rows,
        "indexed_files": len(files),
        "documents": documents,
        "text_chunks": chunks,
        "embedding": EMBEDDING,
        "llm": LOCAL_LLM,
        "llm_backend": LOCAL_BACKEND,
        "llm_model": LOCAL_MODEL,
        "llm_api_base": LOCAL_API_BASE,
        "files": sorted(files),
        "missing_from_index": missing_from_index,
        "index_only_files": index_only_files,
        "healthy": (
            docs_error is None
            and manifest_error is None
            and not missing_from_index
            and not index_only_files
        ),
    }
    if docs_error:
        result["docs_error"] = docs_error
    if manifest_error:
        result["manifest_error"] = manifest_error
    return result


@mcp.tool()
async def paperqa_llm_status(timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Yerel llama.cpp sunucusunun erişilebilirliğini ve yüklü modelleri döndürür.

    Sunucuyu **başlatmaz**; yalnızca durumu raporlar. ``paperqa_ask`` çağrısı
    sunucu kapalıysa otomatik başlatır. llama.cpp'nin ``/v1/models`` uç noktası
    sorgulanır.
    """
    try:
        timeout = max(1.0, min(float(timeout_seconds), 30.0))
    except (TypeError, ValueError):
        timeout = 5.0
    info: dict[str, Any] = {
        "backend": LOCAL_BACKEND,
        "model": LOCAL_MODEL,
        "litellm_model": LOCAL_LLM,
        "api_base": LOCAL_API_BASE,
        "max_tokens": LOCAL_MAX_TOKENS,
        "temperature": LOCAL_TEMPERATURE,
        "auto_start": AUTO_START_LLAMA,
        "auto_stop_idle_seconds": AUTO_STOP_IDLE,
        "managed": False,
        "reachable": False,
        "model_available": False,
    }
    managed_pid = 0
    if _llama_process is not None and _llama_process.returncode is None:
        managed_pid = _llama_process.pid
    elif _llama_started_by_us:
        data = _read_pidfile()
        try:
            pid = int(data.get("pid") or 0) if data else 0
        except (TypeError, ValueError):
            pid = 0
        if pid and _pid_alive(pid) and _pid_is_llama(pid):
            managed_pid = pid
    if managed_pid and _llama_started_by_us:
        info["managed"] = True
        info["managed_pid"] = managed_pid
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{LOCAL_API_BASE}/models")
            response.raise_for_status()
            models = [
                item.get("id")
                for item in response.json().get("data", [])
                if item.get("id")
            ]
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
        if AUTO_START_LLAMA:
            info["hint"] = (
                "paperqa_ask çağrıldığında otomatik başlatılır; elle başlatmak "
                "için bash scripts/start_llamacpp.sh qwen (veya "
                "PAPERQA_LOCAL_API_BASE'i kontrol edin)."
            )
        else:
            info["hint"] = (
                "llama-server'ı başlatın: bash scripts/start_llamacpp.sh "
                "(veya PAPERQA_LOCAL_API_BASE'i kontrol edin)."
            )
        return info
    info["reachable"] = True
    info["models"] = sorted(models)
    info["model_available"] = any(
        name == LOCAL_MODEL
        or name.startswith(f"{LOCAL_MODEL}:")
        or name.startswith(f"{LOCAL_MODEL}/")
        for name in models
    )
    return info


@mcp.tool()
async def paperqa_search(
    project: str,
    query: str,
    k: int = 6,
    max_chars: int = 1600,
) -> dict[str, Any]:
    """Proje içinde semantik arama (yalnızca o projenin indeksi; LLM çağrılmaz).

    Kanıt ve sayfa aralığı bulmak için kullanın; önemli alıntıları
    ``paperqa_read_pages`` ile doğrulayın.
    """
    name = (project or "").strip()
    cfg = _project_config(name)
    query = (query or "").strip()
    if not query:
        raise ValueError("query must not be empty")
    try:
        k = max(1, min(int(k), 20))
        max_chars = max(300, min(int(max_chars), 6000))
    except (TypeError, ValueError) as exc:
        raise ValueError("k ve max_chars tam sayı olmalıdır.") from exc
    docs = await _load_docs(name, cfg)
    settings = _settings_for(name, cfg)
    fetch_k = min(max(k * 4, 12), 40)
    matches = await docs.retrieve_texts(query, k=fetch_k, settings=settings)
    filtered = [match for match in matches if not _looks_like_backmatter(match.text)]
    matches = (filtered or matches)[:k]
    return {
        "project": name,
        "query": query,
        "k": k,
        "results": [
            _text_payload(name, match, rank, max_chars)
            for rank, match in enumerate(matches, start=1)
        ],
    }


@mcp.tool()
async def paperqa_read_pages(
    project: str,
    doi: str,
    page_start: int = 1,
    page_end: int | None = None,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Projedeki bir PDF'ten sayfa metni okur (DOI → manifest eşlemesi).

    Sayfa numaraları 1 tabanlıdır. ``paperqa_search`` sonucundaki alıntıları
    bu araçla doğrulayın. DOI başka bir projede olsa bile burada bulunmaz.
    Tek çağrıda en fazla 50 sayfa okunur.
    """
    import pymupdf

    name = (project or "").strip()
    cfg = _project_config(name)
    doi = (
        (doi or "")
        .strip()
        .lower()
        .removeprefix("https://doi.org/")
        .removeprefix("http://doi.org/")
        .removeprefix("doi:")
    )
    try:
        page_start = int(page_start)
        page_end = int(page_end) if page_end is not None else None
        max_chars = max(300, min(int(max_chars), 20000))
    except (TypeError, ValueError) as exc:
        raise ValueError("page_start, page_end ve max_chars tam sayı olmalıdır.") from exc
    if page_start < 1:
        raise ValueError("page_start 1 veya daha büyük olmalıdır.")
    if page_end is not None and page_end < page_start:
        raise ValueError("page_end, page_start'tan küçük olamaz.")
    mapping: dict[str, Path] = {}
    base = _paper_directory(cfg).resolve()
    for row in _read_manifest(cfg):
        row_doi = (row.get("doi") or "").strip().lower()
        if not row_doi:
            continue
        if row_doi in mapping:
            raise ValueError(
                f"Manifestte {row_doi!r} DOI'si birden fazla dosyaya eşlenmiş; "
                "paperqa_read_pages için DOI benzersiz olmalıdır."
            )
        mapping[row_doi] = base / row["file_location"]
    path = mapping.get(doi)
    if path is None:
        raise ValueError(
            f"{name!r} projesinde {doi!r} DOI'sine eşlenmiş PDF yok. "
            "Manifeste eklemek için paperqa_register_project kullanın."
        )
    path = path.resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"PDF yolu proje klasörü dışında: {path}")
    if not path.exists():
        raise FileNotFoundError(str(path))
    with pymupdf.open(path) as pdf:
        page_count = pdf.page_count
        if page_start > page_count:
            raise ValueError(
                f"page_start ({page_start}) PDF sayfa sayısının ({page_count}) üstünde."
            )
        start = page_start
        end = min(page_count, page_end or page_count)
        if end - start + 1 > MAX_PAGES_PER_READ:
            raise ValueError(
                f"Tek çağrıda en fazla {MAX_PAGES_PER_READ} sayfa okunabilir; "
                "page_end değerini küçültün."
            )
        pages = []
        for page_number in range(start, end + 1):
            page = pdf.load_page(page_number - 1)
            blocks = page.get_text("blocks", sort=True)
            text = "\n".join(
                block[4] for block in blocks if len(block) > 4 and block[4].strip()
            )
            text = re.sub(r"[ \t]+", " ", text).strip()
            pages.append({"page": page_number, "text": text[:max_chars]})
    return {
        "project": name,
        "doi": doi,
        "path": str(path),
        "page_count": page_count,
        "page_range": [start, end],
        "pages": pages,
    }


@mcp.tool()
async def paperqa_ask(
    project: str,
    question: str,
    evidence_k: int = 3,
    max_sources: int = 3,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """Proje indeksi üzerinde yerel LLM'e soru sorar (taslak cevap).

    Yerel llama.cpp sunucusunu kullanır. Sunucu kapalıysa MCP onu otomatik
    başlatır ve yalnızca kendisi başlattıysa boşta kalınca durdurur
    (``PAPERQA_AUTO_START`` / ``PAPERQA_AUTO_STOP_IDLE``). CPU'da yavaştır ve
    küçük modeller atıf hatası yapabilir. Cevabı taslak kabul edin; kaynak
    cümlelerini aynen kopyalamak yerine bulguları paragraf bağlamına uygun
    özgün ifadelerle yazın. Her iddiayı ``paperqa_search`` veya
    ``paperqa_read_pages`` ile doğrulayın. Araç, bu yazım biçimini garanti etmez.
    """
    global _llama_active_asks
    name = (project or "").strip()
    cfg = _project_config(name)
    question = (question or "").strip()
    if not question:
        raise ValueError("question must not be empty")
    try:
        evidence_k = max(1, min(int(evidence_k), 8))
        max_sources = max(1, min(int(max_sources), 5))
        timeout = max(30, min(int(timeout_seconds), 600))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "evidence_k, max_sources ve timeout_seconds tam sayı olmalıdır."
        ) from exc
    status = await _ensure_llama_server()
    if not status.get("reachable") or not status.get("model_available"):
        result = {
            "project": name,
            "question": question,
            "error": "local llama.cpp server unavailable",
            "hint": (
                "paperqa_ask sunucuyu otomatik başlatamadı; "
                "bash scripts/start_llamacpp.sh qwen"
            ),
            "llm_status": status,
        }
        if status.get("error"):
            result["detail"] = status["error"]
        return result

    _llama_active_asks += 1
    try:
        docs = await _load_docs(name, cfg)
        settings = copy.deepcopy(_settings_for(name, cfg))
        settings.answer.evidence_k = evidence_k
        settings.answer.answer_max_sources = max_sources
        settings.answer.evidence_skip_summary = True
        settings.answer.max_concurrent_requests = 1

        async def run() -> Any:
            return await docs.aquery(question, settings=settings)

        try:
            session = await asyncio.wait_for(run(), timeout=timeout)
        except TimeoutError:
            return {
                "project": name,
                "question": question,
                "error": "local model timed out",
                "timeout_seconds": timeout,
            }
        return {
            "project": name,
            "question": question,
            "answer": session.answer,
            "contexts": [
                {
                    "pages": _page_range(context.text.name),
                    "doi": getattr(context.text.doc, "doi", None),
                    "title": getattr(context.text.doc, "title", None),
                    "text": context.context[:1600],
                }
                for context in session.contexts
            ],
            "warning": (
                "Local model answer; verify every claim against paperqa_search "
                "or paperqa_read_pages."
            ),
        }
    finally:
        _llama_active_asks = max(0, _llama_active_asks - 1)
        _touch_llama()


if __name__ == "__main__":
    mcp.run()
