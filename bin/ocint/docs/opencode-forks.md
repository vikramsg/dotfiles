# OpenCode Forks

## Purpose

This document records source and database references for OpenCode manual fork
behavior. It is limited to what OpenCode source and the inspected local OpenCode
database show about fork creation, persisted fields, and source-session
traceability.

## Source Snapshot

- OpenCode repository: `https://github.com/anomalyco/opencode.git`
- Inspected commit: `f52424e05fab0edddb4462112ceb02044085f903`
- Local checkout used for source reads:
  `/tmp/research-opencode-anomalyco-20260702`
- Local database queried read-only:
  `/home/vikram_orbio_earth/.local/share/opencode/opencode.db`

## Fork Flow

### API

The session route map defines `fork` as `/session/:sessionID/fork`. The HTTP API
registers it as a `POST` endpoint that accepts either no content or `ForkPayload`
and returns `Session.Info`. `ForkPayload` is `Session.ForkInput` with `sessionID`
omitted, so the request path supplies the source `sessionID` and the payload can
carry optional `messageID`. [S1] [S2] [S3]

The CLI `run --fork` and ACP fork path both call `sdk.session.fork(...)` with a
source `sessionID`. [S4] [S5]

### Handler

The HTTP handler decodes the optional payload and calls `session.fork({
sessionID, messageID })`. Empty raw bodies are accepted and handled as a fork
without `messageID`. [S6]

### Service

`Session.fork` reads the original session, derives a fork title with
`getForkedTitle`, creates a new session, then copies messages and parts into the
new session. The new session is created without `parentID`. Each copied message
gets a new message ID; assistant `parentID` fields are rewritten through an
in-memory ID map; each copied part gets a new part ID; compaction
`tail_start_id` is rewritten through the same map. [S7] [S8]

`getForkedTitle` appends ` (fork #1)` to a title without a fork suffix and
increments an existing ` (fork #N)` suffix to ` (fork #(N+1))`. [S7]

The service reads source messages through `Session.messages`, which pages the
projected `message` table by `time_created` and ID. [S9]

## Storage Schemas

### Session

`SessionTable` contains `id`, `project_id`, `workspace_id`, `parent_id`, `slug`,
`directory`, `path`, `title`, `version`, summary fields, `metadata`, cost/token
fields, `revert`, `permission`, `agent`, `model`, timestamps, and archive or
compaction times. The listed fields do not include a fork source session ID or a
fork source message ID. [S10]

`parent_id` is present in the session schema, but manual forks do not set it in
`Session.fork`. Subagent/task sessions do set `parentID` when creating child
sessions. [S8] [S11]

### Message

`MessageTable` stores `id`, `session_id`, timestamps, and JSON `data`. The
projector writes `message.time_created` from `event.data.info.time.created` for
`message.updated` events. [S12] [S13]

### Part

`PartTable` stores `id`, `message_id`, `session_id`, timestamps, and JSON `data`.
The projector writes `part.time_created` from `event.data.time` for
`message.part.updated` events. [S12] [S13]

### Event

`EventTable` stores `id`, `aggregate_id`, `seq`, `type`, and JSON `data`.
`EventSequenceTable` stores the latest sequence per aggregate. [S14]

The session event schema defines `session.created`, `session.updated`,
`session.deleted`, `message.updated`, `message.removed`, `message.part.updated`,
and `message.part.removed` in the referenced event object. No `session.fork` event
is defined there. [S15]

## Database References

### Tables

The inspected database contains `session`, `message`, `part`, `event`, and
`session_message` tables. These read-only checks were used:

```sql
PRAGMA table_info(session);
PRAGMA table_info(message);
PRAGMA table_info(part);
PRAGMA table_info(event);
PRAGMA table_info(session_message);
```

The inspected `session` rows had 62 titles matching `* (fork #*)`; none of those
62 rows had `parent_id` or `metadata` populated.

