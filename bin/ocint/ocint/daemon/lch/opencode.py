import os
import secrets
import stat
import tempfile
from collections.abc import Mapping
from enum import StrEnum
from importlib.resources import files
from pathlib import Path

import click
from pydantic import BaseModel, ConfigDict, Field

from ocint.daemon.config import DaemonConfig, DaemonContext


class OpenCodeProviderOptions(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    base_url: str | None = Field(default=None, alias="baseURL")


class OpenCodeModelOptions(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    reasoning_effort: str | None = Field(default=None, alias="reasoningEffort")
    reasoning_summary: str | None = Field(default=None, alias="reasoningSummary")


class OpenCodeModalities(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    input: list[str] = Field(default_factory=list)
    output: list[str] = Field(default_factory=list)


class OpenCodeProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    name: str
    options: OpenCodeModelOptions = Field(default_factory=OpenCodeModelOptions)
    modalities: OpenCodeModalities = Field(default_factory=OpenCodeModalities)


class OpenCodeProvider(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    npm: str | None = None
    options: OpenCodeProviderOptions = Field(default_factory=OpenCodeProviderOptions)
    models: Mapping[str, OpenCodeProviderModel] = Field(default_factory=dict)


class OpenCodeSourceAgentOptions(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    service_tier: str | None = Field(default=None, min_length=1, alias="serviceTier")


class OpenCodeSourceBuildAgent(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    options: OpenCodeSourceAgentOptions = Field(default_factory=OpenCodeSourceAgentOptions)


class OpenCodeSourceAgents(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    build: OpenCodeSourceBuildAgent = Field(default_factory=OpenCodeSourceBuildAgent)


class OpenCodeSourceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    model: str
    provider: Mapping[str, OpenCodeProvider]
    agent: OpenCodeSourceAgents = Field(default_factory=OpenCodeSourceAgents)


class RestrictedOpenCodeAgentOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    service_tier: str = Field(min_length=1, alias="serviceTier")


class RestrictedOpenCodeBuildAgent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    options: RestrictedOpenCodeAgentOptions


class RestrictedOpenCodeAgents(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    build: RestrictedOpenCodeBuildAgent | None = None


class OpenCodePermission(BaseModel):
    model_config = ConfigDict(frozen=True)
    fallback: str = Field(validation_alias="*", serialization_alias="*")
    read: str
    edit: str
    glob: str
    grep: str
    list: str
    external_directory: Mapping[str, str]
    webfetch: str
    websearch: str
    bash: str
    question: str


class StaticOpenCodePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")
    schema_url: str = Field(validation_alias="$schema", serialization_alias="$schema")
    share: str
    instructions: list[str]
    plugin: list[str]
    agent: RestrictedOpenCodeAgents
    lsp: bool
    formatter: bool
    permission: OpenCodePermission


class RestrictedOpenCodeConfig(StaticOpenCodePolicy):
    model: str
    provider: Mapping[str, OpenCodeProvider]


class CoordinatorOpenCodePermission(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)
    fallback: str = Field(validation_alias="*", serialization_alias="*")
    read: str
    list: str
    glob: str
    grep: str
    webfetch: str
    websearch: str
    edit: str
    write: str
    patch: str
    bash: str
    shell: str
    external_directory: Mapping[str, str]
    question: str


class CoordinatorStaticOpenCodePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")
    schema_url: str = Field(validation_alias="$schema", serialization_alias="$schema")
    share: str
    instructions: list[str]
    plugin: list[str]
    mcp: Mapping[str, str]
    agent: RestrictedOpenCodeAgents
    lsp: bool
    formatter: bool
    permission: CoordinatorOpenCodePermission


class CoordinatorRestrictedOpenCodeConfig(CoordinatorStaticOpenCodePolicy):
    model: str
    provider: Mapping[str, OpenCodeProvider]


class OpenCodeSelection(BaseModel):
    model_config = ConfigDict(frozen=True)
    model: str
    provider_name: str
    provider: OpenCodeProvider


class PrivateFilePurpose(StrEnum):
    DAEMON_CONFIG = "daemon config"
    SOURCE_OPENCODE_CONFIG = "source OpenCode config"
    OPENCODE_AUTH = "OpenCode auth"
    MANAGED_CONFIG = "managed configuration"


class PrivateFileRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: Path
    purpose: PrivateFilePurpose
    mode: int = 0o600


class ValidatedPrivateFile(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: Path
    purpose: PrivateFilePurpose


def canonical_file_path(path: Path) -> Path:
    expanded = path.expanduser().absolute()
    return expanded.parent.resolve() / expanded.name


def validate_private_file(requirement: PrivateFileRequirement) -> ValidatedPrivateFile:
    path = canonical_file_path(requirement.path)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise click.ClickException(f"{requirement.purpose.value} must exist as a private file: {path}") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != requirement.mode
    ):
        raise click.ClickException(
            f"{requirement.purpose.value} must be a user-owned regular non-symlink "
            f"mode-{requirement.mode:04o} file: {path}"
        )
    return ValidatedPrivateFile(path=path, purpose=requirement.purpose)


def private_file_is_valid(requirement: PrivateFileRequirement) -> bool:
    try:
        validate_private_file(requirement)
    except click.ClickException:
        return False
    return True


def policy_bytes() -> bytes:
    resource = files("ocint.daemon").joinpath("opencode.daemon.json")
    if not resource.is_file():
        raise click.ClickException(f"packaged OpenCode policy resource is missing: {resource}")
    return resource.read_bytes()


def policy_resource_path() -> str:
    return str(files("ocint.daemon").joinpath("opencode.daemon.json"))


def coordinator_policy_bytes() -> bytes:
    resource = files("ocint.daemon").joinpath("opencode.coordinator.json")
    if not resource.is_file():
        raise click.ClickException(f"packaged coordinator OpenCode policy resource is missing: {resource}")
    return resource.read_bytes()


def coordinator_policy_resource_path() -> str:
    return str(files("ocint.daemon").joinpath("opencode.coordinator.json"))


def load_policy() -> tuple[StaticOpenCodePolicy, bytes]:
    payload = policy_bytes()
    policy = StaticOpenCodePolicy.model_validate_json(payload)
    if policy.permission.external_directory != {"*": "deny"}:
        raise click.ClickException("packaged OpenCode policy must contain only the static external-directory deny rule")
    return policy, payload


def load_coordinator_policy() -> tuple[CoordinatorStaticOpenCodePolicy, bytes]:
    payload = coordinator_policy_bytes()
    policy = CoordinatorStaticOpenCodePolicy.model_validate_json(payload)
    if policy.permission.external_directory != {"*": "deny"}:
        raise click.ClickException("packaged coordinator OpenCode policy must deny every external directory")
    return policy, payload


def restricted_agent_config(service_tier: str | None) -> RestrictedOpenCodeAgents:
    if service_tier is None:
        return RestrictedOpenCodeAgents()
    return RestrictedOpenCodeAgents(
        build=RestrictedOpenCodeBuildAgent(options=RestrictedOpenCodeAgentOptions(serviceTier=service_tier))
    )


def restricted_opencode_config(
    policy: StaticOpenCodePolicy,
    model_name_with_provider: str,
    provider_name: str,
    provider: OpenCodeProvider,
    worktree_root: Path,
    service_tier: str | None = None,
) -> str:
    if not model_name_with_provider.startswith(f"{provider_name}/"):
        raise click.ClickException("selected OpenCode model does not match its provider")
    model_name = model_name_with_provider.removeprefix(f"{provider_name}/")
    model = provider.models.get(model_name)
    if model is None:
        raise click.ClickException(f"existing OpenCode model is not configured: {model_name_with_provider}")
    restricted_provider = provider.model_copy(update={"models": {model_name: model}})
    permission = policy.permission.model_copy(
        update={
            "external_directory": {
                "*": "deny",
                "/tmp/**": "allow",
                f"{worktree_root.resolve()}/**": "allow",
            }
        }
    )
    restricted = RestrictedOpenCodeConfig(
        **policy.model_dump(by_alias=False, exclude={"agent", "permission"}),
        agent=restricted_agent_config(service_tier),
        model=model_name_with_provider,
        provider={provider_name: restricted_provider},
        permission=permission,
    )
    return restricted.model_dump_json(by_alias=True, exclude_none=True, indent=2) + "\n"


def coordinator_restricted_opencode_config(
    policy: CoordinatorStaticOpenCodePolicy,
    model_name_with_provider: str,
    provider_name: str,
    provider: OpenCodeProvider,
) -> str:
    if not model_name_with_provider.startswith(f"{provider_name}/"):
        raise click.ClickException("selected OpenCode model does not match its provider")
    model_name = model_name_with_provider.removeprefix(f"{provider_name}/")
    model = provider.models.get(model_name)
    if model is None:
        raise click.ClickException(f"existing OpenCode model is not configured: {model_name_with_provider}")
    restricted = CoordinatorRestrictedOpenCodeConfig(
        **policy.model_dump(by_alias=False),
        model=model_name_with_provider,
        provider={provider_name: provider.model_copy(update={"models": {model_name: model}})},
    )
    return restricted.model_dump_json(by_alias=True, exclude_none=True, indent=2) + "\n"


def write_private_file(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def upsert_private_environment(path: Path, assignments: Mapping[str, str]) -> None:
    """Atomically update selected assignments while preserving every unrelated byte."""
    if os.path.lexists(path):
        validate_private_file(PrivateFileRequirement(path=path, purpose=PrivateFilePurpose.MANAGED_CONFIG))
    if any("\n" in value or "\r" in value for value in assignments.values()):
        raise click.ClickException("environment values must be single-line")
    content = path.read_bytes().decode() if path.exists() else ""
    values = dict(assignments)
    seen: set[str] = set()
    rendered: list[str] = []
    for line in content.splitlines(keepends=True):
        name, separator, _value = line.rstrip("\r\n").partition("=")
        if separator and name in values:
            ending = line[len(line.rstrip("\r\n")) :]
            rendered.append(f"{name}={values[name]}{ending}")
            seen.add(name)
        else:
            rendered.append(line)
    result = "".join(rendered)
    missing = {name: value for name, value in values.items() if name not in seen}
    if missing:
        if result and not result.endswith(("\n", "\r")):
            result += "\n"
        result += "".join(f"{name}={value}\n" for name, value in missing.items())
    write_private_file(path, result)


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
        raise click.ClickException(f"managed directory must be a user-owned regular directory: {path}")
    path.chmod(0o700)


def ensure_auth_symlink(source: Path, isolated_data_home: Path) -> Path:
    validated = validate_private_file(PrivateFileRequirement(path=source, purpose=PrivateFilePurpose.OPENCODE_AUTH))
    ensure_private_directory(isolated_data_home)
    auth_directory = isolated_data_home / "opencode"
    ensure_private_directory(auth_directory)
    target = auth_directory / "auth.json"
    if os.path.lexists(target):
        if not target.is_symlink() or target.lstat().st_uid != os.getuid() or target.resolve() != validated.path:
            raise click.ClickException(f"managed OpenCode auth link is unsafe: {target}")
        return target
    temporary = auth_directory / f".auth.json.{secrets.token_hex(8)}"
    try:
        temporary.symlink_to(validated.path)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def configured_opencode_selection(context: DaemonContext) -> OpenCodeSelection:
    source_path = context.config_home / "opencode" / "opencode.json"
    validated = validate_private_file(
        PrivateFileRequirement(path=source_path, purpose=PrivateFilePurpose.SOURCE_OPENCODE_CONFIG)
    )
    source = OpenCodeSourceConfig.model_validate_json(validated.path.read_text())
    provider_name, separator, model_name = source.model.partition("/")
    provider = source.provider.get(provider_name)
    if not separator or provider is None or model_name not in provider.models:
        raise click.ClickException("selected OpenCode model/provider is not completely configured")
    return OpenCodeSelection(model=source.model, provider_name=provider_name, provider=provider)


def provision_configured_coordinator_runtime(context: DaemonContext, config: DaemonConfig) -> None:
    provision_coordinator_runtime(
        config,
        configured_opencode_selection(context),
        context.data_home / "opencode" / "auth.json",
    )


def provision_coordinator_runtime(
    config: DaemonConfig,
    selection: OpenCodeSelection,
    auth_source: Path,
) -> None:
    coordinator = config.coordinator
    service = coordinator.opencode
    policy, _payload = load_coordinator_policy()
    payload = coordinator_restricted_opencode_config(
        policy,
        selection.model,
        selection.provider_name,
        selection.provider,
    )
    for directory in (
        coordinator.workspace_root,
        service.xdg_config_home,
        service.config_file.parent,
        service.xdg_data_home,
        service.xdg_data_home / "opencode",
    ):
        ensure_private_directory(directory)
    ensure_auth_symlink(auth_source, service.xdg_data_home)
    write_private_file(service.config_file, payload)


def validate_coordinator_runtime(context: DaemonContext, config: DaemonConfig) -> None:
    try:
        selection = configured_opencode_selection(context)
        policy, _payload = load_coordinator_policy()
        expected = coordinator_restricted_opencode_config(
            policy,
            selection.model,
            selection.provider_name,
            selection.provider,
        )
    except (OSError, ValueError, click.ClickException) as error:
        raise RuntimeError(f"coordinator OpenCode policy validation failed: {error}") from error

    coordinator = config.coordinator
    service = coordinator.opencode
    try:
        validate_private_file(
            PrivateFileRequirement(path=service.config_file, purpose=PrivateFilePurpose.MANAGED_CONFIG)
        )
    except click.ClickException as error:
        raise RuntimeError(str(error)) from error
    if service.config_file.read_text() != expected:
        raise RuntimeError("coordinator OpenCode config does not exactly match the packaged restricted policy")
    for directory in (
        coordinator.workspace_root,
        service.xdg_config_home,
        service.config_file.parent,
        service.xdg_data_home,
        service.xdg_data_home / "opencode",
    ):
        if (
            directory.is_symlink()
            or not directory.is_dir()
            or directory.stat().st_uid != os.getuid()
            or stat.S_IMODE(directory.stat().st_mode) != 0o700
        ):
            raise RuntimeError(f"coordinator managed directory must be user-owned and mode 0700: {directory}")
    auth_source = context.data_home / "opencode" / "auth.json"
    auth_link = service.xdg_data_home / "opencode" / "auth.json"
    try:
        validated_auth = validate_private_file(
            PrivateFileRequirement(path=auth_source, purpose=PrivateFilePurpose.OPENCODE_AUTH)
        )
    except click.ClickException as error:
        raise RuntimeError(str(error)) from error
    if (
        not auth_link.is_symlink()
        or auth_link.lstat().st_uid != os.getuid()
        or auth_link.resolve() != validated_auth.path
    ):
        raise RuntimeError(f"coordinator OpenCode auth link is unsafe: {auth_link}")
