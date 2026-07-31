## 5.6

- Too happy to invoke subagents
- I need to create commands that do not invoke subagents
- We need a build prompt that has sections about invoking subagents that have the same lessons as our orchestrator
  - Provide full context to implementation agent, especially if any decisions have already been made.
  - Ask it to provide all decisions that it did during implementation not already decided 
- Need more control
  - Planner should be smaller and always instruction to add implementation notes.md 
- docs, tickets everything leans how not what. Do not write a plan in a doc unless its specifically a plan

## Workflow

1. Keep `dotfiles` folder free for making quick changes. If required add a second worktree for other changes.

## Prompts

1. Give me component map + interface sketch of change
2. Next give me files changed, and patterns used
3. First tell me if before this plan we should do a Tidy, First pass and then update plan based on that.

## Agent requirements

1. For each project, the reviewer has to be much stronger.
2. Maybe the structure should be
    a. What is business logic
    b. What are the layers
    c. What existing patterns and interfaces are we using
    d. What new interfaces are we creating

## Abstractions

1. The reason to follow current developments is to be able to replicate them without needing to rethink all abstractions and interfaces
    - For eg. by just replicating `ctx` I don't need to think about what the abstractions are and what I need to do about performance.
    - The CLI structure is actually why keeping things open source is an issue. It is easily replicated.

## Docs

1. Docs actually require the same kind of domain slicing that code does.
  - Otherwise it just sprawls up