```sql
SELECT
  count(*) AS fork_titles,
  sum(CASE WHEN metadata IS NOT NULL THEN 1 ELSE 0 END) AS forks_with_metadata,
  sum(CASE WHEN parent_id IS NOT NULL THEN 1 ELSE 0 END) AS forks_with_parent_id
FROM session
WHERE title GLOB '* (fork #*)';
```

The inspected database had 62 root sessions with messages older than the session
creation time, and every one of those root sessions also had a fork-suffix title.

```sql
SELECT count(DISTINCT s.id) AS root_sessions_with_pre_session_msg
FROM session s
JOIN message m ON m.session_id = s.id
WHERE s.parent_id IS NULL
  AND m.time_created < s.time_created;

SELECT count(*) AS nonfork_titles_with_pre
FROM session s
WHERE s.parent_id IS NULL
  AND s.title NOT GLOB '* (fork #*)'
  AND EXISTS (
    SELECT 1
    FROM message m
    WHERE m.session_id = s.id
      AND m.time_created < s.time_created
  );
```

### Queries

This query identifies root sessions whose projected messages predate their own
session creation time and whose current title has a generated fork suffix:

```sql
SELECT s.id, s.title, s.time_created, count(m.id) AS copied_messages
FROM session s
JOIN message m
  ON m.session_id = s.id
 AND m.time_created < s.time_created
WHERE s.parent_id IS NULL
  AND s.title GLOB '* (fork #*)'
GROUP BY s.id;
```

This query lists candidate source sessions for a fork by title generation and
directory. For `fork #1`, the expected source title is the base title. For `fork
#N`, the expected source title is `fork #(N-1)`.

```sql
SELECT candidate.id, candidate.title, candidate.time_created
FROM session forked
JOIN session candidate
  ON candidate.directory = forked.directory
 AND candidate.time_created < forked.time_created
WHERE forked.id = :fork_session_id
  AND candidate.title = :expected_source_title;
```

## Stored Fields

Manual fork sessions have these source-backed stored fields and row patterns in
the inspected code and database:

- a generated title suffix from `getForkedTitle`;
- no `parent_id` set by `Session.fork`;
- copied messages whose `message.time_created` can predate the new session's
  `session.time_created`;
- new message IDs and part IDs generated during copy;
- no persisted source-session or source-message field in `SessionTable`.

## Source Limits

The fork API receives a source `sessionID`, but `Session.fork` does not persist
that source ID into the new session row, message rows, part rows, or a dedicated
fork event. [S3] [S8] [S10] [S14] [S15]

When several candidate sessions have the expected generated title and identical
copied prefix at the fork boundary, the stored data does not prove which session
ID was passed to the fork API. Current projected rows can also diverge after a
fork because source sessions can continue changing after the copy.

## Source References

- [S1] `SessionPaths.fork`: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/server/routes/instance/httpapi/groups/session.ts#L78-L90
- [S2] `ForkPayload`: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/server/routes/instance/httpapi/groups/session.ts#L55-L60
- [S3] `ForkInput`: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/session/session.ts#L273-L276
- [S4] CLI `--fork` call sites: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/cli/cmd/run.ts#L469-L504
- [S5] ACP fork call site: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/acp/service.ts#L354-L384
- [S6] HTTP fork handler: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts#L206-L230
- [S7] `getForkedTitle`: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/session/session.ts#L161-L168
- [S8] `Session.fork`: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/session/session.ts#L693-L733
- [S9] `Session.messages`: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/session/session.ts#L830-L853
- [S10] `SessionTable`: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/core/src/session/sql.ts#L22-L65
- [S11] subagent `parentID`: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/tool/task.ts#L142-L158
- [S12] `MessageTable` and `PartTable`: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/core/src/session/sql.ts#L68-L98
- [S13] message and part projectors: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/core/src/session/projector.ts#L262-L329
- [S14] `EventTable`: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/core/src/event/sql.ts#L4-L25
- [S15] session event schema: https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/schema/src/v1/session.ts#L571-L630
