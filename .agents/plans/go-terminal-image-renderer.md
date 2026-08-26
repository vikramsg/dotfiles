# Performance-First Go Terminal Image Renderer

## Status

Proposed. No renderer implementation has been started.

## Goal

Build the smallest useful still-image renderer in Go that displays images in terminals supporting the Kitty graphics protocol, with performance treated as a first-order requirement.

The initial target is local display in Ghostty. The implementation should remain usable in Kitty-compatible terminals without attempting to reproduce Chafa's broad terminal, image-format, animation, and character-art feature set.

## User Intent

The desired result is not an FZF implementation and is not a Chafa clone. FZF was only a clue leading to the currently used image-rendering path.

The project should:

- display a still image in a Kitty-protocol terminal;
- be implemented primarily in Go;
- minimize startup, decode, resize, encode, and transmission latency;
- make decisions from benchmarks and observed implementations rather than protocol capabilities alone;
- stay small enough that each added feature has a demonstrated need.

## Non-Goals For V1

- FZF integration.
- Symbol, Braille, half-block, or ASCII rendering.
- Sixel and iTerm2 protocols.
- Animation or video.
- SVG, AVIF, JPEG XL, TIFF, or PDF.
- Tmux passthrough and Unicode placeholders.
- Terminal capability databases comparable to Chafa's.
- Grids, labels, hyperlinks, interactive navigation, or image editing.
- Eight-, sixteen-, or 256-color output.
- Chafa-compatible command-line options.

## Current Repository Context

The current shell configuration delegates previews to Homebrew's `fzf-preview.sh` from `zsh/.zshrc`. That script prefers `kitten icat`, then invokes Chafa. The Herdr FZF path sets `TERM=xterm-kitty`, causing Chafa to choose Kitty graphics. The tmux file finder has a separate `bat`/`cat` preview and does not render images.

These details explain how Chafa was discovered but are not implementation requirements for the new renderer.

## What Chafa Actually Does

Chafa 1.18.2 contains several mostly independent systems:

- media loaders for many image formats;
- terminal detection and protocol selection;
- image scaling, alpha processing, preprocessing, dithering, and color conversion;
- symbol rendering using an internal 8x8 sample matrix per terminal cell;
- Kitty, Sixel, iTerm2, and ANSI symbol encoders;
- animation, grids, labels, cursor management, and multiplexer passthrough.

Its symbol path downsamples each terminal cell to 8x8 pixels, extracts two colors, converts the cell into a 64-bit foreground/background mask, finds candidate glyph masks by Hamming distance, evaluates candidates using pixel color error, and emits optimized ANSI attributes. Relevant code:

