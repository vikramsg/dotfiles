# Show Me Skill

This OpenCode skill was adapted on August 23, 2026, from HumanLayer's
[`show-me` skill](https://github.com/humanlayer/skills/blob/6ab9013a10c28f5046f7f999549cd5328a0b30d7/plugins/show-me/skills/show-me/SKILL.md)
at upstream commit `6ab9013a10c28f5046f7f999549cd5328a0b30d7`.

## How It Was Created

The upstream `SKILL.md` was copied into this repository and adapted for the
local OpenCode environment:

- Mermaid guidance and the Mermaid sequence diagram were replaced with a
  fixed-width ASCII sequence diagram because Mermaid cannot be previewed in
  the terminal UI.
- File-tree examples were converted from box-drawing characters to ASCII so
  every text diagram renders consistently in a terminal.
- The Claude-style `Bash(open ...)` example was replaced with tool-neutral
  browser guidance suitable for OpenCode.
- The description was updated to advertise ASCII diagrams.

The remaining workflow and examples intentionally follow the upstream skill.

## Installation

Install all managed OpenCode configuration, including this skill, from the
repository root:

```sh
just opencode
```

To install only this skill, run the dedicated recipe from `skills/`:

```sh
just install show-me
```

This links the skill to `~/.config/opencode/skills/show-me` for global OpenCode
discovery.

## Upstream License

MIT License

Copyright (c) 2026 HumanLayer

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
