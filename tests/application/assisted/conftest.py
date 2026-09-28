import httpx
import pytest
from moonlighter.core.db import Job, init_db


@pytest.fixture
def job_factory(request):
    """Create a Job row in the in-memory test database.

    Follows the pattern used in tests/application/test_service.py: the shared
    tmp_db fixture points MOONLIGHTER_DB_PATH at a fresh temp file, init_db()
    creates the schema in it, and Job.create() persists the row callers ask
    for. Pulled in via getfixturevalue rather than as a declared parameter so
    this file's parameter names stay full words without renaming the shared
    fixture everywhere else it is used.
    """
    request.getfixturevalue("tmp_db")
    init_db()

    def _make(**overrides: object) -> Job:
        defaults: dict[str, object] = {
            "source": "greenhouse",
            "company": "Acme",
            "title": "Engineer",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "status": "new",
        }
        defaults.update(overrides)
        return Job.create(**defaults)

    return _make


@pytest.fixture(autouse=True)
def _no_real_network(request, monkeypatch):
    """A unit test that reaches a real ATS is a bug: fail it loudly.

    MockTransport is unaffected (it never reaches AsyncHTTPTransport); e2e
    tests opt out because talking to the real ATS is their point.
    """
    if request.node.get_closest_marker("e2e") is not None:
        return

    async def refuse(self, http_request):
        raise AssertionError(f"real network call in a unit test: {http_request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
