from ocint.daemon.github.models import ActorType, CommentState, StoredComment
from ocint.daemon.github.service import GitHubService


def test_followup_prompt_orders_actor_attributed_comments() -> None:
    # GIVEN
    comments = (
        StoredComment(
            github_comment_id=1,
            issue_id=2,
            body="first",
            actor_login="alice",
            actor_type=ActorType.HUMAN,
            state=CommentState.BATCHED,
            github_created_at="2026-01-01T00:00:00Z",
            marker="",
            agent_response_comment_id=0,
        ),
        StoredComment(
            github_comment_id=2,
            issue_id=2,
            body="second",
            actor_login="bob",
            actor_type=ActorType.HUMAN,
            state=CommentState.PENDING,
            github_created_at="2026-01-01T00:01:00Z",
            marker="",
            agent_response_comment_id=0,
        ),
    )

    # WHEN
    prompt = GitHubService.followup_prompt(comments)

    # THEN
    assert prompt.index("@alice") < prompt.index("@bob")
    assert "GitHub comment 1" in prompt
    assert "GitHub comment 2" in prompt
    assert "first" in prompt
    assert "second" in prompt


def test_duplicate_followups_have_distinct_prompt_identity() -> None:
    # GIVEN
    first = StoredComment(
        github_comment_id=101,
        issue_id=2,
        body="same request",
        actor_login="alice",
        actor_type=ActorType.HUMAN,
        state=CommentState.BATCHED,
        github_created_at="2026-01-01T00:00:00Z",
        marker="",
        agent_response_comment_id=0,
    )
    second = StoredComment(
        github_comment_id=102,
        issue_id=2,
        body="same request",
        actor_login="alice",
        actor_type=ActorType.HUMAN,
        state=CommentState.PENDING,
        github_created_at="2026-01-01T00:01:00Z",
        marker="",
        agent_response_comment_id=0,
    )

    # WHEN
    prompt = GitHubService.followup_prompt((first, second))

    # THEN
    assert prompt.count("same request") == 2
    assert "GitHub comment 101" in prompt
    assert "GitHub comment 102" in prompt