- [8x8 work cells and mask generation](https://github.com/hpjansson/chafa/blob/571246107ac9cb88dee2c6c69cda5dd9805820da/chafa/internal/chafa-work-cell.c#L40-L143)
- [candidate search](https://github.com/hpjansson/chafa/blob/571246107ac9cb88dee2c6c69cda5dd9805820da/chafa/chafa-symbol-map.c#L1152-L1253)
- [glyph and color evaluation](https://github.com/hpjansson/chafa/blob/571246107ac9cb88dee2c6c69cda5dd9805820da/chafa/chafa-canvas.c#L164-L314)
- [ANSI emission](https://github.com/hpjansson/chafa/blob/571246107ac9cb88dee2c6c69cda5dd9805820da/chafa/internal/chafa-canvas-printer.c#L140-L252)

None of this symbol machinery is needed to display a real image through Kitty graphics.

Chafa's Kitty path scales into an RGBA canvas and directly base64-encodes the raw pixel data:

- [RGBA canvas and parallel scaling](https://github.com/hpjansson/chafa/blob/571246107ac9cb88dee2c6c69cda5dd9805820da/chafa/internal/chafa-kitty-canvas.c#L105-L212)
- [direct chunk encoding](https://github.com/hpjansson/chafa/blob/571246107ac9cb88dee2c6c69cda5dd9805820da/chafa/internal/chafa-kitty-canvas.c#L215-L288)

This path is computationally respectable but produces a large protocol stream because it does not PNG-compress the resized raster.

## Kitty Protocol Minimum

The protocol-level minimum is:

1. Produce PNG, RGB, or RGBA image data.
2. Base64-encode it.
3. Split direct transfers into protocol chunks.
4. Send an `a=T` transmit-and-display command.

The official specification supports three transmission media:

- direct data through terminal escape codes;
- a local file or temporary file;
- POSIX shared memory.

Protocol reference: [Kitty terminal graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/).

Protocol support is not evidence that a transport is fastest for this workload. Direct, file, and shared-memory paths must be measured end-to-end in Ghostty before selecting a local default.

## Ghostty Receiver Findings

Ghostty already applies SIMD and caching at the receiver-side points that matter most for Kitty graphics. Sender work should complement these paths rather than duplicate or optimize around them blindly.

### Direct Base64 Decode

Ghostty decodes direct-transfer base64 payloads in place. Its parser replaces the encoded payload with decoded bytes in the same allocation, avoiding a second image-sized receiver buffer. The decoder uses `simdutf` when available and falls back to a scalar implementation otherwise.

Sources:

- [in-place Kitty payload decode](https://github.com/ghostty-org/ghostty/blob/9c3ec931d64561a8407dde7ac984ce156ae91539/src/terminal/kitty/graphics_command.zig#L262-L289)
- [SIMD base64 implementation](https://github.com/ghostty-org/ghostty/blob/9c3ec931d64561a8407dde7ac984ce156ae91539/src/simd/base64.zig#L9-L37)

Implication: direct transmission still pays sender-side base64 encoding and 33 percent wire expansion, but receiver-side decoding is already optimized. The Go sender's useful direct-path optimization is fast base64 encoding, not escape-sequence construction.

### Local File And Shared Memory

Ghostty accepts file and shared-memory Kitty transports without carrying image bytes as base64 through the PTY. It currently copies the file or shared-memory content into owned storage before later processing.

Source: [Ghostty local transport loading](https://github.com/ghostty-org/ghostty/blob/9c3ec931d64561a8407dde7ac984ce156ae91539/src/terminal/kitty/graphics_image.zig#L147-L189).

Implication: local transport is not zero-copy in Ghostty today, but it avoids sender-side base64, base64 wire expansion, PTY transfer of image bytes, and receiver-side base64 decode. For an existing local PNG, `t=f` is the strongest available sender optimization because it can avoid sender decode, resize, PNG encode, and base64 entirely. End-to-end measurement must still account for Ghostty reading, copying, decoding, and scaling the original PNG.

### PNG Decode

Ghostty decodes PNG once into RGBA using Wuffs.

Source: [Ghostty PNG decode path](https://github.com/ghostty-org/ghostty/blob/9c3ec931d64561a8407dde7ac984ce156ae91539/src/terminal/sys.zig#L15-L53).

Implication: sending PNG shifts one decode to Ghostty and avoids transmitting raw RGBA. Re-encoding a resized PNG on the sender may reduce bytes, but an unchanged local PNG over `t=f` avoids all sender image processing and lets Ghostty perform its existing single decode.

### GPU Texture Cache

Ghostty retains decoded images as GPU textures and tracks each texture by image ID plus generation. Existing textures are reused until their generation changes, avoiding repeated upload on every render.

Source: [Ghostty image texture cache](https://github.com/ghostty-org/ghostty/blob/9c3ec931d64561a8407dde7ac984ce156ae91539/src/renderer/image.zig#L853-L877).

Implication: a persistent sender should transmit an image once, retain a stable image ID, and use placement operations for repeated display. It should change the image generation only when pixels change and explicitly delete images when they are no longer needed.

## Implementations Surveyed

### Kitty `icat`

Kitty's current `icat` is written in Go. It:

- avoids converting an unchanged, single-frame PNG when no transformation is needed;
- selects RGB for opaque decoded images and RGBA when alpha is required;
- probes direct, file, and shared-memory transport support;
- selects shared memory for generated in-memory data when available, otherwise file transport, then direct streaming;
- conditionally zlib-compresses non-PNG direct payloads larger than 2 KiB, retaining compression only if it reduces size;
- parallelizes independent input files.

Sources:

- [PNG fast path and decode/resize path](https://github.com/kovidgoyal/kitty/blob/54416498c89e1d07e5079c49d15470dd0d947ce7/kittens/icat/process_images.go#L156-L174)
- [target sizing and conversion](https://github.com/kovidgoyal/kitty/blob/54416498c89e1d07e5079c49d15470dd0d947ce7/kittens/icat/process_images.go#L202-L231)
- [transport implementations and selection](https://github.com/kovidgoyal/kitty/blob/54416498c89e1d07e5079c49d15470dd0d947ce7/kittens/icat/transmit.go#L85-L165)
- [transport priority](https://github.com/kovidgoyal/kitty/blob/54416498c89e1d07e5079c49d15470dd0d947ce7/kittens/icat/transmit.go#L254-L277)
- [capability probing](https://github.com/kovidgoyal/kitty/blob/54416498c89e1d07e5079c49d15470dd0d947ce7/kittens/icat/detect.go#L46-L108)
- [conditional zlib compression](https://github.com/kovidgoyal/kitty/blob/54416498c89e1d07e5079c49d15470dd0d947ce7/tools/tui/graphics/command.go#L271-L309)

Important benchmark & profiling result: its image-processing path was slow (~1.8–3 seconds) on the screenshot corpus. Profiling revealed the bottleneck was **not** Go, PNG decompression, or transport, but **full-resolution ICC color profile conversion** in `github.com/kovidgoyal/imaging`. Applying ICC curve math (`pow`/`log`/`exp`) on millions of source pixels accounted for ~81% of CPU time (~1.6s). Its transport design is useful evidence; its decode-order image processing is not a target to copy.

### mcat

mcat 0.6.4 was the fastest tested application. Its Kitty still-image path:

- resizes with the Rust `fast_image_resize` library;
- encodes the resized image as PNG;
- base64-encodes the PNG;
- writes Kitty protocol chunks of 4096 encoded bytes.

Sources:

- [resize path](https://github.com/Skardyy/mcat/blob/dd268f1322bdab97029208bbb57a4118bc7d7bef/crates/rasteroid/src/image_extended.rs#L47-L91)
- [PNG and Kitty encoding](https://github.com/Skardyy/mcat/blob/dd268f1322bdab97029208bbb57a4118bc7d7bef/crates/rasteroid/src/kitty_encoder.rs#L130-L169)
- [chunk writer](https://github.com/Skardyy/mcat/blob/dd268f1322bdab97029208bbb57a4118bc7d7bef/crates/rasteroid/src/kitty_encoder.rs#L61-L128)

mcat is the current performance baseline, not proof that every individual design choice is optimal. Its complete pipeline won the benchmark.

### timg

timg 1.6.3:

- uses specialized decoders and can perform decoder-assisted JPEG downscaling;
- converts its final framebuffer to PNG;
- defaults to compression level 1 for encoding speed;
- runs compression and base64 generation in a worker pool;
- queues completed buffers through an ordered asynchronous writer;
- uses bounded IDs for animation to avoid overwhelming terminal image stores.

Sources:

- [decoder-assisted JPEG scaling](https://github.com/hzeller/timg/blob/aa22227b5dd8e146c2af658460c09b5e516765f9/src/jpeg-source.cc#L183-L215)
- [speed-oriented PNG compression](https://github.com/hzeller/timg/blob/aa22227b5dd8e146c2af658460c09b5e516765f9/src/timg-png.h#L27-L41)
- [asynchronous PNG and Kitty encoding](https://github.com/hzeller/timg/blob/aa22227b5dd8e146c2af658460c09b5e516765f9/src/kitty-canvas.cc#L126-L235)
- [ordered write sequencer](https://github.com/hzeller/timg/blob/aa22227b5dd8e146c2af658460c09b5e516765f9/src/buffered-write-sequencer.h#L45-L56)
- [bounded animation IDs](https://github.com/hzeller/timg/blob/aa22227b5dd8e146c2af658460c09b5e516765f9/src/kitty-canvas.cc#L140-L168)

timg emitted the smallest protocol stream but had the highest client-side latency among mcat, Chafa, and timg. Minimum bytes and minimum latency are different objectives.

### viuer / viu

Viuer independently validates the local-versus-remote transport split:

- local rendering uses a temporary file;
- remote rendering sends direct base64 chunks.

Sources:

- [transport detection and choice](https://github.com/atanunq/viuer/blob/ed329e5c01d0aa0f65eae25fdb34e8cb87e5eac5/src/printer/kitty.rs#L23-L95)
- [local temporary-file path](https://github.com/atanunq/viuer/blob/ed329e5c01d0aa0f65eae25fdb34e8cb87e5eac5/src/printer/kitty.rs#L202-L303)
- [remote direct path](https://github.com/atanunq/viuer/blob/ed329e5c01d0aa0f65eae25fdb34e8cb87e5eac5/src/printer/kitty.rs#L306-L356)

`viu` was excluded from performance timing because its CLI cannot force Kitty output. Redirected output fell back to block rendering, while a synthetic TTY waited for a capability response. Comparing either behavior to forced Kitty output would have been invalid.

### Yazi

Yazi was examined but must not be treated as positive performance evidence. Its current Kitty path:

- decodes and downscales for each `image_show`;
- materializes RGB or RGBA bytes;
- allocates a complete base64 string;
- allocates another protocol output buffer;
- uses direct transmission.

Sources:

- [decode and downscale](https://github.com/sxyazi/yazi/blob/a40148448f2bb95c97cf8515bff4d857a8e481b6/yazi-adapter/src/image.rs#L43-L63)
- [full-buffer base64 and protocol output](https://github.com/sxyazi/yazi/blob/a40148448f2bb95c97cf8515bff4d857a8e481b6/yazi-adapter/src/drivers/kgp.rs#L351-L386)

Moving work into `spawn_blocking` protects the async executor but does not reduce total rendering latency. Yazi is useful as a straightforward implementation and as an example of allocation costs to avoid, not as a performance benchmark.

## Benchmark Method

### Environment

- Date: 2026-08-25.
- Linux 6.17.0-1020-gcp, x86_64.
- Intel Xeon 2.80 GHz.
- 4 logical CPUs.
- 31 GiB memory.
- Corpus: `/home/vikram_orbio_earth/Desktop/Screenshots`.

### Corpus

- 17 PNG files, all 8-bit RGBA.
- 9,603,069 bytes total.
- File sizes from 180,434 to 1,083,771 bytes.
- Dimensions from 2346x1482 to 3586x2226.
- Eleven images are 3294x1860.

This is representative of a large-source, small-terminal-preview workload.

### Compared Applications

- Chafa 1.18.2.
- mcat 0.6.4.
- timg 1.6.3_1.
- Kitty `icat` 0.48.2.

`viu` was excluded for the comparability reason above. Yazi was not benchmarked as a standalone renderer because its image path is embedded in the application.

### Geometry

The normal target was approximately 720 pixels wide:

- timg: 80x24 cells with its no-TTY 9x18 pixel-cell fallback, producing a representative 720x407 PNG after aspect fit;
- mcat: explicit 720x420 pixel bounds, producing a representative 720x407 PNG after aspect fit;
- Chafa: 72x24 cells with 10x20 fallback geometry, producing a 720x420 canvas after cell-boundary rounding.

Chafa processed about 3 percent more output pixels and was therefore slightly disadvantaged.

### Valid Commands

```sh
chafa --probe off --format kitty --size 72x24 --margin-bottom 0 --animate off FILE > /dev/null
timg -pk -g80x24 --frames=1 FILE > /dev/null
mcat -i --kitty --spx 720x420 --img-width 720px --img-height 420px --no-center --silent FILE > /dev/null
```

Kitty `icat` used an explicit window size, direct streaming, no passthrough, and no stdin detection:

```sh
kitten icat --stdin no --transfer-mode stream --passthrough none \
  --use-window-size 80,24,720,432 --place 80x24@0x0 \
  --no-trailing-newline FILE > /dev/null
```

### Invalid Run Excluded

An initial whole-corpus invocation passed all files to each program at once. mcat interpreted the multiple inputs through a different combined rendering path and emitted only 73,093 bytes. Those timings were discarded. The valid corpus comparison launched each application once per image.

## Benchmark Results

### Largest Image

Largest image: 3586x2226, 1,083,771 bytes. Confirmation run used 30 timed iterations after 5 warmups.

| Application | Mean | Standard deviation | Range | Output bytes |
|---|---:|---:|---:|---:|
| mcat | 112.8 ms | 10.0 ms | 100.6-148.2 ms | 176,186 |
| Chafa | 223.9 ms | 80.9 ms | 158.5-559.5 ms | 1,789,846 |
| timg | 282.2 ms | 30.7 ms | 246.1-367.8 ms | 110,815 |
| kitten icat, builtin | 3.037 s | 0.226 s | 2.439-3.402 s | 131,236 |
| kitten icat, ImageMagick | 3.396 s | 0.375 s | 2.590-4.393 s | 112,660 |

mcat was about 1.99 times faster than Chafa and 2.50 times faster than timg by mean. Kitty `icat` was far slower for this resize-heavy PNG workload.

### Smallest Image

Smallest file: 2726x1648, 180,434 bytes. Twenty timed iterations after three warmups.

| Application | Mean | Standard deviation | Range | Output bytes |
|---|---:|---:|---:|---:|
| Chafa | 104.5 ms | 11.6 ms | 92.5-136.2 ms | 1,712,029 |
| mcat | 110.0 ms | 29.7 ms | 65.9-185.8 ms | 44,636 |
| timg | 248.6 ms | 87.1 ms | 166.6-459.3 ms | 28,832 |

Chafa and mcat were effectively close for this low-complexity screenshot, while Chafa still emitted dramatically more protocol data.

### Median-Size Image

Median-size file: 3294x1860, 557,105 bytes. Twenty timed iterations after three warmups.

| Application | Mean | Standard deviation | Range | Output bytes |
|---|---:|---:|---:|---:|
| mcat | 104.7 ms | 20.6 ms | 84.8-164.9 ms | 91,273 |
| Chafa | 169.6 ms | 28.4 ms | 138.3-235.5 ms | 1,634,212 |
| timg | 245.2 ms | 36.1 ms | 205.6-322.3 ms | 59,443 |

### Full Corpus

Each renderer was launched separately for each of the 17 images. Seven timed runs after one warmup.

| Application | Mean total | Standard deviation | Range | Total output bytes |
|---|---:|---:|---:|---:|
| mcat | 1.678 s | 0.222 s | 1.479-2.099 s | 2,678,629 |
| Chafa | 2.558 s | 0.172 s | 2.320-2.861 s | 28,326,323 |
| timg | 3.869 s | 0.211 s | 3.727-4.300 s | 1,513,826 |

mcat was about 1.52 times faster than Chafa and 2.31 times faster than timg by mean.

### Output-Size Sensitivity

Largest source image:

| Approximate target | mcat | Chafa | timg |
|---|---:|---:|---:|
| 360x210 | 112.9 ms | 192.0 ms | 227.7 ms |
| 720x420 | 112.8 ms | 223.9 ms | 282.2 ms |
| 1440x840 | 159.3 ms | 224.1 ms | 386.7 ms |

At the large target, protocol sizes were:

- mcat: 528,564 bytes;
- Chafa: 7,003,551 bytes;
- timg: 355,835 bytes.

mcat remained fastest at every tested target. Timg minimized bytes but spent more CPU time. Chafa's client time scaled modestly, but its raw RGBA wire size grew substantially.

### Peak Memory

Single observation on the largest file:

- Chafa: 78,524 KiB peak RSS.
- mcat: 84,180 KiB peak RSS.
- timg: 99,788 KiB peak RSS.

This was not a repeated memory benchmark and should be treated as directional only.

## Benchmark Limitations

- Output was written to `/dev/null`.
- Results measure process startup, file reading, decode, resize, encode, base64/protocol serialization, and writes to the sink.
- Results do not measure terminal parsing, PNG decode in the terminal, GPU upload, compositing, or paint latency.
- File and shared-memory transports could not be measured correctly because no compatible graphical terminal consumed and acknowledged the transfer.
- A detached tmux pane would test tmux rather than Ghostty and was not used as a substitute.
- Chafa processed about 3 percent more output pixels at the normal target.
- Client latency and protocol byte count are separate metrics. Timg demonstrates that the smallest payload does not necessarily produce the lowest client latency.
- The corpus contains only large RGBA screenshots. Results should not be generalized to photographs, tiny icons, JPEGs, alpha-heavy artwork, or animations without additional measurements.

## Installation And Cleanup Record

The benchmark temporarily installed:

- timg;
- viu;
- hyperfine;
- Kitty/kitten;
- ImageMagick;
- dependencies introduced by timg.

All newly installed applications and the 30 dependencies introduced by timg were removed afterward. No Kitty shared-memory test objects remain.

Homebrew upgraded five formulae that were already installed: `x265`, `little-cms2`, `libdeflate`, `libheif`, and `libksba`. They were not removed or downgraded because they predated the benchmark.

The repository worktree was clean after benchmark cleanup.

## Recommended V1 Architecture

```text
local existing PNG + file transport supported
    |
send absolute path with f=100,t=f and target placement

otherwise
    |
read source metadata
    |
calculate target pixel dimensions
    |
decode still image
    |
resize directly to target
    |
encode speed-oriented PNG
    |
base64 Kitty chunks
    |
single buffered write
```

### Initial Data Path

1. Accept a single local PNG or JPEG path.
2. Accept explicit cell geometry or pixel geometry; do not require terminal probing for deterministic benchmarks.
3. For an existing local PNG when file transport is known to work, send its absolute path with `f=100,t=f` and let Ghostty decode and place it. Do not read, decode, resize, re-encode, or base64-encode it on the sender.
4. Otherwise determine target pixels using cell dimensions and measured cell pixel size when available.
5. Decode only the first still frame.
6. Resize once, preserving aspect ratio.
7. Encode the resized raster as PNG with a speed-oriented compression setting.
8. Base64-encode and emit a direct `a=T,f=100,t=d,q=2` Kitty transfer.
9. Buffer the complete bounded preview output and write it with one `Write` call or a minimal number of writes.

The normal preview size bounds output sufficiently that a single buffer is acceptable. Avoid whole-source-size intermediates where the chosen decoder permits target-aware decoding.

### Why PNG First

- mcat's resize-to-PNG path was the fastest complete pipeline tested.
- PNG reduced wire size by roughly an order of magnitude compared with Chafa's raw RGBA path on this corpus.
- Timg showed that pursuing the smallest possible PNG can cost excessive CPU, so compression should favor speed rather than minimum size.
- PNG is natively defined by the Kitty protocol and preserves alpha.
- Ghostty decodes PNG once into RGBA with Wuffs and caches the resulting GPU texture by image ID and generation.
- An existing local PNG can be handed to Ghostty with `t=f`, bypassing sender-side image processing and base64 entirely.

### Go Image Backend Decision

Do not assume Go's standard image stack meets the target. Kitty `icat` is a Go implementation and its observed resize-heavy PNG performance was poor in this environment.

Before implementing the CLI around a backend, create a focused benchmark comparing candidate Go-compatible decode/resize/PNG pipelines on the same corpus. Candidates may include pure-Go and cgo-backed approaches, but no backend should be selected solely from reputation.

Measure these stages independently:

- metadata read;
- decode;
- resize;
- PNG encode;
- base64 and Kitty framing;
- full pipeline.

Record allocation count, allocated bytes, peak RSS, output bytes, and wall time.

### Sender-Side SIMD Priorities

SIMD is potentially valuable in the Go sender, but only after avoiding unnecessary work and measuring each stage. Prioritize:

1. Base64 encoding for direct transfer.
2. Image resizing.
3. RGB/RGBA conversion and alpha compositing.
4. Zlib compression used by PNG or raw direct transfer.

Do not spend optimization effort on Kitty escape-sequence construction. Its byte count and CPU cost are tiny relative to image decode, resize, compression, and base64.

The first optimization question for every stage is whether the stage can be skipped:

- `t=f` for an existing local PNG skips sender read, decode, resize, PNG encode, zlib, base64, and image-byte PTY transfer;
- opaque images may skip alpha compositing and use RGB in a future raw path;
- unchanged repeated images may skip retransmission by reusing a Ghostty-cached image ID and placement;
- direct transfer should use fast base64 and resize only when local file transport is unavailable or inappropriate.

### Transport Boundary

Keep transport separate from image preparation so the PNG-producing path does not change when adding local file or shared-memory transport.

Implement direct transfer first as the deterministic protocol-test path and portable fallback. The user-facing V1 local path should also support `t=f` for an existing PNG, because Ghostty bypasses base64 and PTY image-byte transfer for that mode. Capability detection or an explicit transport option must guard this path.

Generated images and JPEG inputs still require an image-processing path. Shared memory may become the best transport for generated PNG or RGB/RGBA bytes, but Ghostty currently copies shared-memory data into owned storage, so it must be measured rather than assumed to be zero-copy.

After V1, compare in a real Ghostty session:

- direct PNG bytes;
- existing PNG file path;
- generated temporary-file PNG path;
- shared-memory PNG bytes, if Ghostty reports support.

Do not choose the default from Kitty's documented preference alone. Select the lowest measured end-to-end latency in Ghostty, including terminal consumption and cleanup.

### Concurrency

Keep the single-image V1 synchronous. The fastest tested still-image path did not require an asynchronous multi-stage pipeline, while timg's more elaborate worker and sequencer design did not win this workload.

Add bounded concurrency only when supporting:

- multiple independent images;
- animation frames;
- decode/encode overlap with terminal output.

Never parallelize protocol chunk writes; preserve command ordering.

### Image IDs

For a one-shot CLI, transmit and display one image without implementing a cache.

For a future long-running preview process, use a bounded image-ID strategy and explicitly replace or delete prior images. Ghostty caches decoded GPU textures by image ID plus generation, so repeated placement can avoid decode and upload while unchanged. Timg's comments document terminal pressure from unbounded IDs, and Yazi uses a stable process-derived ID for its single preview slot.

## Tidy, First

Apply Tidy, First by separating decisions that can be proven independently before building the command:

1. Establish a reproducible benchmark harness and corpus manifest before choosing an image backend.
2. Decide whether an existing PNG can use the local file fast path before allocating or decoding image data.
3. Define one small processed-raster result shape for fallback paths: dimensions plus encoded PNG bytes.
4. Define Kitty framing independently and test it with tiny known payloads and file paths.
5. Keep terminal geometry calculation independent from decode and encode.
6. Add the CLI only after the fast path, fallback backend, and protocol writer meet isolated tests and benchmarks.

This makes the intended change easy: image backend experiments can be swapped without disturbing protocol code, and transport experiments can be swapped without disturbing image processing. Avoid broader abstractions until a second implementation requires them.

## Implementation Plan

### Phase 1: Reproducible Benchmarks

- Add a benchmark corpus manifest that references configurable external paths rather than committing personal screenshots.
- Add a command or Go benchmark that runs one file and the complete corpus at fixed target sizes.
- Capture stage timings, allocations, output bytes, and environment metadata.
- Add target sizes matching the completed investigation: approximately 360x210, 720x420, and 1440x840.
- Establish mcat 0.6.4 as the external reference on the benchmark machine when available.
- Add separate benchmark cases for existing-PNG file transport and processed direct transport in a real Ghostty terminal.

Exit criteria:

- repeated results are machine-readable;
- invalid command modes fail loudly;
- each compared output is checked for the expected Kitty header and raster dimensions;
- one command cannot silently switch to block, Markdown, or another renderer.

### Phase 2: Backend Spike

- Benchmark candidate PNG metadata readers and decoders.
- Benchmark resize quality and speed separately.
- Benchmark PNG encoders at their speed-oriented settings.
- Benchmark available SIMD-capable base64 encoders against Go's standard encoder for direct output.
- Benchmark RGB/RGBA conversion, alpha compositing, and zlib independently before adding specialized SIMD code.
- Include opaque and alpha images.
- Include PNG and JPEG sources.
- Reject any pipeline that silently changes color channels, orientation, or alpha semantics.

Provisional normal-target performance goals on the benchmark host:

- largest screenshot warm mean no more than 150 ms;
- median screenshot warm mean no more than 125 ms;
- normal-target protocol payload no more than 350 KiB for the largest screenshot;
- peak RSS no more than 100 MiB.

These are based on measured mcat behavior with margin for a first Go implementation. Adjust only with documented benchmark evidence.

### Phase 3: Minimal Kitty Writer

- Implement transmit-and-display PNG framing.
- Implement direct base64 chunking according to the Kitty specification.
- Implement existing-file PNG framing with `f=100,t=f` and an absolute path payload.
- Suppress replies with `q=2` for normal output.
- Validate final `m=0` handling and exact chunk boundaries.
- Write protocol tests using tiny fixed PNG fixtures and golden byte sequences.
- Ensure filenames and image bytes never enter shell interpolation.

Exit criteria:

- protocol output decodes back to the original PNG payload;
- chunks satisfy protocol size and continuation rules;
- file transport emits only the encoded absolute path, not image bytes;
- output is deterministic except for an explicitly optional image ID;
- malformed input fails without partial protocol output where feasible.

### Phase 4: Minimal CLI

- Accept one image path.
- Accept explicit maximum cells and optional explicit pixel dimensions.
- Preserve source aspect ratio.
- Render one still frame.
- Use the existing-PNG file fast path when selected and supported.
- Fall back to resize-to-PNG direct transfer for unsupported local transport, remote operation, JPEG input, or required sender-side transformations.
- Write only protocol data to stdout and diagnostics to stderr.
- Return nonzero on decode, resize, encode, or write failure.
- Keep all work in one process and avoid subprocess image tools.

Exit criteria:

- PNG and JPEG inputs render in Ghostty;
- transparent PNG edges render correctly;
- output dimensions stay within requested bounds;
- the CLI meets provisional performance and memory targets.

### Phase 5: Real Ghostty Transport Benchmark

- Run in a directly attached Ghostty terminal, not through tmux.
- Query support once per process.
- Compare direct, existing-file, generated temporary-file, and shared-memory transport using identical PNG bytes.
- Include terminal acknowledgement or a reliable completion barrier so measurements include terminal consumption.
- Measure first render, repeated render, replacement, and cleanup.
- Measure placement of an unchanged image ID separately from retransmission to verify the value of Ghostty's texture cache.
- Verify no temporary files or shared-memory objects remain.

Exit criteria:

- select a default local transport from measured end-to-end latency;
- retain direct transfer as the fallback;
- document behavior over SSH and through tmux separately.

### Phase 6: Optional Fast Paths

Add only when measurements justify them:

- RGB output for opaque generated rasters if raw transport becomes useful;
- decoder-assisted downscaling;
- persistent process and bounded image-ID reuse;
- shared-memory transport for generated data;
- SIMD base64, resize, color conversion, alpha compositing, or zlib where profiles show a material bottleneck;
- parallel processing of multiple images.

## Verification Matrix

### Functional

- Small opaque PNG.
- Large RGBA screenshot.
- JPEG photograph.
- Portrait and landscape aspect ratios.
- Image smaller than target with upscaling disabled.
- Corrupt and unsupported input.
- Output write failure.

### Protocol

- Single-chunk PNG.
- Multi-chunk PNG.
- Exact chunk-boundary payload.
- Existing-file PNG path with `t=f`.
- File paths containing spaces and non-ASCII bytes where supported by the platform.
- Quiet mode.
- Correct terminal string terminators.
- No raw binary outside the encoded payload.

### Performance

- Cold first invocation.
- Warm repeated invocation.
- Small, normal, and large output dimensions.
- Full screenshot corpus.
- Stage-level CPU and allocation profiles.
- Standard versus SIMD-capable base64 encoding for direct transfer.
- Resize, RGB/RGBA conversion, alpha compositing, and zlib profiles before any SIMD specialization.
- Direct versus existing-file, temporary-file, and shared-memory end-to-end Ghostty results.
- Retransmission versus placement-only rendering of a Ghostty-cached image ID.

### Cleanup

- No leaked temporary files.
- No leaked POSIX shared-memory objects.
- No retained image IDs in a future persistent mode after explicit clear.
- Benchmark-only Homebrew installations removed after use unless separately approved.

## Risks

- Pure-Go decode or resize performance may miss the target.
- PNG encoding can dominate at larger target dimensions.
- Direct base64 adds about 33 percent transport expansion.
- SIMD integration can add architecture-specific code and maintenance without improving end-to-end latency if decode or PNG encode dominates.
- Existing-file transport avoids sender work but asks Ghostty to read, copy, decode, and potentially scale the full source image; it must win an end-to-end benchmark before becoming the automatic default.
- Ghostty's current file and shared-memory paths still copy data into owned storage and are not zero-copy.
- File and shared-memory support varies across terminals and local/remote boundaries.
- Terminal render latency may reverse client-only rankings.
- RGBA screenshots are not representative of all image types.
- A large dependency added only for decode speed may violate the minimum-product goal.
- Copying implementation code from GPL or LGPL projects can introduce licensing obligations. Use the protocol specification and independently implemented algorithms; do not copy source or static data tables.

## Decision Summary

- **Why `icat` in Go was slow**: Profiling confirmed it was bottlenecked by full-resolution ICC color conversion (~81% CPU, ~1.6s).
- **Core Strategy**:
  - Prefer `t=f` for existing local PNGs (~0.7 ms sender time).
  - If processing is necessary, resize *first*, then apply color transformations on the bounded target thumbnail size (~337 ms vs ~1,800 ms).
  - Do not waste effort optimizing escape framing (takes <0.35 ms).
- Use mcat as the measured performance baseline.
- Implement direct resize-to-PNG transfer first for deterministic protocol validation and as the portable fallback.
- Include `t=f` for an existing local PNG in V1 and treat it as the leading local fast-path candidate.
- Do not copy Chafa's raw RGBA transport as the V1 default.
- Do not use Yazi as performance evidence.
- Do not assume Kitty `icat` proves a fast Go image pipeline.
- Skip sender work before optimizing it: prefer existing-PNG file transport when supported and proven faster end-to-end.
- For direct transfer, profile base64 and resize first; then RGB/RGBA conversion, alpha compositing, and zlib. Do not optimize escape framing.
- Rely on Ghostty's existing SIMD base64 decode, Wuffs PNG decode, and image-ID/generation GPU texture cache rather than duplicating receiver responsibilities.
- Keep the first still-image implementation synchronous and small.
- Decide file versus shared-memory transport only after a real Ghostty end-to-end benchmark.
