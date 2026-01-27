# Agent Skills

This directory is used to author and manage agent skills following the [SKILL.md standard](https://opencode.ai/docs/skills). 

## Architecture

Skills in this directory are the source of truth. 
To make a skill available to OpenCode agents, it must be symlinked into the global configuration directory: `~/.config/opencode/skills/`.

## Management with `just`

The `justfile` provides a simple way to manage and test skills.

### Create a new skill
Scaffold a new skill directory and template:
```bash
just create <skill-name>
```

### Install a skill
To "activate" a skill globally:
```bash
just install <skill-name>
```

### Test skill discovery
Verify that OpenCode can discover and use a specific skill correctly:
```bash
just test <skill-name>
```
This command installs the skill, triggers an OpenCode prompt to load it, and verifies the tool call in the trace.

### List skills
To see what is available and what is currently linked:
```bash
just list
```

### Uninstall a skill
To remove the symlink:
```bash
just uninstall <skill-name>
```

## Creating a Skill manually

## Manual Example (OpenCode)

If you prefer to link manually:
```bash
ln -s "/path/to/dotfiles/skills/my-skill" ~/.config/opencode/skills/my-skill
```
