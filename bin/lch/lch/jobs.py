from dataclasses import dataclass


@dataclass(frozen=True)
class JobDefinition:
    job_id: str
    label: str
    dispatch_command: list[str]
    watch_path_command: list[str]


JOBS = {
    "lch-screenshot-clipboard": JobDefinition(
        job_id="lch-screenshot-clipboard",
        label="com.vikramsg.dotfiles.lch-screenshot-clipboard",
        dispatch_command=["screenshot", "clipboard", "on-event"],
        watch_path_command=["screenshot", "watch-path"],
    )
}


def get_job_definition(job_id: str) -> JobDefinition:
    try:
        return JOBS[job_id]
    except KeyError as exc:
        raise KeyError(f"Unknown job: {job_id}") from exc
