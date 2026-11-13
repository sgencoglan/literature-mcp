"""Modelin kendi web aracıyla yürüteceği yayıncıdan bağımsız keşif planı.

Bu modül tarayıcı veya arama sağlayıcısı çalıştırmaz. Plan hazırlama ile
gerçekte yapılmış aramaların kaydını birbirinden ayırır.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

PLATFORMS = {
    "cochrane": {
        "label": "Cochrane Library / Cochrane",
        "domains": ["cochranelibrary.com", "cochrane.org"],
    },
    "pubmed": {"label": "PubMed", "domains": ["pubmed.ncbi.nlm.nih.gov"]},
    "guidelines": {"label": "NICE / WHO", "domains": ["nice.org.uk", "who.int"]},
    "sciencedirect": {"label": "ScienceDirect", "domains": ["sciencedirect.com"]},
    "taylor_francis": {
        "label": "Taylor & Francis / Routledge",
        "domains": ["tandfonline.com", "taylorfrancis.com"],
    },
    "springer_nature": {"label": "Springer Nature", "domains": ["link.springer.com", "nature.com"]},
    "wiley": {"label": "Wiley", "domains": ["onlinelibrary.wiley.com"]},
    "sage": {"label": "SAGE", "domains": ["journals.sagepub.com"]},
    "apa": {"label": "APA PsycNet", "domains": ["psycnet.apa.org"]},
    "cambridge": {"label": "Cambridge Core", "domains": ["cambridge.org"]},
    "oxford": {"label": "Oxford Academic", "domains": ["academic.oup.com"]},
    "bmj": {"label": "BMJ", "domains": ["bmj.com"]},
    "jama": {"label": "JAMA Network", "domains": ["jamanetwork.com"]},
    "psychiatryonline": {"label": "PsychiatryOnline", "domains": ["psychiatryonline.org"]},
    "ovid_lww": {"label": "Ovid / LWW", "domains": ["journals.lww.com", "ovid.com"]},
}
SEARCH_INSTRUCTIONS = [
    "Hız hedefi yoktur: kaynak kapsamı tamamlanmadan işi bitmiş sayma. Aynı sağlayıcıda sıralı, bağımsız API sağlayıcılarında en fazla iki eşzamanlı arama yürüt.",
    "site: sorgularının farklı hedef alan adları aynı web arama sağlayıcısının kotasını paylaşır. Üç sorguluk küçük partilerden sonra checkpoint kaydet.",
    "429/Retry-After geldiğinde bildirilen süreden önce yeniden deneme. Beklerken bağımsız sağlayıcıda ilerle; bekleyen görevi atlanmış veya tamamlanmış sayma.",
    "Konu ve bağlamdan İngilizce terimleri, eş anlamlıları ve farklı adlandırmaları çıkar; query_variants olarak ver.",
    "Önce site filtresiz sorguları, sonra platform görevlerini bağlı web aracıyla gerçekten çalıştır. Bir sorgunun bitmesi bütün platformun tarandığı anlamına gelmez.",
    "Bu araç arama yapmaz. Host web aracı yoksa sorguları not_run bırak; kullanıcıya bağlantı sun.",
    "Normal web araması sonucunu Google Scholar araması olarak etiketleme; engine alanına gerçek servisi yaz.",
    "Atıf sayısı, Q1/Q2, tarih, yayıncı veya yayın türü nedeniyle keşif aşamasında erken eleme yapma; kitap/bölüm, yeni ve düşük atıflı yayınları koru.",
    "Temel derlemelerin kaynakçalarını ve bilinen yayınlara atıf yapan çalışmaları takip et; alternatif sorguları sonuçlara göre genişlet.",
    "Bulunan kaynağın asıl sayfasını erişilebildiği ölçüde kontrol et. Yalnızca arama özetini gördüysen read_level=snippet yaz; abstract veya fulltext okundu deme.",
    "Başlık, URL, DOI/PMID, yıl ve okuma düzeyini kaydet. Eksik metadata uydurma. Site eşleşmesi indeks veya kalite doğrulaması değildir.",
    "Bilinen önemli yayınları bağımsız kontrol listesiyle karşılaştır. Eksik kaynakları, engelleri ve çalıştırılmamış görevleri açıkça sun; eksiksizlik garantisi verme.",
]


def prepare_platform_search(
    topic: str,
    query_variants: list[str] | None = None,
    platforms: list[str] | None = None,
    exact_title: bool = False,
) -> dict[str, Any]:
    topic = str(topic or "").strip()
    if not topic or len(topic) > 1000:
        raise ValueError("topic boş olmamalı ve 1000 karakteri geçmemeli")
    selected = list(PLATFORMS) if platforms is None else list(dict.fromkeys(platforms))
    if any(p not in PLATFORMS for p in selected):
        raise ValueError("Bilinmeyen platform")
    terms = []
    for query in [topic, *(query_variants or [])]:
        query = re.sub(r"\s+", " ", str(query)).strip()
        if query and query.casefold() not in {t.casefold() for t in terms}:
            terms.append(query)
    if len(terms) > 5 or any(len(t) > 1000 for t in terms):
        raise ValueError("En fazla 5 sorgu varyantı ve her biri en fazla 1000 karakter olmalı")
    if exact_title:
        terms = ['"' + t.replace('"', " ") + '"' for t in terms]
    tasks = []

    def add(query: str, platform: str | None, domain: str | None) -> None:
        tasks.append(
            {
                "id": f"Q{len(tasks) + 1}",
                "query": query,
                "platform": platform,
                "domain": domain,
                "status": "not_run",
                "executor": "model_host_web_search",
                "rate_limit_group": "host_web_search",
                "web_url": "https://www.google.com/search?" + urlencode({"q": query}),
                "scholar_url": "https://scholar.google.com/scholar?" + urlencode({"q": query}),
            }
        )

    for term in terms:
        add(term, None, None)
    for platform in selected:
        for domain in PLATFORMS[platform]["domains"]:
            for term in terms:
                add(f"site:{domain} {term}", platform, domain)
    return {
        "schema": "platform-search/1",
        "topic": topic,
        "objective": "minimize_missed_relevant_publications",
        "execution": "model_host_tools",
        "tasks": tasks,
        "platforms": {p: PLATFORMS[p] for p in selected},
        "instructions": SEARCH_INSTRUCTIONS,
        "early_exclusion_filters": [],
        "pacing": {
            "mode": "coverage_first",
            "batch_size": 3,
            "max_parallel_per_provider": 1,
            "max_parallel_independent_providers": 2,
            "respect_retry_after": True,
            "checkpoint_after_each_batch": True,
            "elapsed_time_completes_search": False,
        },
        "completeness": "not_established",
    }


def _valid_url(url: Any) -> bool:
    try:
        parts = urlsplit(str(url or ""))
        return (
            parts.scheme in {"http", "https"}
            and bool(parts.hostname)
            and not parts.username
            and not parts.password
        )
    except ValueError:
        return False


def collect_platform_results(plan: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    if plan.get("schema") != "platform-search/1":
        raise ValueError("platform-search/1 planı gerekli")
    tasks = {t["id"]: t for t in plan["tasks"]}
    history: dict[str, list[dict[str, Any]]] = {}
    records: dict[tuple[str, str], dict[str, Any]] = {}
    retry_until: dict[str, datetime] = {}
    warnings = []
    for run in runs:
        task_id = run.get("task_id")
        if task_id not in tasks:
            raise ValueError("Arama kaydı plan içindeki task_id değerini kullanmalı")
        status = run.get("status")
        if status not in {"ok", "partial", "error", "rate_limited", "unavailable"}:
            raise ValueError("Geçersiz arama durumu")
        if not run.get("engine") or not run.get("searched_at"):
            raise ValueError("Gerçek arama servisi ve searched_at gerekli")
        searched_at = datetime.fromisoformat(str(run["searched_at"]).replace("Z", "+00:00"))
        if searched_at.tzinfo is None:
            searched_at = searched_at.replace(tzinfo=timezone.utc)
        if status in {"error", "rate_limited"}:
            delay = run.get("retry_after_seconds")
            if delay is None:
                delay = 60.0 if status == "rate_limited" else 30.0
            if not isinstance(delay, (int, float)) or isinstance(delay, bool) or not math.isfinite(delay) or delay < 0:
                raise ValueError("retry_after_seconds negatif olmayan sayı olmalı")
            group = tasks[task_id].get("rate_limit_group", "host_web_search")
            until = searched_at + timedelta(seconds=delay)
            retry_until[group] = max(retry_until.get(group, until), until)
        hits = run.get("results") or []
        if not isinstance(hits, list):
            raise ValueError("results liste olmalı")
        if status not in {"ok", "partial"} and hits:
            raise ValueError("Başarısız arama sonuç içeremez; kısmi sonuç için partial kullan")
        task = tasks[task_id]
        saved_run = {k: run.get(k) for k in ("task_id", "status", "engine", "searched_at", "note")}
        saved_run["query"] = task["query"]
        saved_run["retry_after_seconds"] = run.get("retry_after_seconds")
        saved_run["result_count"] = len(hits)
        history.setdefault(task_id, []).append(saved_run)
        for hit in hits:
            if (
                not isinstance(hit, dict)
                or not str(hit.get("title") or "").strip()
                or not _valid_url(hit.get("url"))
            ):
                raise ValueError("Her sonuç gerçek başlık ve http(s) URL içermeli")
            level = hit.get("read_level", "snippet")
            if level not in {"metadata", "snippet", "abstract", "fulltext"}:
                raise ValueError("Geçersiz okuma düzeyi")
            host = (urlsplit(hit["url"]).hostname or "").casefold()
            domain = task.get("domain")
            matched = domain is None or host == domain or host.endswith("." + domain)
            if not matched:
                warnings.append(
                    f"{task_id}: sonuç hedef alan adı dışında; kayıt korunarak incelemeye bırakıldı."
                )
            doi = re.sub(
                r"^https?://(?:dx\.)?doi\.org/", "", str(hit.get("doi") or ""), flags=re.I
            ).strip()
            doi = doi.casefold() if re.fullmatch(r"10\.\d{4,9}/\S+", doi) else ""
            # DOI doğrulanmış kabul edilmez. Farklı URL'leri otomatik birleştirme;
            # aynı yayının alternatif sürümlerini sonraki kapsam denetimi karşılaştırır.
            key = (hit["url"].split("#", 1)[0], " ".join(str(hit["title"]).casefold().split()))
            sighting = {
                "task_id": task_id,
                "engine": run["engine"],
                "searched_at": run["searched_at"],
                "domain_match": matched,
                "read_level": level,
                "excerpt": str(hit.get("excerpt") or ""),
            }
            if key in records:
                records[key]["sightings"].append(sighting)
                continue
            records[key] = {
                "title": str(hit["title"]),
                "url": hit["url"],
                "doi": doi or None,
                "year": hit.get("year"),
                "publication_type": hit.get("publication_type") or "unknown",
                "source": "model_web_search",
                "read_level": level,
                "platforms": [
                    p
                    for p, spec in PLATFORMS.items()
                    if any(host == d or host.endswith("." + d) for d in spec["domains"])
                ],
                "abstract": str(hit.get("abstract") or "")
                if level in {"abstract", "fulltext"}
                else "",
                "model_relevance_note": str(hit.get("relevance_note") or ""),
                "quality_status": "not_assessed",
                "index_status": "not_verified",
                "sightings": [sighting],
            }
    coverage = []
    for task_id, task in tasks.items():
        attempts = history.get(task_id, [])
        statuses = [r["status"] for r in attempts]
        status = (
            "not_run"
            if not attempts
            else (
                "partial" if "ok" in statuses and any(s != "ok" for s in statuses) else statuses[-1]
            )
        )
        coverage.append({**task, "status": status, "runs": attempts})
    now = datetime.now(timezone.utc)
    pending = [t for t in coverage if t["status"] != "ok"]
    ready = [
        t["id"]
        for t in pending
        if t["status"] != "unavailable"
        and retry_until.get(t.get("rate_limit_group", "host_web_search"), now) <= now
    ]
    return {
        "schema": "platform-search-results/1",
        "topic": plan["topic"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": list(records.values()),
        "coverage": coverage,
        "warnings": warnings,
        "completeness": "not_established",
        "summary": {
            "records": len(records),
            "planned_queries": len(tasks),
            "attempted_queries": len(history),
            "queries_needing_followup": sum(t["status"] != "ok" for t in coverage),
        },
        "checkpoint": {"plan": plan, "runs": runs},
        "resume": {
            "pending_task_ids": [t["id"] for t in pending],
            "ready_task_ids": ready,
            "next_batch_task_ids": ready[: plan.get("pacing", {}).get("batch_size", 3)],
            "provider_retry_at": {
                group: until.isoformat() for group, until in retry_until.items() if until > now
            },
            "execution": "Run next-batch tasks sequentially on the shared web provider; independent API providers may run in parallel.",
        },
        "next_step": "Kayıtları build_literature_audit.py ile havuz ve bağımsız bilinen yayın listesine karşı denetle; kaynakça/ileri atıf takibini ayrıca yap.",
        "presentation_instructions": [
            "Önemli adayları neden ilgili olduklarıyla sun; başlık, yıl, kaynak bağlantısı ve okuma düzeyini göster.",
            "Kalite ve indeks bilgisi doğrulanmadıysa açıkça belirt; kaynak platformunu kalite puanı sayma.",
            "Kitap/bölüm, derleme ve özgün çalışmaları görünür tut; DOI/başlık tekrarlarını kapsam denetimine gönder.",
            "Çalıştırılmamış veya başarısız sorguları ve bilinen kaynak boşluklarını sonuç tablosundan ayrı bildir.",
        ],
    }
