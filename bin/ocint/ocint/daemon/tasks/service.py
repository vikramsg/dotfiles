from ocint.daemon.tasks.models import Thread, ThreadMessage


def render_prompt(thread: Thread, messages: tuple[ThreadMessage, ...]) -> str:
    contributions = "".join(
        f"\n\nThread message {message.source_id} by @{message.actor}:\n{message.body}" for message in messages
    )
    return (
        "Complete this thread with the most appropriate outcome. "
        "If the request calls for implementation or documentation, make meaningful repository changes. "
        "If it only calls for an answer, investigation, clarification, or guidance, leave the repository unchanged "
        "and provide the answer in your final response. "
        "Do not create or publish a pull request; the daemon handles publication after validation.\n\n"
        f"Thread: {thread.title or '(untitled)'}{contributions}"
    )
