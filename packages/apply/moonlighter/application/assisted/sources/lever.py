"""Lever has no JSON form API; its public apply page carries the whole form.

`GET https://jobs.lever.co/{company}/{posting}/apply` is HTML (~1.9 MB). Standard
fields are `<li class="application-question">` with a `div.application-label`
whose `<span class="required">✱</span>` marks a required field; the resume
field's `<li>` also has the class `resume`. Custom questions are cards: a hidden
`<input name="cards[<id>][baseTemplate]" value="<HTML-escaped JSON>">` whose
`fields` carry `type`, `text`, `required` and `options[].text`; their `<li>`s
are `custom-question` and are read from the JSON, not the markup. Verified on a
live posting on 2026-09-25 (bancada ats-form-apis). A malformed card makes the
whole form unreadable: a sheet silently missing a card would claim a complete
form. jobs.eu.lever.co was never observed and does not match.
"""

import json
import re
from html.parser import HTMLParser
from typing import Any

import httpx
from moonlighter.application.assisted.questions import FormQuestion, QuestionKind
from moonlighter.application.assisted.sources.base import SourceMatch
from moonlighter.core.db import Job

APPLY_PAGE = "https://jobs.lever.co/{company}/{posting_id}/apply"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; moonlighter/0.1)"}

_URL = re.compile(r"https?://jobs\.lever\.co/(?P<company>[^/]+)/(?P<posting_id>[0-9a-f-]{36})")

_CARD_KINDS = {
    "text": QuestionKind.TEXT,
    "textarea": QuestionKind.LONG_TEXT,
    "dropdown": QuestionKind.SINGLE_SELECT,
    "multiple-choice": QuestionKind.SINGLE_SELECT,
    "multiple-select": QuestionKind.MULTI_SELECT,
}
_CHOICE_KINDS = (QuestionKind.SINGLE_SELECT, QuestionKind.MULTI_SELECT)
_REQUIRED_MARK = "✱"


def posting_from_url(url: str) -> tuple[str, str] | None:
    match = _URL.search(url)
    return (match["company"], match["posting_id"]) if match else None


class _LeverFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.standard_fields: list[tuple[str, bool, bool]] = []  # (label, required, is_file)
        self.card_templates: list[str] = []
        self._question_classes: list[str] | None = None
        self._in_label = False
        self._label_parts: list[str] = []
        self._label_required = False

    def handle_starttag(self, tag: str, attribute_pairs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attribute_pairs)
        classes = (attributes.get("class") or "").split()
        if tag == "input" and "[baseTemplate]" in (attributes.get("name") or ""):
            self.card_templates.append(attributes.get("value") or "")
        elif tag == "li" and "application-question" in classes:
            self._question_classes = classes
        elif tag == "div" and "application-label" in classes and self._question_classes is not None:
            self._in_label = True
            self._label_parts = []
            self._label_required = False
        elif tag == "span" and self._in_label and "required" in classes:
            self._label_required = True

    def handle_endtag(self, tag: str) -> None:
        if tag != "div" or not self._in_label or self._question_classes is None:
            return
        self._in_label = False
        if "custom-question" not in self._question_classes:
            label = " ".join("".join(self._label_parts).replace(_REQUIRED_MARK, "").split())
            if label:
                self.standard_fields.append(
                    (label, self._label_required, "resume" in self._question_classes)
                )
        self._question_classes = None

    def handle_data(self, data: str) -> None:
        if self._in_label:
            self._label_parts.append(data)


def _card_questions(template: str) -> list[FormQuestion]:
    card = json.loads(template)
    if not isinstance(card, dict):
        raise ValueError("a Lever card template is not a JSON object")
    questions: list[FormQuestion] = []
    for field in card.get("fields") or []:
        if not isinstance(field, dict) or not field.get("text"):
            continue
        kind = _CARD_KINDS.get(str(field.get("type")), QuestionKind.LONG_TEXT)
        options = _options(field) if kind in _CHOICE_KINDS else ()
        if kind in _CHOICE_KINDS and not options:
            kind = QuestionKind.LONG_TEXT
        questions.append(
            FormQuestion(
                label=str(field["text"]),
                kind=kind,
                required=bool(field.get("required")),
                options=options,
            )
        )
    return questions


def _options(field: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(option["text"])
        for option in field.get("options") or []
        if isinstance(option, dict) and option.get("text")
    )


def parse_lever_form(page: str) -> list[FormQuestion]:
    parser = _LeverFormParser()
    parser.feed(page)
    questions = [
        FormQuestion(
            label=label,
            kind=QuestionKind.FILE if is_file else QuestionKind.TEXT,
            required=required,
        )
        for label, required, is_file in parser.standard_fields
    ]
    for template in parser.card_templates:
        questions.extend(_card_questions(template))
    return questions


async def fetch_lever_questions(
    company: str, posting_id: str, client: httpx.AsyncClient
) -> list[FormQuestion]:
    response = await client.get(
        APPLY_PAGE.format(company=company, posting_id=posting_id), headers=HEADERS
    )
    if response.status_code != 200:
        return []
    return parse_lever_form(response.text)


class LeverSource:
    name = "lever"

    def match(self, job: Job) -> SourceMatch | None:
        found = posting_from_url(job.url)
        return SourceMatch(self, found) if found else None

    async def questions(self, match: SourceMatch, client: httpx.AsyncClient) -> list[FormQuestion]:
        company, posting_id = match.locator
        return await fetch_lever_questions(company, posting_id, client)

    async def required_fields(
        self, match: SourceMatch, client: httpx.AsyncClient
    ) -> tuple[str, ...]:
        return ()
