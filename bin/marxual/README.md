# marxual

`marxual` is a standalone Go Markdown viewer for the terminal.

It uses Bubble Tea for the TUI, Glamour for Markdown rendering, and `mermaid-ascii` to convert Mermaid code fences into ASCII diagrams before final rendering.

## Features

- Open Markdown from a file path.
- Read Markdown from stdin with `-`.
- Convert Mermaid fences to ASCII before rendering.
- Fall back gracefully when Mermaid conversion fails.
- Scroll long documents and rerender on terminal resize.
- Default to the built-in `tokyo-night` Glamour theme.
- Switch between built-in Glamour themes with `--style`.

## Build

From `bin/marxual`:

```bash
go build
```

Install into `~/.local/bin` from the repo root:

```bash
just marxual
```

## Usage

```bash
marxual README.md
marxual --style dracula README.md
cat README.md | marxual -
```

Available built-in styles:

- `ascii`
- `auto`
- `dark`
- `dracula`
- `tokyo-night`
- `light`
- `notty`
- `pink`

## Keys

- `q`: quit
- `j` / `k`: scroll down or up
- arrow keys: scroll
- `pgdn` / `pgup`: page down or up
- `g` / `G`: jump to top or bottom

## Development

From `bin/marxual`:

```bash
go test ./...
```
