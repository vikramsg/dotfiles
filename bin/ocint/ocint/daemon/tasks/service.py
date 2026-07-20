from ocint.daemon.tasks.models import Thread, ThreadMessage


def render_prompt(thread: Thread, messages: tuple[ThreadMessage, ...]) -> str:
    contributions = "".join(
        f"\n\nThread message {message.source_id} by @{message.actor}:\n{message.body}" for message in messages
    )
    return f"Thread: {thread.title or '(untitled)'}{contributions}"
