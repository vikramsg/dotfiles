---
name: skill-creator
description: Helps the user create, install, and test new OpenCode skills with a self-correction feedback loop.
license: MIT
compatibility: opencode
---

# Skill Creator

I help you manage the lifecycle of OpenCode skills in this repository, ensuring they are not just discoverable but functionally correct.

## What I do

### 1. Research & Scaffold
Before creating a skill, I:
- Read all provided documentation and READMEs.
- Research tool CLI help (e.g., `tool help <command>`) to learn correct syntax and schemas.
- Use `just create <name>` to set up the directory and `SKILL.md` template.

### 2. Implementation with Precision
I draft the `SKILL.md` to be extremely specific. For tools with complex inputs (like JSON schemas or specific flags), I include valid examples in the skill content to ensure the loading agent has a baseline.

### 3. Verification & Feedback Loop (CRITICAL)
After using `just install <name>`, I verify the skill by executing a functional test:
1. **Execute**: Run `opencode run "..."` with a prompt that exercises the skill's unique capabilities.
2. **Analyze**: If the command fails, I read the STDOUT/STDERR carefully.
3. **Compare**: I compare the error with the tool's documentation or help output.
4. **Fix**: I update the `SKILL.md` instructions to address the failure (e.g., "The tool expects 'items' not 'rows'").
5. **Retry**: Re-install and re-test until the functional task succeeds.

### 4. Lifecycle Management
- `just install <name>`: Symlink to global config.
- `just list`: Audit available and active skills.
- `just uninstall <name>`: Deactivate a skill.

## When to use me
Use this skill when you need to build a new capability that requires specific tool knowledge and verified execution. I am particularly useful for skills that wrap complex CLI tools.
