from pydantic import BaseModel, ConfigDict

from ocint.daemon.github.service import (
    GitHubContext,
    complete_github_task,
    configured_github_repository,
    is_github_thread_eligible,
    poll_github,
    publish_github_pull_request,
)
from ocint.daemon.models import Job
from ocint.daemon.tasks.models import Task


class GitHubIntegration(BaseModel):
    model_config = ConfigDict(frozen=True)

    context: GitHubContext

    async def poll(self) -> None:
        await poll_github(self.context)

    async def complete_task(self, task: Task, job: Job) -> None:
        await complete_github_task(self.context, task, job)

    def eligible(self, thread_id: int) -> bool:
        return is_github_thread_eligible(self.context, thread_id)

    def configured_repository(self, thread_id: int) -> str:
        return configured_github_repository(self.context, thread_id)

    async def publish(self, repository: str, branch: str, base: str, title: str, body: str, job_id: str) -> str:
        return await publish_github_pull_request(self.context, repository, branch, base, title, body, job_id)
