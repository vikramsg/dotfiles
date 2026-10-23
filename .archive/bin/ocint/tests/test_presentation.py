import json

import ocint.presentation as presentation
from ocint.presentation import plain_table, render_csv, render_json, render_jsonl, render_raw
from pydantic import BaseModel


class ExampleRow(BaseModel):
    name: str
    count: int


def test_presentation_facade_declares_every_public_symbol() -> None:
    # GIVEN the shared presentation facade
    expected = {
        "Group",
        "Markdown",
        "Presentation",
        "Rule",
        "Table",
        "Text",
        "data_table",
        "default_cli_context",
        "document",
        "key_value_section",
        "plain_table",
        "render_csv",
        "render_json",
        "render_jsonl",
        "render_raw",
    }

    # WHEN its supported exports are inspected
    exports = set(presentation.__all__)

    # THEN the facade is the complete public presentation API
    assert exports == expected
    assert all(hasattr(presentation, name) for name in exports)


def test_machine_serializers_preserve_exact_formats() -> None:
    # GIVEN one typed row and its mapping equivalent
    model = ExampleRow(name="alpha", count=2)
    rows = [{"name": "alpha", "count": 2}]

    # WHEN each exact serializer renders it
    rendered_json = render_json(model)
    rendered_jsonl = render_jsonl([model])
    rendered_csv = render_csv(rows)
    rendered_raw = render_raw(rows)

    # THEN each format is deterministic and unstyled
    assert json.loads(rendered_json) == {"name": "alpha", "count": 2}
    assert rendered_jsonl == '{"count": 2, "name": "alpha"}\n'
    assert rendered_csv == "name,count\r\nalpha,2\r\n"
    assert rendered_raw == "alpha\t2\n"
    assert "\x1b" not in rendered_json + rendered_jsonl + rendered_csv + rendered_raw


def test_plain_table_preserves_deterministic_legacy_text() -> None:
    # GIVEN one typed row
    rows = [ExampleRow(name="alpha", count=2)]

    # WHEN it is rendered as an unstyled table
    result = plain_table(rows)

    # THEN headers and cells use the existing deterministic layout
    assert result == "NAME   COUNT\n-----  -----\nalpha  2    \n"
