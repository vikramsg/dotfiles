import pytest
from ocint.daemon.models import PromptObservation
from ocint.daemon.pull_request_job.service import PromptDecision, prompt_action


@pytest.mark.parametrize(
    ("observation", "expected"),
    [
        (PromptObservation(found=True, completed=True, active=False), PromptDecision.ADVANCE),
        (PromptObservation(found=True, completed=False, active=True), PromptDecision.WAIT),
        (PromptObservation(found=True, completed=False, active=False), PromptDecision.SUBMIT),
        (PromptObservation(found=False, completed=False, active=False), PromptDecision.SUBMIT),
        (PromptObservation(found=False, completed=False, active=True), PromptDecision.SUBMIT),
    ],
)
def test_prompt_decision_matrix(observation: PromptObservation, expected: PromptDecision) -> None:
    # GIVEN / WHEN
    decision = prompt_action(observation)

    # THEN
    assert decision is expected
