from dataclasses import dataclass

from lch.config import load_config


@dataclass(frozen=True)
class JobDefinition:
    job_id: str
    label: str
    dispatch_command: list[str]
    watch_path_command: list[str]


JOBS = {
    "lch-screenshot-clipboard": JobDefinition(
        job_id="lch-screenshot-clipboard",
        label="",
        dispatch_command=["screenshot", "clipboard", "on-event"],
        watch_path_command=["screenshot", "watch-path"],
    ),
    "lch-screenshot-sync": JobDefinition(
        job_id="lch-screenshot-sync",
        label="",
        dispatch_command=["screenshot", "sync", "run"],
        watch_path_command=["screenshot", "watch-path"],
    )
}


def list_job_definitions() -> list[JobDefinition]:
    return [get_job_definition(job_id) for job_id in sorted(JOBS)]


def get_job_definition(job_id: str) -> JobDefinition:
    try:
        job = JOBS[job_id]
    except KeyError as exc:
        raise KeyError(f"Unknown job: {job_id}") from exc

    namespace = load_config().namespace
    return JobDefinition(
        job_id=job.job_id,
        label=f"{namespace}.{job.job_id}",
        dispatch_command=list(job.dispatch_command),
        watch_path_command=list(job.watch_path_command),
    )
