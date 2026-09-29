import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

# ── Scan concorrente ──────────────────────────────────────────────────────────


async def test_greenhouse_scan_20_companies_concurrent():
    """
    20 companies scanned in parallel should finish much faster than sequential.
    Each mock HTTP call has a 0.02s delay. Sequential: ~0.4s. Concurrent: ~0.02s.
    """
    from moonlighter.discovery.sources.http import GreenhouseScanner

    async def slow_get(url, **keyword_arguments):
        await asyncio.sleep(0.02)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"jobs": []}
        return response

    mock_client = MagicMock()
    mock_client.get = slow_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    slugs = [f"company-{index}" for index in range(20)]

    with patch("moonlighter.discovery.sources.http.httpx.AsyncClient", return_value=mock_client):
        start_time = time.perf_counter()
        await GreenhouseScanner().scan(slugs)
        elapsed = time.perf_counter() - start_time

    # Concurrent: should be close to 0.02s (one batch), not 0.4s (20 sequential calls)
    assert elapsed < 0.3, f"Expected < 0.3s (concurrent), got {elapsed:.3f}s"


async def test_lever_scan_15_companies_concurrent():
    """15 Lever companies fetched concurrently."""
    from moonlighter.discovery.sources.http import LeverScanner

    async def slow_get(url, **keyword_arguments):
        await asyncio.sleep(0.02)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = []
        return response

    mock_client = MagicMock()
    mock_client.get = slow_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    slugs = [f"company-{index}" for index in range(15)]

    with patch("moonlighter.discovery.sources.http.httpx.AsyncClient", return_value=mock_client):
        start_time = time.perf_counter()
        await LeverScanner().scan(slugs)
        elapsed = time.perf_counter() - start_time

    assert elapsed < 0.3, f"Expected < 0.3s (concurrent), got {elapsed:.3f}s"


async def test_ashby_scan_10_companies_concurrent():
    """10 Ashby companies fetched concurrently via POST."""
    from moonlighter.discovery.sources.http import AshbyScanner

    async def slow_post(url, **keyword_arguments):
        await asyncio.sleep(0.02)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": {"jobPostings": []}}
        return response

    mock_client = MagicMock()
    mock_client.post = slow_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    slugs = [f"company-{index}" for index in range(10)]

    with patch("moonlighter.discovery.sources.http.httpx.AsyncClient", return_value=mock_client):
        start_time = time.perf_counter()
        await AshbyScanner().scan(slugs)
        elapsed = time.perf_counter() - start_time

    assert elapsed < 0.3, f"Expected < 0.3s (concurrent), got {elapsed:.3f}s"


# ── Batch LLM evaluation ─────────────────────────────────────────────────────


async def test_evaluate_10_jobs_concurrent_faster_than_sequential():
    """
    10 LLM evaluations in asyncio.gather should be much faster than sequential.
    Each mock evaluation has 0.05s delay.
    Sequential: ~0.5s. Concurrent: ~0.05s.
    """
    import json

    from moonlighter.discovery.evaluator import evaluate_job

    call_count = [0]
    _response = json.dumps(
        {
            "score": 7.0,
            "score_notes": "ok",
            "caveats": [],
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_source": None,
        }
    )

    async def slow_caller(prompt, model, cache_prefix=None):
        await asyncio.sleep(0.05)
        call_count[0] += 1
        return _response

    profile = {}
    jobs = [(f"Co{index}", f"Eng {index}", f"Job description {index}") for index in range(10)]

    start_time = time.perf_counter()
    await asyncio.gather(
        *[
            evaluate_job(
                company=company,
                title=title,
                description=description,
                profile=profile,
                model="test",
                _caller=slow_caller,
                location=None,
                remote_type=None,
            )
            for company, title, description in jobs
        ]
    )
    concurrent_elapsed = time.perf_counter() - start_time

    # Sequential baseline (just measure)
    start_time = time.perf_counter()
    for company, title, description in jobs:
        await evaluate_job(
            company=company,
            title=title,
            description=description,
            profile=profile,
            model="test",
            _caller=slow_caller,
            location=None,
            remote_type=None,
        )
    sequential_elapsed = time.perf_counter() - start_time

    assert concurrent_elapsed < sequential_elapsed * 0.5, (
        f"Concurrent ({concurrent_elapsed:.3f}s) should be at least 2x faster than sequential ({sequential_elapsed:.3f}s)"
    )
    assert concurrent_elapsed < 0.2, (
        f"Concurrent should finish in < 0.2s, got {concurrent_elapsed:.3f}s"
    )


async def test_evaluate_batch_size_10_processes_all():
    """
    25 jobs processed in batches of 10 (as scan_and_evaluate does) — all 25 processed.
    """
    import json

    from moonlighter.discovery.evaluator import evaluate_job

    _response = json.dumps(
        {
            "score": 7.0,
            "score_notes": "ok",
            "caveats": [],
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_source": None,
        }
    )

    async def fast_caller(prompt, model, cache_prefix=None):
        return _response

    profile = {}
    BATCH_SIZE = 10
    all_jobs = [(f"Co{index}", f"Eng{index}", f"desc{index}") for index in range(25)]
    results = []

    for index in range(0, len(all_jobs), BATCH_SIZE):
        batch = all_jobs[index : index + BATCH_SIZE]
        batch_results = await asyncio.gather(
            *[
                evaluate_job(
                    company=company,
                    title=title,
                    description=description,
                    profile=profile,
                    model="test",
                    _caller=fast_caller,
                    location=None,
                    remote_type=None,
                )
                for company, title, description in batch
            ]
        )
        results.extend(batch_results)

    assert len(results) == 25
    assert all(result.score == 7.0 for result in results)


# ── Queries no DB ─────────────────────────────────────────────────────────────


async def test_list_jobs_1000_records_fast(temporary_database):
    """list_jobs with 1000 records in DB returns in < 500ms."""
    from moonlighter.core.db import Job, init_db

    init_db()

    # Insert 1000 jobs
    with Job._meta.database.atomic():
        for index in range(1000):
            Job.create(
                source="greenhouse",
                company=f"Company{index}",
                title=f"Engineer {index}",
                url=f"https://example.com/jobs/{index}",
                score=float(index % 10),
                status="new",
            )

    from moonlighter.server import list_jobs

    start_time = time.perf_counter()
    result = await list_jobs(status="new", limit=20)
    elapsed = time.perf_counter() - start_time

    assert elapsed < 0.5, f"list_jobs with 1000 records took {elapsed:.3f}s, expected < 0.5s"
    assert result is not None


async def test_scan_log_dedup_1000_urls_fast(temporary_database):
    """Dedup check against ScanLog with 1000 entries completes in < 200ms."""
    from moonlighter.core.db import ScanLog, init_db

    init_db()

    with ScanLog._meta.database.atomic():
        for index in range(1000):
            ScanLog.create(job_url=f"https://example.com/jobs/{index}", source="greenhouse")

    start_time = time.perf_counter()
    seen_urls = {row.job_url for row in ScanLog.select(ScanLog.job_url)}
    elapsed = time.perf_counter() - start_time

    assert elapsed < 0.2, f"ScanLog dedup check took {elapsed:.3f}s, expected < 0.2s"
    assert len(seen_urls) == 1000
