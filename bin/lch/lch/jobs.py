import re
from dataclasses import dataclass

from lch.config import Service, load_config


@dataclass(frozen=True)
class JobDefinition:
    job_id: str
    label: str
    dispatch_command: list[str]
    watch_path_command: list[str]


@dataclass(frozen=True)
class ServiceDefinition:
    job_id: str
    label: str
    service: Service


@dataclass(frozen=True)
class JobIdentity:
    job_id: str
    label: str


JOBS = {
    "lch-screenshot-clipboard": JobDefinition(
        job_id="lch-screenshot-clipboard",
        label="",
        dispatch_command=["screenshot", "clipboard", "on-event"],
        watch_path_command=["screenshot", "watch-path"],
    ),
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


def get_job_identity(job_id: str) -> JobIdentity:
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", job_id) is None:
        raise ValueError(f"Invalid job ID: {job_id}")
    return JobIdentity(job_id=job_id, label=f"{load_config().namespace}.{job_id}")


def list_service_definitions() -> list[ServiceDefinition]:
    config = load_config()
    return [
        ServiceDefinition(
            job_id=service_id,
            label=f"{config.namespace}.{service_id}",
            service=config.services[service_id],
        )
        for service_id in sorted(config.services)
    ]


def get_launchd_job_definition(job_id: str) -> JobDefinition | ServiceDefinition:
    try:
        return get_job_definition(job_id)
    except KeyError:
        for service in list_service_definitions():
            if service.job_id == job_id:
                return service
    raise KeyError(f"Unknown job: {job_id}")


def list_launchd_job_definitions() -> list[JobDefinition | ServiceDefinition]:
    definitions: list[JobDefinition | ServiceDefinition] = [
        *list_job_definitions(),
        *list_service_definitions(),
    ]
    return sorted(definitions, key=lambda definition: definition.job_id)
