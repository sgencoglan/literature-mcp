import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from sciencedirect_meta import platform_search as ps
from sciencedirect_meta import unified


class PlatformSearchTests(unittest.TestCase):
    def setUp(self):
        self.plan = ps.prepare_platform_search("example topic", platforms=["sciencedirect"])
        self.task = next(t for t in self.plan["tasks"] if t["domain"])

    def run_for(self, results=None, **updates):
        return {
            "task_id": self.task["id"],
            "engine": "host_web_search",
            "status": "ok",
            "searched_at": "2026-01-01T00:00:00Z",
            "results": results or [],
            **updates,
        }

    def test_unrestricted_queries_precede_site_queries_without_early_exclusion(self):
        plan = ps.prepare_platform_search("topic", ["alternative phrase"])
        self.assertIsNone(plan["tasks"][0]["domain"])
        self.assertIsNone(plan["tasks"][1]["domain"])
        self.assertEqual(plan["early_exclusion_filters"], [])
        self.assertTrue(all(t["status"] == "not_run" for t in plan["tasks"]))

    def test_all_requested_platforms_and_cochrane_are_present(self):
        plan = ps.prepare_platform_search("topic")
        domains = {t["domain"] for t in plan["tasks"]}
        self.assertTrue(
            {
                "cochranelibrary.com",
                "cochrane.org",
                "sciencedirect.com",
                "taylorfrancis.com",
                "tandfonline.com",
                "nature.com",
                "psycnet.apa.org",
                "journals.sagepub.com",
                "cambridge.org",
                "academic.oup.com",
                "bmj.com",
                "jamanetwork.com",
                "psychiatryonline.org",
            }.issubset(domains)
        )

    def test_exact_title_is_optional_and_query_urls_round_trip(self):
        self.assertNotIn('"', self.plan["tasks"][0]["query"])
        plan = ps.prepare_platform_search("Known title", platforms=[], exact_title=True)
        task = plan["tasks"][0]
        self.assertEqual(task["query"], '"Known title"')
        self.assertEqual(parse_qs(urlsplit(task["scholar_url"]).query)["q"][0], task["query"])

    def test_no_runs_means_not_searched(self):
        result = ps.collect_platform_results(self.plan, [])
        self.assertEqual(result["summary"]["attempted_queries"], 0)
        self.assertTrue(all(r["status"] == "not_run" for r in result["coverage"]))
        self.assertEqual(result["completeness"], "not_established")

    def test_source_and_quality_are_distinct_and_snippet_is_not_abstract(self):
        hit = {
            "title": "Example source",
            "url": "https://www.sciencedirect.com/science/article/example",
            "abstract": "Unverified text",
        }
        result = ps.collect_platform_results(self.plan, [self.run_for([hit])])
        record = result["records"][0]
        self.assertEqual(record["platforms"], ["sciencedirect"])
        self.assertEqual(record["quality_status"], "not_assessed")
        self.assertEqual(record["index_status"], "not_verified")
        self.assertEqual(record["read_level"], "snippet")
        self.assertEqual(record["abstract"], "")
        self.assertEqual(record["sightings"][0]["engine"], "host_web_search")

    def test_out_of_domain_results_are_preserved_with_warning(self):
        hit = {"title": "Potential source", "url": "https://sciencedirect.com.evil.example/article"}
        result = ps.collect_platform_results(self.plan, [self.run_for([hit])])
        self.assertEqual(len(result["records"]), 1)
        self.assertTrue(result["warnings"])
        self.assertFalse(result["records"][0]["sightings"][0]["domain_match"])

    def test_failed_query_is_not_overwritten_by_later_success(self):
        result = ps.collect_platform_results(
            self.plan, [self.run_for(status="error"), self.run_for()]
        )
        task = next(t for t in result["coverage"] if t["id"] == self.task["id"])
        self.assertEqual(task["status"], "partial")
        self.assertEqual(len(task["runs"]), 2)

    def test_repeated_url_preserves_search_provenance(self):
        hit = {"title": "Source", "url": "https://www.sciencedirect.com/article"}
        result = ps.collect_platform_results(self.plan, [self.run_for([hit]), self.run_for([hit])])
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(len(result["records"][0]["sightings"]), 2)

    def test_rate_limit_defers_all_tasks_on_same_search_provider_and_preserves_checkpoint(self):
        now = datetime.now(timezone.utc)
        run = self.run_for(
            status="rate_limited", searched_at=now.isoformat(), retry_after_seconds=600
        )
        result = ps.collect_platform_results(self.plan, [run])
        self.assertEqual(result["resume"]["ready_task_ids"], [])
        self.assertTrue(result["resume"]["provider_retry_at"])
        self.assertEqual(result["checkpoint"]["runs"], [run])
        later = self.run_for(
            status="rate_limited",
            searched_at=(now - timedelta(seconds=700)).isoformat(),
            retry_after_seconds=600,
        )
        self.assertTrue(ps.collect_platform_results(self.plan, [later])["resume"]["ready_task_ids"])

    def test_shared_url_does_not_discard_different_titles(self):
        hits = [
            {"title": name, "url": "https://www.sciencedirect.com/article"}
            for name in ("First", "Second")
        ]
        self.assertEqual(
            len(ps.collect_platform_results(self.plan, [self.run_for(hits)])["records"]), 2
        )

    def test_unknown_task_and_missing_engine_are_rejected(self):
        with self.assertRaises(ValueError):
            ps.collect_platform_results(self.plan, [self.run_for(task_id="not-planned")])
        with self.assertRaises(ValueError):
            ps.collect_platform_results(self.plan, [self.run_for(engine="")])

    def test_failure_cannot_contain_successful_results(self):
        with self.assertRaises(ValueError):
            ps.collect_platform_results(
                self.plan,
                [self.run_for([{"title": "Source", "url": "https://example.org"}], status="error")],
            )

    def test_mcp_tools_execute_and_return_input_errors_without_crashing(self):
        result = asyncio.run(
            unified.handle_call_tool("prepare_platform_search", {"topic": "example"})
        )
        self.assertEqual(json.loads(result[0].text)["schema"], "platform-search/1")
        result = asyncio.run(
            unified.handle_call_tool("collect_platform_results", {"plan": {}, "runs": []})
        )
        self.assertIn("error", json.loads(result[0].text))


if __name__ == "__main__":
    unittest.main()
