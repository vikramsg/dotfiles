from ocint.daemon.tasks.models import MessageActorType, MessageDisposition, Thread, ThreadMessage
from ocint.daemon.tasks.service import render_prompt


def test_task_prompt_includes_all_accepted_messages_in_order() -> None:
    # GIVEN
    thread = Thread(
        id=1,
        repository="repo",
        source="github",
        source_thread_id="5",
        actor="alice",
        eligible=True,
        execution_job_id="",
        title="Make the change",
        body="Issue body",
    )
    messages = (
        ThreadMessage(
            id=1,
            thread_id=1,
            source_message_id="11",
            actor="alice",
            actor_type=MessageActorType.HUMAN,
            disposition=MessageDisposition.ACCEPTED,
            body="first",
            source_created_at="2026-01-01T00:00:00Z",
        ),
        ThreadMessage(
            id=2,
            thread_id=1,
            source_message_id="12",
            actor="bob",
            actor_type=MessageActorType.HUMAN,
            disposition=MessageDisposition.ACCEPTED,
            body="second",
            source_created_at="2026-01-01T00:01:00Z",
        ),
    )

    # WHEN
    prompt = render_prompt(thread, messages)

    # THEN
    assert "Make the change" in prompt
    assert "Issue body" in prompt
    assert prompt.index("Thread message 11") < prompt.index("Thread message 12")
    assert "@alice" in prompt
    assert "@bob" in prompt
