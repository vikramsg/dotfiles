from ocint.daemon.tasks.models import Thread, ThreadMessage


def render_prompt(thread: Thread, messages: tuple[ThreadMessage, ...]) -> str:
    contributions = "".join(
        f"\n\nThread message {message.source_id} by @{message.actor}:\n{message.body}" for message in messages
    )
    return (
        "Complete this thread by making meaningful changes in the repository. "
        "Do not finish with only a conversational answer. For a research or informational request, "
        "write the findings into the most appropriate repository documentation. "
        "Do not create or publish a pull request; the daemon handles publication after validation.\n\n"
        f"Thread: {thread.title or '(untitled)'}{contributions}"
    )
