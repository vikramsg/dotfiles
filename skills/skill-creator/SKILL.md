---
name: skill-creator
description: Helps the user create, install, and test new OpenCode skills.
license: MIT
compatibility: opencode
---

# Skill Creator

I help you manage the lifecycle of OpenCode skills in this repository. 

## What I do

### 1. Scaffold New Skills
I use `just create <name>` to set up a new skill directory and `SKILL.md` template.
When creating a skill, I ensure:
- The name is lowercase alphanumeric with hyphens (e.g., `git-release`).
- The `SKILL.md` has the required frontmatter (`name`, `description`).

### 2. Install/Activate Skills
I use `just install <name>` to symlink the skill to the global configuration directory (`~/.config/opencode/skills/`). This makes the skill available globally to all OpenCode agents.

### 3. Verify Skills
I use `just test` to run a non-interactive verification suite. This verifies that:
- The skill discovery mechanism is working.
- Agents can correctly load and follow skill instructions.

### 4. Manage Links
I use `just list` to audit available skills and active links. I use `just uninstall <name>` to deactivate a skill by removing its symlink.

## When to use me
Use this skill whenever you want to:
- Create a new reusable set of instructions (a "skill").
- "Activate" a skill from this repo to your global OpenCode environment.
- Verify that your skill installation is working correctly.
