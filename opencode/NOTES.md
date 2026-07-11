1. Permission issues
    * even after giving *.local permissions it keeps doing arbitrary permission questions
2. Add a teaching agent. That does not read files and only answers based on idiomatic usage
3. Create a plugin that auto approves any read/glob access to .local, .config... etc
    * And auto denies everything else
4. The implementer, since it creates tests first, always then creates backward compatiblity shims after

## Prompts

1. Give me component map + interface sketch of change

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
