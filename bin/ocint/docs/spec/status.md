# State Accounting

`ocint state summary` is OpenCode-compatible and session-authoritative: it uses
`SUM(session.cost)` for sessions filtered by the `session.time_updated` cutoff.
A qualifying session contributes its lifetime aggregates, not only usage created
inside the window.

`ocint state detailed` is message-attributed. Its project, agent, and
project/agent groups use assistant-message `message.data.cost` and token data,
filtered by `message.time_created`. Project groups join `session.project_id` to
`project.worktree`. Agent groups use the immutable historical
`message.data.agent`; `session.parent_id` classifies each message as root or
subagent. Project/agent groups retain both of those dimensions.

The detailed project, agent, and project/agent sections each reconcile to
`MESSAGE_ATTRIBUTED_COST`, but they may not equal summary/session cost. One
observed database reported session cost `$5107.520334` and assistant-message
cost `$5142.157824`; this document does not attribute a cause for that
difference.

## Window Semantics

`summary --days N` selects sessions by `session.time_updated` and includes their
lifetime `session.cost`. `detailed --days N` selects assistant messages by
`message.time_created` and sums `message.data.cost`. Their difference can include
older messages belonging to recently updated sessions and divergence between
OpenCode's session aggregates and persisted message costs.
This is because session dates are based on most recent event in session, but there can be agent calls in that session that are older and do not belong to same window.

OpenCode's overview uses sessions, while its models grouping sums assistant
message costs.
