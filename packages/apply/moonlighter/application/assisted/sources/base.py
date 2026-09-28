"""The contract every form-question source implements, and the guard around it.

A source answers two questions about one job: does it know this job's form
(`match`, no network), and what does the form ask (`questions`). `[]` from
`questions` means "this source does not have the form" and sends the person to
the paste path — never "the form has zero questions". `required_fields` exists
for sources that publish only which built-in fields are required (InHire).
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx
from moonlighter.application.assisted.questions import FormQuestion
from moonlighter.core.db import Job

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceMatch:
    source: QuestionSource
    locator: tuple[str, ...]


class QuestionSource(Protocol):
    name: str

    def match(self, job: Job) -> SourceMatch | None: ...

    async def questions(
        self, match: SourceMatch, client: httpx.AsyncClient
    ) -> list[FormQuestion]: ...

    async def required_fields(
        self, match: SourceMatch, client: httpx.AsyncClient
    ) -> tuple[str, ...]: ...


async def questions_or_empty(match: SourceMatch, client: httpx.AsyncClient) -> list[FormQuestion]:
    """A source that cannot be reached or read has no form: the caller asks for a paste."""
    try:
        return await match.source.questions(match, client)
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("%s questions unavailable: %s", match.source.name, error, exc_info=True)
        return []


async def required_fields_or_empty(
    match: SourceMatch, client: httpx.AsyncClient
) -> tuple[str, ...]:
    try:
        return await match.source.required_fields(match, client)
    except (httpx.HTTPError, ValueError) as error:
        logger.warning(
            "%s required fields unavailable: %s", match.source.name, error, exc_info=True
        )
        return ()
