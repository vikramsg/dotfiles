# Daemon GitHub Boundary Example

GitHub is an outer provider. It owns GitHub API configuration, transport,
persistence, and translation between GitHub data and daemon domain messages. It
does not own task workflow or job execution.

```text
daemon/config.py
    |
    | composes GitHubConfig through the public facade
    v
daemon/github/__init__.py
    |
    | open_github_service(...)
    v
GitHub transport + repository + concrete operations
    |
    | GitHubGateway
    v
+----------------------+       +----------------------+
| TaskCoordinator      |       | JobExecutor          |
| observe and reply    |       | publish              |
+----------------------+       +----------------------+
          |                            |
          +---- shared daemon DTOs ----+
```

## Ownership

- `github/config.py` owns `GitHubConfig` and its external validation.
- `github/models.py` owns GitHub API DTOs and GitHub persistence models.
- `github/client.py` owns GitHub HTTP transport.
- `github/repository.py` owns durable GitHub mappings.
- `github/service.py` owns GitHub behavior and translation to shared daemon
  DTOs.
- `github/__init__.py` owns the supported facade, `GitHubGateway` contract, and
  the lifecycle factory that constructs concrete GitHub dependencies.
- `tasks/` owns ingestion, task persistence, authorization outcomes, replies,
  and task state transitions.
- The execution service owns job state, checkpoints, and publication outcomes.

## Allowed Flow

```text
config aggregate ---> GitHubConfig
daemon CLI ---------> GitHub facade factory
GitHub service ------> shared daemon DTOs
TaskCoordinator -----> consumer-owned source contract
JobExecutor ---------> consumer-owned publication contract
```

The CLI converts aggregate repository entries into the GitHub policy model
before constructing the feature. The GitHub implementation never receives
`DaemonConfig` or `RepositoryConfig`.

## Forbidden Flow

```text
github service -X-> DaemonConfig
github service -X-> tasks repository or task state
tasks          -X-> concrete GitHub modules
config import  -X-> eager client, repository, or service initialization
```

Declare these dependencies in `tach.toml`. Use pytest for observable behavior,
including configuration import safety, polling translation, authorization
outcomes, idempotent replies, publication refusal, and resource cleanup. Do not
use pytest to parse imports or duplicate Tach's dependency graph.
