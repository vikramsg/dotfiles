import asyncio
import contextlib
import socket
import threading
from pathlib import Path

from ocint.daemon.config import DaemonConfig, LoadedDaemonConfig, load_daemon_config
from ocint.daemon.git import GitHubPublisher, RepositoryManager
from ocint.daemon.models import (
    AgentRuntime,
    Artifact,
    Channel,
    Claim,
    Job,
    JobStage,
    JobState,
    OutboxItem,
    PromptObservation,
    RuntimeEvent,
    WorkspaceRetirement,
    Worktree,
    WorkUpdate,
)
from ocint.daemon.outbox_repository import OutboxRepository
from ocint.daemon.repository import ControlRepository
from ocint.daemon.runner_repository import RunnerRepository
from ocint.daemon.service import matching_channel, recovery_plan, retirable_workspaces, terminal_update
from ocint.daemon.workspace_repository import WorkspaceRepository


class ActiveConfig:
    def __init__(self, loaded: LoadedDaemonConfig, home: Path) -> None:
        self.loaded = loaded
        self.home = home

    def reload(self) -> LoadedDaemonConfig:
        replacement = load_daemon_config(self.loaded.settings, self.home)
        current = self.loaded.config
        candidate = replacement.config
        changed: list[str] = []
        if current.database_path != candidate.database_path:
            changed.append("database_path")
        if current.mirror_root != candidate.mirror_root:
            changed.append("mirror_root")
        if current.worktree_root != candidate.worktree_root:
            changed.append("worktree_root")
        if current.api != candidate.api:
            changed.append("api")
        if current.opencode != candidate.opencode:
            changed.append("opencode")
        if current.providers != candidate.providers:
            changed.append("providers")
        if current.channels != candidate.channels:
            changed.append("channels")
        if current.scheduler.command_timeout_seconds != candidate.scheduler.command_timeout_seconds:
            changed.append("scheduler.command_timeout_seconds")
        if current.scheduler.command_output_bytes != candidate.scheduler.command_output_bytes:
            changed.append("scheduler.command_output_bytes")
        if current.scheduler.shutdown_timeout_seconds != candidate.scheduler.shutdown_timeout_seconds:
            changed.append("scheduler.shutdown_timeout_seconds")
        if changed:
            raise ValueError(f"non-reloadable daemon fields changed: {', '.join(changed)}")
        self.loaded = replacement
        return replacement

    def current(self) -> LoadedDaemonConfig:
        return self.loaded


