# Plan: PDF Processor Skill Implementation

## Goal
Create a functional `pdf-processor` skill using the `skill-creator` agent, incorporating a feedback loop to ensure the skill handles `pdfcpu` JSON syntax correctly.

## Stopping Point
I will stop once:
1. The `pdf-processor` skill is created, installed, and active in the global config.
2. A valid `travel_claim.pdf` is generated containing a travel expense table and the merged `ticket.pdf`.
3. `pdfcpu info travel_claim.pdf` confirms the document structure is correct.

## Phases

### Phase 1: Brain Upgrade (Skill Creator)
- Update `skills/skill-creator/SKILL.md` to include mandates for:
    - **Research**: Read tool help (`pdfcpu help`) and documentation before writing instructions.
    - **Testing**: Run a real task using `opencode run` after installation.
    - **Feedback Loop**: If the task fails, read the error output, compare with documentation, update `SKILL.md`, and retry.
- **Acceptance Criteria**: `just test skill-creator` passes.

### Phase 2: Implementation (PDF Processor)
- Delegate to a sub-agent using `skill-creator` to:
    - Scaffold `pdf-processor`.
    - Create `SKILL.md` based on `pdf-processor/README.md` and `pdfcpu help create`.
    - Install the skill.
- **Acceptance Criteria**: `skills/pdf-processor/SKILL.md` exists.

### Phase 3: Verification (The Travel Claim)
- Use the new `pdf-processor` skill to:
    - Generate a JSON definition for a travel expense table (Date, Item, Amount).
    - Create a PDF from that JSON.
    - Merge the resulting PDF with `/Users/vikramsingh/Projects/Personal/dotfiles/ticket.pdf`.
- **Feedback Loop**: If `pdfcpu create` or `pdfcpu merge` fails, the agent must update its own skill instructions to fix the error and try again.
- **Acceptance Criteria**: `travel_claim.pdf` is generated and contains both the table and the ticket.

### Phase 4: Final Audit
- Inspect the final PDF with `pdfcpu info`.
- Verify the `SKILL.md` content for accuracy.
