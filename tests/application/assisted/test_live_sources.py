"""Live checks against the real ATSes — run with `uv run pytest -m e2e`.

Each test picks a posting that is open right now from the ATS's own listing,
so it does not rot as postings close. A skipped e2e counts as a failure here.
"""

import httpx
import pytest
from moonlighter.application.assisted.questions import QuestionKind
from moonlighter.application.assisted.sources.base import (
    SourceMatch,
    questions_or_empty,
    required_fields_or_empty,
)
from moonlighter.application.assisted.sources.inhire import InHireSource
from moonlighter.application.assisted.sources.lever import LeverSource
from moonlighter.application.assisted.sources.workable import WorkableSource

pytestmark = pytest.mark.e2e
HEADERS = {"User-Agent": "moonlighter/0.1"}


async def test_workable_live_form_has_a_required_question():
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        listing = (
            await client.get("https://apply.workable.com/api/v1/widget/accounts/seeq")
        ).json()
        shortcode = listing["jobs"][0]["shortcode"]
        questions = await questions_or_empty(SourceMatch(WorkableSource(), (shortcode,)), client)
    assert any(question.required for question in questions), questions


async def test_lever_live_form_has_a_required_question():
    async with httpx.AsyncClient(timeout=60, headers=HEADERS) as client:
        [posting] = (
            await client.get("https://api.lever.co/v0/postings/palantir?mode=json&limit=1")
        ).json()
        questions = await questions_or_empty(
            SourceMatch(LeverSource(), ("palantir", posting["id"])), client
        )
    assert any(question.required for question in questions), questions
    # The standard fields alone satisfy the assertion above; only a card yields a
    # choice or a long-text question, so this one proves the cards were read.
    # "Additional information" is long text from the standard markup, not a card.
    assert any(
        (question.is_choice or question.kind is QuestionKind.LONG_TEXT)
        and question.label != "Additional information"
        for question in questions
    ), f"no question came from a Lever card — the custom questions were not read: {questions}"


async def test_inhire_live_job_lists_required_fields():
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        listing = (
            await client.get(
                "https://api.inhire.app/job-posts/public/pages", headers={"X-Tenant": "infleet"}
            )
        ).json()
        job_id = listing["jobsPage"][0]["jobId"]
        required = await required_fields_or_empty(
            SourceMatch(InHireSource(), ("infleet", job_id)), client
        )
    assert required, "InHire returned no required fields for an open posting"
