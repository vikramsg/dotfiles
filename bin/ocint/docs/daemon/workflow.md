# Daemon Pull Request Workflow

```text
systemd timer -> one daemon invocation -> one GitHub poll
                                      |
labelled issue -> authorize -> persist comments/prompt -> permanent job
                                      |
private OpenCode session -> validate -> commit -> explicit SSH push
                                      |
create/reuse owned PR -> marker-protected response -> address batch
                                      |
unchanged idle generation for 60s -> normal two-server shutdown
```

Initial work includes title, body, and chronological authorized comments.
Follow-ups batch new chronological actor-attributed comments, retain the newest
as the durable anchor, and reuse the original session, worktree, branch, and PR.
Each prompt includes GitHub comment IDs, and each successful push advances the
durable Git baseline before publication.
Push state, pull-request stage, and the new baseline form one durable checkpoint.
Comments arriving during an active batch wait for the next invocation. A closed
or merged owned PR errors the batch before execution and is never replaced.
