import html
import json
import re
from pathlib import Path

import httpx
import pytest
from moonlighter.application.assisted.questions import QuestionKind
from moonlighter.application.assisted.sources.base import SourceMatch, questions_or_empty
from moonlighter.application.assisted.sources.lever import (
    LeverSource,
    fetch_lever_questions,
    parse_lever_form,
    posting_from_url,
)

PAGE = (Path(__file__).parent / "fixtures" / "lever_apply_palantir.html").read_text()


def _card_fields(page):
    fields = []
    for tag in re.findall(r"<input[^>]*baseTemplate[^>]*>", page):
        value = re.search(r'value="([^"]*)"', tag).group(1)
        fields.extend(json.loads(html.unescape(value))["fields"])
    return fields


def _by_label(questions, label):
    return next(question for question in questions if question.label == label)


def test_standard_fields_carry_the_asterisk_as_required():
    questions = parse_lever_form(PAGE)
    assert _by_label(questions, "Full name").required is True
    assert _by_label(questions, "Current location").required is True
    assert _by_label(questions, "Phone").required is False


def test_the_resume_field_is_a_file():
    resume = _by_label(parse_lever_form(PAGE), "Resume/CV")
    assert resume.kind is QuestionKind.FILE
    assert resume.required is True


def test_every_card_field_becomes_one_question():
    questions = parse_lever_form(PAGE)
    card_labels = {field["text"] for field in _card_fields(PAGE)}
    assert card_labels <= {question.label for question in questions}
    standard_labels = {"Resume/CV", "Full name", "Email", "Phone", "Current location"}
    assert standard_labels <= {question.label for question in questions}
    assert len(questions) == len({question.label for question in questions})


def test_card_types_map_to_kinds_with_options():
    languages = _by_label(parse_lever_form(PAGE), "Language Skill(s) (Check all that apply)")
    assert languages.kind is QuestionKind.MULTI_SELECT
    assert languages.required is True
    assert "English (ENG)" in languages.options


@pytest.mark.parametrize(
    ("card_type", "expected"),
    [
        ("text", QuestionKind.TEXT),
        ("textarea", QuestionKind.LONG_TEXT),
        ("dropdown", QuestionKind.SINGLE_SELECT),
        ("multiple-choice", QuestionKind.SINGLE_SELECT),
        ("multiple-select", QuestionKind.MULTI_SELECT),
        ("something-new", QuestionKind.LONG_TEXT),
    ],
)
def test_each_card_type(card_type, expected):
    card = {
        "fields": [
            {
                "type": card_type,
                "text": "Q",
                "required": False,
                "options": [{"text": "A"}, {"text": "B"}],
            }
        ]
    }
    value = html.escape(json.dumps(card), quote=True)
    page = f'<form><input type="hidden" value="{value}" name="cards[1][baseTemplate]"></form>'
    [question] = parse_lever_form(page)
    assert question.kind is expected


def test_a_choice_card_without_options_degrades_to_long_text():
    card = {"fields": [{"type": "dropdown", "text": "Q", "required": True, "options": []}]}
    page = f'<form><input value="{html.escape(json.dumps(card), quote=True)}" name="cards[1][baseTemplate]"></form>'
    [question] = parse_lever_form(page)
    assert question.kind is QuestionKind.LONG_TEXT


def test_a_malformed_card_makes_the_form_unreadable():
    page = PAGE.replace('name="cards[', 'data-broken="1" value="{not json" name="cards[', 1)
    with pytest.raises(ValueError):
        parse_lever_form(page)


def test_a_page_without_a_form_has_no_questions():
    assert parse_lever_form("<html><body>This posting is closed.</body></html>") == []


def test_a_card_that_is_not_an_object_makes_the_form_unreadable():
    page = '<form><input value="[1, 2]" name="cards[1][baseTemplate]"></form>'
    with pytest.raises(ValueError):
        parse_lever_form(page)


def test_card_fields_without_text_are_skipped():
    card = {"fields": ["not a field", {"type": "text", "required": True}]}
    page = f'<form><input value="{html.escape(json.dumps(card), quote=True)}" name="cards[1][baseTemplate]"></form>'
    assert parse_lever_form(page) == []


def test_an_empty_standard_label_is_skipped():
    page = '<ul><li class="application-question"><div class="application-label"></div><div>x</div></li></ul>'
    assert parse_lever_form(page) == []


async def test_lever_publishes_no_separate_required_fields():
    async with httpx.AsyncClient() as client:
        source = LeverSource()
        assert await source.required_fields(SourceMatch(source, ("a", "b")), client) == ()


def test_posting_from_url():
    uuid = "6ed76ce8-4156-4b60-b120-403538bd66cd"
    assert posting_from_url(f"https://jobs.lever.co/palantir/{uuid}") == ("palantir", uuid)
    assert posting_from_url(f"https://jobs.lever.co/palantir/{uuid}/apply") == ("palantir", uuid)
    assert posting_from_url(f"https://jobs.eu.lever.co/palantir/{uuid}") is None
    assert posting_from_url("https://jobs.lever.co/palantir") is None


async def test_fetch_reads_the_apply_page():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=PAGE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        questions = await fetch_lever_questions("palantir", "abc", client)
    assert seen == ["https://jobs.lever.co/palantir/abc/apply"]
    assert questions


async def test_a_non_200_means_no_form():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))
    ) as client:
        assert await fetch_lever_questions("palantir", "abc", client) == []


async def test_a_malformed_card_reaches_the_person_as_the_paste_hint():
    broken = PAGE.replace('name="cards[', 'value="{not json" name="cards[', 1)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=broken))
    ) as client:
        assert (
            await questions_or_empty(SourceMatch(LeverSource(), ("palantir", "abc")), client) == []
        )
