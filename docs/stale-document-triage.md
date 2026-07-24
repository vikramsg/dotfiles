# Stale Document Triage

Documentation is stale when it no longer describes the repository's current
behavior or supported workflow. Age alone does not make a document stale. Use
this guide when a command, path, screenshot, architecture description, or
external reference appears out of date.

## Source Of Truth

Confirm the current behavior before editing the document. Prefer evidence in
this order:

1. Executable behavior and configuration in the repository.
2. Tests that describe supported behavior.
3. Current component documentation and help output.
4. Recent pull requests and commit history that explain intent.
5. Upstream documentation for external tools.

Do not preserve a statement only because another document repeats it. If the
sources disagree, identify the owning component and resolve the disagreement
before rewriting the documentation.

## Triage

For each suspected stale document:

1. Identify the exact claim that may be stale. Avoid treating the whole file as
   obsolete because one section is wrong.
2. Reproduce commands and workflows when it is safe to do so. For destructive,
   privileged, or environment-specific steps, inspect the implementation and
   tests instead.
3. Check referenced paths, command flags, configuration names, and links.
4. Determine the impact:
   - **High:** Following the document can lose data, weaken security, publish
     unintended changes, or break an installation.
   - **Medium:** The primary setup or operating workflow fails or gives the
     wrong result.
   - **Low:** Examples, links, terminology, or diagrams are inaccurate without
     blocking the workflow.
5. Choose one disposition and record enough evidence for review.

## Dispositions

### Update

Update the smallest stale section when the workflow is still supported. Keep
useful context and diagrams, and verify every changed example against the
current interface.

### Remove

Remove content when the behavior is no longer supported and no current reader
needs it. Also remove inbound links and references to the deleted content.

### Archive

Archive only when historical instructions still have a concrete audience, such
as users operating a supported older release. Add a prominent note that names
the applicable version or date and links to the current instructions. Git
history alone is usually sufficient; do not archive content merely to avoid
deleting it.

### Defer

Defer when the correct behavior cannot yet be established. Open a tracked
follow-up that names an owner, the unresolved question, the evidence already
checked, and the risk of leaving the document unchanged. Add a temporary
warning to high-impact content rather than silently leaving unsafe guidance in
place.

## Triage Record

Use this compact record in an issue or pull-request description:

```text
Document: <path and section>
Suspected stale claim: <specific statement, command, link, or diagram>
Current source of truth: <code, test, help output, or upstream reference>
Impact: <high | medium | low>
Disposition: <update | remove | archive | defer>
Verification: <commands run and links checked>
Follow-up: <owner and tracked work, or none>
```

## Completion Checklist

- The corrected text matches current behavior rather than planned behavior.
- Commands, paths, links, and cross-references were checked.
- Related documents were searched for the same stale claim.
- Removed or moved sections have no broken inbound links.
- Generated documentation was changed at its source, then regenerated.
- Repository documentation checks pass, when available.