class DaemonRunner:
    def __init__(
        self,
        active_config: ActiveConfig,
        repository: ControlRepository,
        manager: RepositoryManager,
        runtime: AgentRuntime,
        publisher: GitHubPublisher,
        channels: list[Channel],
        outbox: OutboxRepository,
        runners: RunnerRepository,
        workspaces: WorkspaceRepository,
    ) -> None:
        self.active_config = active_config
        self.repository = repository
        self.manager = manager
        self.runtime = runtime
        self.publisher = publisher
        self.channels = channels
        self.outbox = outbox
        self.runners = runners
        self.workspaces = workspaces
        self.owner = f"{socket.gethostname()}:{id(self)}"
        self.stopping = asyncio.Event()
        self.execution_tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        config = self.active_config.loaded.config
        self.runners.register(self.owner, config.scheduler.lease_seconds)
        await self._reconcile(config)
        background = [asyncio.create_task(self._supervise_channel(channel)) for channel in self.channels]
        background.append(asyncio.create_task(self._supervise_outbox()))
        background.append(asyncio.create_task(self._supervise_retention()))
        background.append(asyncio.create_task(self._runner_heartbeat()))
        try:
            while not self.stopping.is_set():
                snapshot = self.active_config.loaded
                await self._reconcile(snapshot.config)
                claim = self.repository.claim(
                    self.owner,
                    snapshot.config.scheduler.capacity,
                    snapshot.config.scheduler.lease_seconds,
                    snapshot.config.model_dump_json(),
                )
                if claim is None:
                    await asyncio.sleep(snapshot.config.scheduler.poll_seconds)
                    if self.stopping.is_set():
                        break
                    continue
                task = asyncio.create_task(self._execute(claim, snapshot.config))
                self.execution_tasks.add(task)
                task.add_done_callback(self.execution_tasks.discard)
        finally:
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            timeout = config.scheduler.shutdown_timeout_seconds
            try:
                async with asyncio.timeout(timeout):
                    await asyncio.gather(*self.execution_tasks, return_exceptions=True)
            except TimeoutError:
                for task in self.execution_tasks:
                    task.cancel()
                await asyncio.gather(*self.execution_tasks, return_exceptions=True)
            self.runners.stop(self.owner)

    async def _reconcile(self, config: DaemonConfig) -> None:
        for claim in self.runners.recoverable(self.owner):
            session_status = "missing"
            prompt = PromptObservation(found=False, completed=False)
            worktree_has_changes = False
            if claim.job.worktree_path is not None:
                worktree = Worktree(
                    path=claim.job.worktree_path,
                    branch=claim.job.branch,
                    base_revision=claim.job.base_revision,
                )
                with contextlib.suppress(Exception):
                    worktree_has_changes = await asyncio.to_thread(
                        self.manager.has_changes, worktree, threading.Event()
                    )
                if claim.job.session_id:
                    with contextlib.suppress(Exception):
                        session = await self.runtime.inspect(claim.job.worktree_path, claim.job.session_id)
                        session_status = session.status
                        prompt = await self.runtime.prompt_observation(
                            claim.job.worktree_path,
                            claim.job.session_id,
                            claim.job.prompt,
                        )
            plan = recovery_plan(
                claim,
                session_status,
                prompt,
                worktree_has_changes,
                config.scheduler.max_attempts,
            )
            update = terminal_update(claim.job, JobState.FAILED, plan.error) if plan.state is JobState.FAILED else None
            self.runners.recover(
                claim,
                plan.state,
                plan.stage,
                plan.error,
                reset_execution=plan.reset_execution,
                terminal_update=update,
            )

    async def _supervise_channel(self, channel: Channel) -> None:
        while not self.stopping.is_set():
            try:
                await channel.run()
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1)

    async def _execute(self, claim: Claim, config: DaemonConfig) -> None:
        cancelled = threading.Event()
        execution = asyncio.current_task()
        if execution is None:
            raise RuntimeError("daemon execution requires an asyncio task")
        heartbeat = asyncio.create_task(self._heartbeat(claim, config, cancelled, execution))
        event_task: asyncio.Task[None] | None = None
        worktree: Worktree | None = None
        try:
            repository_config = config.repository(claim.job.repository)
            job = self.repository.get(claim.job.id)
            if job.worktree_path is None:
                worktree = await asyncio.to_thread(self.manager.provision, repository_config, job.id, cancelled)
                self.repository.set_worktree(job.id, claim.lease_id, worktree)
            else:
                worktree = Worktree(path=job.worktree_path, branch=job.branch, base_revision=job.base_revision)
            job = self.repository.get(job.id)
            if job.stage is JobStage.EXECUTION:
                if not job.session_id:
                    session = await self.runtime.create(worktree.path, f"ocint:{job.id}:{claim.attempt_id}")
                    self.repository.set_session(
                        job.id, claim.lease_id, session.session_id, str(config.opencode.server_url).rstrip("/")
                    )
                    job = self.repository.get(job.id)
                self.repository.transition(
                    job.id, claim.attempt_id, claim.lease_id, JobState.PREPARING, JobState.RUNNING
                )
                queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
                connected = asyncio.Event()
                event_task = asyncio.create_task(
                    self._collect_events(job, claim, worktree, queue, connected, cancelled)
                )
                async with asyncio.timeout(config.opencode.request_timeout_seconds):
                    await connected.wait()
                completed_without_event = False
                if job.prompt_submitted:
                    current_session = await self.runtime.inspect(worktree.path, job.session_id)
                    if current_session.status == "idle":
                        observation = await self.runtime.prompt_observation(worktree.path, job.session_id, job.prompt)
                        if observation.completed or await asyncio.to_thread(
                            self.manager.has_changes, worktree, cancelled
                        ):
                            completed_without_event = True
                        else:
                            self.repository.reset_execution(job.id, claim.lease_id)
                            raise RuntimeError("persisted OpenCode session has no active runner or worktree changes")
                if not job.prompt_submitted:
                    if not job.prompt_intended:
                        job = self.repository.checkpoint(
                            job.id,
                            claim.lease_id,
                            JobStage.EXECUTION,
                            prompt_intended=True,
                        )
                    observation = await self.runtime.prompt_observation(worktree.path, job.session_id, job.prompt)
                    if not observation.found:
                        await self.runtime.prompt(worktree.path, job.session_id, job.prompt)
                    job = self.repository.checkpoint(
                        job.id,
                        claim.lease_id,
                        JobStage.EXECUTION,
                        prompt_intended=True,
                        prompt_submitted=True,
                    )
                if not completed_without_event:
                    await self._wait_for_completion(job, worktree, queue, cancelled, config)
                self.repository.transition(
                    job.id, claim.attempt_id, claim.lease_id, JobState.RUNNING, JobState.VALIDATING
                )
                job = self.repository.checkpoint(job.id, claim.lease_id, JobStage.VALIDATION)
            elif job.state is JobState.PREPARING:
                resumed_state = (
                    JobState.PUBLISHING
                    if job.stage in {JobStage.PUSH, JobStage.PULL_REQUEST, JobStage.COMPLETE}
                    else JobState.VALIDATING
                )
                self.repository.transition(job.id, claim.attempt_id, claim.lease_id, JobState.PREPARING, resumed_state)
            job = self.repository.get(job.id)
            if job.stage is JobStage.VALIDATION:
                await asyncio.to_thread(self.manager.validate, worktree, repository_config.checks, cancelled)
                job = self.repository.checkpoint(job.id, claim.lease_id, JobStage.COMMIT)
            if job.stage is JobStage.COMMIT:
                commit = await asyncio.to_thread(
                    self.manager.commit, worktree, f"ocint: complete job {job.id}", cancelled
                )
                self.repository.add_artifact(job.id, claim.lease_id, Artifact(kind="commit", value=commit, url=""))
                job = self.repository.checkpoint(job.id, claim.lease_id, JobStage.PUSH, commit_sha=commit)
                self.repository.transition(
                    job.id, claim.attempt_id, claim.lease_id, JobState.VALIDATING, JobState.PUBLISHING
                )
            if job.stage is JobStage.PUSH:
                await asyncio.to_thread(self.manager.push, worktree, cancelled)
                job = self.repository.checkpoint(job.id, claim.lease_id, JobStage.PULL_REQUEST, pushed=True)
            if job.stage is JobStage.PULL_REQUEST and repository_config.github_repository:
                pull = await self.publisher.publish(
                    repository_config.github_repository,
                    worktree.branch,
                    repository_config.default_branch,
                    f"ocint: complete job {job.id}",
                    f"Automated by ocint daemon for {job.conversation_id}.",
                )
                self.repository.add_artifact(job.id, claim.lease_id, pull)
                job = self.repository.checkpoint(job.id, claim.lease_id, JobStage.COMPLETE, pull_request_url=pull.url)
            update = WorkUpdate(
                conversation_id=job.conversation_id,
                job_id=job.id,
                status=JobState.COMPLETED,
                message="job completed",
                session_id=job.session_id,
                artifact_url=job.pull_request_url,
            )
            self.repository.finish_with_outbox(claim, JobState.COMPLETED, "", update)
        except asyncio.CancelledError:
            cancelled.set()
            if worktree is not None:
                current = self.repository.get(claim.job.id)
                if current.session_id:
                    with contextlib.suppress(Exception):
                        await asyncio.shield(self.runtime.cancel(worktree.path, current.session_id))
            raise
        except Exception as error:
            cancelled.set()
            if worktree is not None and claim.job.session_id:
                with contextlib.suppress(Exception):
                    await self.runtime.cancel(worktree.path, claim.job.session_id)
            message = str(error)[:2000]
            with contextlib.suppress(RuntimeError):
                current = self.repository.get(claim.job.id)
                if current.cancel_requested:
                    self.repository.finish_with_outbox(
                        claim,
                        JobState.CANCELLED,
                        "cancelled",
                        terminal_update(current, JobState.CANCELLED, "cancelled"),
                    )
                elif current.attempt_count < config.scheduler.max_attempts:
                    self.repository.requeue(current.id, claim.attempt_id, claim.lease_id, message)
                else:
                    self.repository.finish_with_outbox(
                        claim,
                        JobState.FAILED,
                        message,
                        terminal_update(current, JobState.FAILED, message),
                    )
        finally:
            cancelled.set()
            if event_task is not None:
                event_task.cancel()
                await asyncio.gather(event_task, return_exceptions=True)
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _collect_events(
        self,
        job: Job,
        claim: Claim,
        worktree: Worktree,
        queue: asyncio.Queue[RuntimeEvent],
        connected: asyncio.Event,
        cancelled: threading.Event,
    ) -> None:
        async for item in self.runtime.events(worktree.path, job.session_id):
            if cancelled.is_set():
                return
            self.repository.record_event(job.id, claim.attempt_id, claim.lease_id, item.event_type, item.payload)
            if item.event_type == "server.connected":
                connected.set()
            await queue.put(item)

    async def _wait_for_completion(
        self,
        job: Job,
        worktree: Worktree,
        queue: asyncio.Queue[RuntimeEvent],
        cancelled: threading.Event,
        config: DaemonConfig,
    ) -> None:
        async with asyncio.timeout(config.scheduler.job_timeout_seconds):
            while True:
                if cancelled.is_set() or self.repository.get(job.id).cancel_requested:
                    await self.runtime.cancel(worktree.path, job.session_id)
                    raise RuntimeError("job cancelled or lease lost")
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1)
                except TimeoutError:
                    if await self._session_completed(job, worktree, cancelled):
                        return
                    continue
                if item.event_type == "server.connected" and await self._session_completed(job, worktree, cancelled):
                    return
                if item.event_type.startswith("permission"):
                    await self.runtime.cancel(worktree.path, job.session_id)
                    raise PermissionError("OpenCode requested an unapproved permission")
                if item.event_type == "session.idle" or (item.event_type == "session.status" and item.status == "idle"):
                    return

    async def _session_completed(self, job: Job, worktree: Worktree, cancelled: threading.Event) -> bool:
        current_session = await self.runtime.inspect(worktree.path, job.session_id)
        if current_session.status != "idle":
            return False
        observation = await self.runtime.prompt_observation(worktree.path, job.session_id, job.prompt)
        return observation.completed or await asyncio.to_thread(self.manager.has_changes, worktree, cancelled)

    async def _heartbeat(
        self,
        claim: Claim,
        config: DaemonConfig,
        cancelled: threading.Event,
        execution: asyncio.Task[None],
    ) -> None:
        while True:
            await asyncio.sleep(config.scheduler.heartbeat_seconds)
            if not self.repository.heartbeat(claim.lease_id, config.scheduler.lease_seconds):
                cancelled.set()
                execution.cancel()
                return

    async def _supervise_outbox(self) -> None:
        while not self.stopping.is_set():
            try:
                outbox_lease_seconds = self.active_config.loaded.config.scheduler.outbox_lease_seconds
                for item in self.outbox.claim(self.owner, outbox_lease_seconds, limit=1):
                    try:
                        channel = matching_channel(item, self.channels)
                        await self._publish_outbox(item, channel)
                    except Exception as error:
                        self.outbox.acknowledge(item.id, item.lease_id, str(error))
                    else:
                        self.outbox.acknowledge(item.id, item.lease_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1)
            await asyncio.sleep(1)

    async def _publish_outbox(self, item: OutboxItem, channel: Channel) -> None:
        lease_seconds = self.active_config.loaded.config.scheduler.outbox_lease_seconds
        publication = asyncio.current_task()
        if publication is None:
            raise RuntimeError("outbox publication requires an asyncio task")
        renewal = asyncio.create_task(self._renew_outbox(item, lease_seconds, publication))
        try:
            await channel.publish(item.update, item.id, item.delivery_target)
        finally:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)

    async def _renew_outbox(
        self,
        item: OutboxItem,
        lease_seconds: int,
        publication: asyncio.Task[None],
    ) -> None:
        while True:
            await asyncio.sleep(max(lease_seconds / 3, 0.1))
            if not self.outbox.renew(item, lease_seconds):
                publication.cancel()
                return

    async def _runner_heartbeat(self) -> None:
        while not self.stopping.is_set():
            config = self.active_config.loaded.config
            await asyncio.sleep(config.scheduler.heartbeat_seconds)
            if not self.runners.heartbeat(self.owner, config.scheduler.lease_seconds):
                self.stopping.set()
                return

    async def _supervise_retention(self) -> None:
        while not self.stopping.is_set():
            try:
                config = self.active_config.loaded.config
                for job in retirable_workspaces(self.repository, config.retention_seconds):
                    if job.worktree_path is None:
                        continue
                    retirement = self.workspaces.claim_retirement(
                        job.workspace_owner_id,
                        str(job.worktree_path),
                        self.owner,
                        60,
                    )
                    if retirement is None:
                        continue
                    worktree = Worktree(
                        path=job.worktree_path,
                        branch=job.branch,
                        base_revision=job.base_revision,
                    )
                    retention_task = asyncio.current_task()
                    if retention_task is None:
                        raise RuntimeError("workspace retirement requires an asyncio task")
                    renewal = asyncio.create_task(self._renew_workspace_retirement(retirement, retention_task))
                    try:
                        disposed = retirement.disposed
                        removed = retirement.removed
                        if not disposed:
                            await self.runtime.dispose(worktree.path)
                            disposed = True
                            if not self.workspaces.checkpoint(retirement, disposed=disposed, removed=removed):
                                raise RuntimeError("workspace retirement lease lost after dispose")
                        if not removed:
                            await asyncio.to_thread(
                                self.manager.retire,
                                config.repository(job.repository),
                                worktree,
                                threading.Event(),
                            )
                            removed = True
                            if not self.workspaces.checkpoint(retirement, disposed=disposed, removed=removed):
                                raise RuntimeError("workspace retirement lease lost after removal")
                    except Exception as error:
                        self.workspaces.complete(retirement, str(error))
                        continue
                    finally:
                        renewal.cancel()
                        await asyncio.gather(renewal, return_exceptions=True)
                    self.workspaces.complete(retirement)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1)
            await asyncio.sleep(10)

    async def _renew_workspace_retirement(
        self,
        retirement: WorkspaceRetirement,
        retirement_task: asyncio.Task[None],
    ) -> None:
        while True:
            await asyncio.sleep(20)
            if not self.workspaces.renew(retirement, 60):
                retirement_task.cancel()
                return
