---
name: ngrok-live-testing
description: Use ngrok with dedicated tmux windows and persistent sanitized logs to test real public callbacks against a local server. Use when diagnosing webhooks, event subscriptions, signatures, retries, forwarding, or live HTTP integrations.
---

# ngrok Live Testing

Use a real static ngrok endpoint to test one callback scenario at a time against
an isolated local server. Keep evidence from the local server and ngrok so a
missing callback is diagnosed at the correct boundary.

Load `tmux-terminal-testing` before creating terminal resources.

## Required Inputs

Establish these values before starting:

- local server command and working directory;
- loopback host, port, and readiness path;
- public ngrok URL and callback path;
- ngrok executable and configuration location;
- expected request method, authentication, and response;
- scenarios to exercise and the unique marker for each scenario;
- services that currently own the local port or static domain.

Do not guess channel type, event type, callback path, or provider identity. Query
or verify each external contract first.

## Safety Rules

- Inspect existing tmux windows, listeners, processes, and services first.
- Record whether every affected service was active and enabled before testing.
- Stop a pre-existing service only when the live test requires its port or
  static domain. Restore its original state during cleanup.
- Create new dedicated tmux windows. Record stable window and pane IDs.
- Kill only windows and processes created by this test.
- Never use `tmux kill-server`.
- Bind the local server and ngrok inspection API to loopback only.
- Never expose database, control API, debug, or ngrok inspection ports.
- Never print tokens, signing secrets, authorization headers, cookies, raw
  signatures, or unrelated request bodies.
- Never delete or recreate `.sqlite` or `.db` files.
- Do not suppress server or ngrok output during diagnostics.
- Preserve sanitized logs after cleanup.

## Evidence Directory

Create one private run directory outside the repository, for example:

```text
~/.local/state/<project>/ngrok-live/<UTC-run-id>/
├── server.log
├── ngrok.log
├── callbacks.jsonl
└── ngrok-requests.json
```

Require mode `0700` on the run directory and mode `0600` on every file. Use a
new run ID instead of truncating evidence from an earlier test.

`callbacks.jsonl` should contain one sanitized record per callback:

```text
received_at
method
path
response_status
authentication_valid
provider_event_id
event_type
event_subtype
provider_actor_id
provider_message_id
client_message_id
retry_number
retry_reason
scenario_marker
```

Omit credentials, authorization collections, raw signatures, and unrelated
payload fields.

## Preflight

Record the initial terminal and process state:

```bash
tmux -V
tmux list-sessions -F '#{session_id} #{session_name}'
tmux list-windows -a -F '#{session_id} #{window_id} #{window_name}'
command -v ngrok
ngrok version
ss -ltn
```

Verify the local port, ngrok inspection port `4040`, and static domain are not
owned by an unrelated process. If a managed service owns them, record its state
before stopping it.

Create separate tmux windows for the server and ngrok. Do not combine both
processes in one pane because their lifecycle and evidence must remain distinct.

## Start The Local Server

Start the local server before ngrok. Redirect stdout and stderr to `server.log`
while retaining useful output in its dedicated pane when possible.

The server must:

- bind only to the expected loopback host and port;
- expose only the callback route needed by the scenario;
- enforce the real authentication contract;
- return the provider-required response within its deadline;
- emit sanitized structured callback records;
- flush each record before responding when the test checks durability.

Verify loopback readiness directly. A readiness GET may legitimately return
`404` or `405` when the public callback accepts only POST; document the expected
status before treating it as healthy.

## Start ngrok

Start ngrok in its own tmux window after local readiness succeeds. Use the
configured static URL and exact local destination.

Enable local inspection for diagnostics:

```text
ngrok http --url=<static-url> --inspect=true http://127.0.0.1:<port>
```

Keep `127.0.0.1:4040` local. Redirect ngrok output to `ngrok.log`; do not discard
stdout or stderr.

Verify all three boundaries independently:

1. The local readiness request reaches the server.
2. The public URL reaches the server through ngrok.
3. The ngrok inspection API records the public request.

Do not begin provider scenarios until these checks pass.

## Run Scenarios

Use a unique marker for every scenario. Run one scenario, inspect evidence, and
only then continue to the next scenario.

For each scenario:

1. Record the scenario marker and expected provider identity.
2. Trigger the real external action.
3. Poll the server log and ngrok inspection API deliberately.
4. Correlate provider message ID, event ID, client message ID, and timestamp.
5. Confirm authentication result and HTTP status.
6. Save a metadata-only ngrok request snapshot.
7. Record whether retries occurred and why.

Do not infer that no request arrived merely because application state is empty.
Check ngrok and the local receiver independently.

## Diagnose By Boundary

Use the first missing boundary as the root of the failure:

```text
External provider
       |
       v
Static ngrok domain  -> ngrok inspection
       |
       v
Loopback server      -> server log
       |
       v
Authentication       -> callback JSONL
       |
       v
Application state
```

- No ngrok request: inspect provider subscription, event type, resource type,
  app identity, installation, membership, and whether changes were saved.
- ngrok request but no server request: inspect forwarding destination, local
  listener, tunnel ownership, and process lifetime.
- Server request with authentication failure: inspect exact raw-body handling,
  timestamp tolerance, and credential/app identity without logging secrets.
- Server returns non-2xx: inspect parsing and provider deadline behavior.
- Server returns 2xx but application state is absent: inspect translation,
  authorization, deduplication, and persistence.
- Retries appear: correlate retry headers with the original event ID before
  creating another test message.

## Cleanup

Cleanup is mandatory after success, failure, or interruption:

1. Stop the ngrok process created by the test.
2. Stop the local server created by the test.
3. Kill only the recorded test windows.
4. Verify test listeners and processes are gone.
5. Restore every service to its recorded initial active/enabled state.
6. Verify pre-existing tmux resources still exist.
7. Keep the private evidence directory.

Production ngrok must return to inspection-disabled operation after diagnostics.

## Report

Report:

- run ID and evidence paths;
- created tmux window and pane IDs;
- local and public readiness results;
- each scenario marker and observed callback identity;
- ngrok status, server status, authentication result, and retries;
- the first failed boundary when a scenario did not pass;
- services stopped and restored;
- confirmation that all test-owned resources were closed.
