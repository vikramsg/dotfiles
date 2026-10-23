# gocat

A lightweight, performance-first terminal image renderer written in Go supporting the **Kitty Graphics Protocol** (Ghostty / Kitty).

## Features

- **Fast Path (`t=f`)**: For local PNG files, sends file path control sequences directly to Ghostty/Kitty, bypassing sender-side decode/encode overhead (<0.04 ms internal latency).
- **Fallback Pipeline (`t=d`)**: Streaming decode, bilinear downscale, and speed-optimized PNG chunked base64 transmission for WebP, JPEG, GIF, and piped standard input.
- **Pure Go**: Zero cgo dependencies, fast cold start.

## Installation & Build

```bash
cd bin/gocat
go build -o gocat .
```

## Usage

```bash
# Render a local image (automatically selects fast path for PNGs)
./gocat path/to/image.png

# Render with target bounding box in pixels
./gocat --target 800x600 path/to/image.jpg
./gocat -t 720x420 path/to/image.png

# Pipe image via stdin
cat image.png | ./gocat -

# Force specific mode
./gocat --mode passthrough path/to/image.png
./gocat --mode fallback --target 600x400 path/to/image.png
```

## Options

- `-t, --target WxH`: Target bounding box in pixels (e.g. `800x600` or `720x420`). Aspect ratio is preserved.
- `-m, --mode [auto|passthrough|fallback]`: Rendering mode (`auto` by default).
- `-q, --quiet [0|1|2]`: Kitty quiet mode (default `2` to suppress terminal OK replies).
- `--cols C`: Target terminal columns (`c=N`).
- `--rows R`: Target terminal rows (`r=N`).
- `--timings`: Report processing stage timings to standard error.

## Benchmarks & Performance

See [EXPERIMENT_LOG.md](./EXPERIMENT_LOG.md) for full benchmark results and comparisons against `mcat`.

Override the default screenshot corpus when benchmarking another image set:

```bash
GOCAT_BENCH_CORPUS=/path/to/images go test -bench . -benchmem ./...
```
