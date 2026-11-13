import asyncio
import unittest
from datetime import datetime, timezone
from unittest import mock

from sciencedirect_meta import pipeline, rate_limit, server, sources


class PatientSearchTests(unittest.TestCase):
    def tearDown(self):
        server._HOST_COOLDOWN_UNTIL.clear()
        sources._SOURCE_COOLDOWN.clear()

    def test_http_date_retry_after_is_honored(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(
            rate_limit.retry_after_seconds("Thu, 01 Jan 2026 00:10:00 GMT", 0, now=now), 600
        )
        self.assertEqual(rate_limit.retry_after_seconds("999", 0, "export.arxiv.org"), 999)

    def test_long_retry_after_defers_instead_of_retrying_early_or_blocking(self):
        client = mock.Mock()
        client.get = mock.AsyncMock(
            return_value=mock.Mock(status_code=429, headers={"Retry-After": "600"})
        )
        with (
            mock.patch.object(server, "client_for_loop", return_value=client),
            mock.patch.object(server, "_throttle", new=mock.AsyncMock()),
            mock.patch.object(server.asyncio, "sleep", new=mock.AsyncMock()) as sleep,
        ):
            with self.assertRaises(server.RateLimitedError) as caught:
                asyncio.run(server.polite_get("https://api.openalex.org/works"))
        self.assertEqual(caught.exception.retry_after, 600)
        self.assertEqual(client.get.await_count, 1)
        sleep.assert_not_awaited()

    def test_independent_host_can_continue_while_other_is_in_cooldown(self):
        server._HOST_COOLDOWN_UNTIL["api.openalex.org"] = server.time.monotonic() + 600
        client = mock.Mock()
        client.get = mock.AsyncMock(return_value=mock.Mock(status_code=200, headers={}))
        with (
            mock.patch.object(server, "client_for_loop", return_value=client),
            mock.patch.object(server, "_throttle", new=mock.AsyncMock()),
        ):
            self.assertEqual(
                asyncio.run(server.polite_get("https://api.crossref.org/works")).status_code, 200
            )

    def test_source_coverage_reports_resume_deadline(self):
        async def limited():
            raise server.RateLimitedError("rate limited", retry_after=600)

        result = asyncio.run(sources.run_source("pubmed", limited(), 20))
        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(result["retry_after_seconds"], 600)
        self.assertIsNotNone(result["retry_at"])

    def test_multi_source_search_limits_parallel_source_jobs(self):
        active = maximum = 0
        async def source():
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return []
        async def run():
            tasks = {f"fixture-{i}": source() for i in range(6)}
            with mock.patch.object(pipeline, "_build_tasks", return_value=tasks):
                await pipeline.collect_source_results(list(tasks), "fixture", 10)
        asyncio.run(run())
        self.assertEqual(maximum, 2)


if __name__ == "__main__":
    unittest.main()
