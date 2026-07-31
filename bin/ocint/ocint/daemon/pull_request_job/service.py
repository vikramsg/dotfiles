from enum import StrEnum

from ocint.daemon.models import PromptObservation
from ocint.daemon.pull_request_job.config import PullRequestJobConfig
from ocint.daemon.pull_request_job.models import PullRequestJobRequest


class PromptDecision(StrEnum):
    SUBMIT = "submit"
    WAIT = "wait"
    ADVANCE = "advance"


def authorize(request: PullRequestJobRequest, config: PullRequestJobConfig) -> None:
    repository = config.repository(request.repository)
    if repository.actors and str(request.actor) not in {str(actor) for actor in repository.actors}:
        raise PermissionError(f"actor is not allowed for {request.repository}: {request.actor}")


def prompt_action(observation: PromptObservation) -> PromptDecision:
    if observation.completed:
        return PromptDecision.ADVANCE
    if observation.found and observation.active:
        return PromptDecision.WAIT
    return PromptDecision.SUBMIT
