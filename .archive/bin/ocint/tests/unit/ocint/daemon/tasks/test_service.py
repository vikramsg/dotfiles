from ocint.daemon.models import GitHubLogin
from ocint.daemon.tasks.models import MessageClassification, Thread, ThreadMessage
from ocint.daemon.tasks.service import render_prompt


def test_render_prompt_includes_all_contributions_in_order() -> None:
    # GIVEN
    thread = Thread(id=1, source_id="github:owner/repo:5", title="Make the change")
    messages = (
        ThreadMessage(
            id=1,
            thread_id=1,
            source_id="github:owner/repo:issue:5",
            actor=GitHubLogin("alice"),
            classification=MessageClassification.ACTIONABLE,
            body="Issue body",
            source_created_at="2026-01-01T00:00:00Z",
        ),
        ThreadMessage(
            id=2,
            thread_id=1,
            source_id="github:owner/repo:comment:12",
            actor=GitHubLogin("bob"),
            classification=MessageClassification.ACTIONABLE,
            body="second",
            source_created_at="2026-01-01T00:01:00Z",
        ),
    )

    # WHEN
    prompt = render_prompt(thread, messages)

    # THEN
    assert "Make the change" in prompt
    assert "Issue body" in prompt
    assert "making meaningful changes in the repository" in prompt
    assert "research or informational request" in prompt
    assert "Do not create or publish a pull request" in prompt
    assert prompt.index("Thread message github:owner/repo:issue:5") < prompt.index(
        "Thread message github:owner/repo:comment:12"
    )
    assert "@alice" in prompt
    assert "@bob" in prompt
