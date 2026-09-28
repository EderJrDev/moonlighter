"""The ordered list of form-question sources; the first that matches a job wins."""

from moonlighter.application.assisted.sources.base import QuestionSource, SourceMatch
from moonlighter.application.assisted.sources.greenhouse import GreenhouseSource
from moonlighter.application.assisted.sources.recruitee import RecruiteeSource
from moonlighter.core.db import Job

SOURCES: tuple[QuestionSource, ...] = (GreenhouseSource(), RecruiteeSource())


def find_match(job: Job) -> SourceMatch | None:
    for source in SOURCES:
        if (match := source.match(job)) is not None:
            return match
    return None
