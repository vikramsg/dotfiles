# markdown-viewer

Render Markdown files or stdin in a Textual app.

## Install

```bash
uv tool install ./bin/markdown_viewer --force
```

## Usage

Render a file:

```bash
markdown-viewer README.md
```

Render piped input:

```bash
cat README.md | markdown-viewer -
```

Hide the table of contents:

```bash
markdown-viewer README.md --no-toc
```

## Test

From this directory:

```bash
uv run pytest
```
