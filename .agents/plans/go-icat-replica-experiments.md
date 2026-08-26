# Go `icat` Replica And Terminal Graphics Experiments

## Status

Proposed. This plan covers benchmark-only Go code and controlled experiments. It does not replace the broader renderer plan in `.agents/plans/go-terminal-image-renderer.md`.

## Objective

Create a small Go program that reproduces the relevant still-image path from Kitty `icat` at commit `54416498c89e1d07e5079c49d15470dd0d947ce7`, establish behavioral and performance parity, and then compare alternative image-processing and Kitty-transport approaches by changing one decision at a time.

The purpose is not to spend more time diagnosing Kitty's application. The replica gives us code we control, stage-level measurements, and an attributable experiment matrix from which to select the product design.

## Core Rule

No alternative may be called faster or better until:

1. the baseline replica passes parity checks against `kitten icat`;
2. the compared outputs have equivalent target dimensions and image semantics;
3. the experiment command and environment are recorded;
4. invalid and failed runs are retained in the experiment log rather than silently discarded;
5. temporary installations and artifacts are cleaned up and recorded.

## Experiment Log

Maintain an append-only experiment log throughout execution.

Proposed path:

```text
.agents/data/go-kitty-renderer-experiments.md
```

Each experiment entry must include:

- timestamp;
- experiment ID;
- question or hypothesis;
- source commit and dependency versions;
- host CPU, operating system, Go version, and relevant environment variables;
- corpus and selected files;
- exact command lines;
- target cells and target pixels;
- transport and image format;
- warmup and timed run counts;
- stage timings;
- wall time and CPU time;
- allocations and allocated bytes;
- peak RSS when measured;
- source and destination dimensions;
- encoded payload size and complete protocol-output size;
- payload or pixel hash used for equivalence;
- result and interpretation;
- validity status;
- unexpected behavior;
- generated artifact paths;
- packages installed for the experiment;
- cleanup performed.

Never overwrite an earlier result. If a method is found invalid, append a correction that identifies the invalid experiment IDs and explains why.

## Scope

### Included

- One still PNG or JPEG input.
- Fixed target geometry.
- Kitty direct, existing-file, temporary-file, and shared-memory transports.
- PNG and raw RGB/RGBA payloads.
- Zlib and base64 costs.
- Decode, resize, color conversion, alpha compositing, compression, and framing.
- Sender-only benchmarks.
- End-to-end Ghostty benchmarks.
- Stable image-ID placement experiments.

### Excluded

- FZF integration.
- Character-art rendering.
- Animation and video.
- Sixel and iTerm2.
- Tmux passthrough.
- Production CLI design beyond what is necessary to run experiments.
- Broad terminal detection databases.

## Reference Behavior

The baseline follows Kitty's current Go `icat` implementation:

- determine available pixel dimensions;
- decode through Kitty's imaging backend;
- use the resize callback to fit the source to the requested target;
- preserve an unchanged single-frame PNG when no transformation is needed;
- otherwise select RGB for opaque images and RGBA for images with alpha;
- conditionally zlib-compress non-PNG direct payloads larger than 2 KiB when compression reduces size;
- base64-encode and chunk Kitty graphics commands;
- transmit and display the image.

Pinned sources:

- [input and resize orchestration](https://github.com/kovidgoyal/kitty/blob/54416498c89e1d07e5079c49d15470dd0d947ce7/kittens/icat/process_images.go#L130-L330)
- [transport orchestration](https://github.com/kovidgoyal/kitty/blob/54416498c89e1d07e5079c49d15470dd0d947ce7/kittens/icat/transmit.go#L85-L165)
- [transport selection](https://github.com/kovidgoyal/kitty/blob/54416498c89e1d07e5079c49d15470dd0d947ce7/kittens/icat/transmit.go#L254-L277)
- [compression and direct output](https://github.com/kovidgoyal/kitty/blob/54416498c89e1d07e5079c49d15470dd0d947ce7/tools/tui/graphics/command.go#L255-L310)

## Experiment Code

Create isolated benchmark code rather than modifying Kitty or production dotfiles code.

Proposed location:

```text
.agents/experiments/go-icat-replica/
```

Keep the first implementation structurally small:

```text
main and experiment selection
baseline image pipeline
Kitty command writer
stage recorder
equivalence checks
benchmarks
```

Do not design a reusable terminal graphics framework during this phase. Introduce a boundary only where the matrix needs substitution:

- image preparation;
- payload encoding;
- transport.

## Licensing Boundary

The baseline may use Kitty's public Go packages at the pinned revision where practical. If exact behavior requires adapting Kitty code, keep that work benchmark-only, retain source attribution, and treat it as GPLv3-derived experimental code.

Do not copy GPL-derived code into the eventual product implementation. Reimplement the selected behavior independently from the Kitty protocol specification and measured requirements.

## Phase 1: Build The Exact Baseline

Implement the resize-required still-image path:

```text
read source
-> decode using the same Kitty imaging backend
-> calculate the same destination dimensions
-> perform the same resize
-> run the same opacity decision
-> materialize RGB or RGBA
-> make the same conditional zlib decision
-> base64 and frame using the same Kitty command behavior
-> write to a selectable sink
```

Also implement Kitty's unchanged single-frame PNG path so that no-transform behavior can be compared separately.

Instrument every stage from the first version. Instrumentation must be switchable so its overhead can be measured.

## Phase 2: Establish Parity

Run the replica and pinned `kitten icat` with identical:

- input file;
- engine;
- target cell dimensions;
- target pixel dimensions;
- fit and scale-up settings;
- alpha/background behavior;
- direct transport;
- passthrough setting;
- quiet mode.

Verify:

- exit status;
- source dimensions;
- destination dimensions;
- RGB versus RGBA selection;
- uncompressed pixel hash;
- compression enabled or disabled;
- decompressed transport payload hash;
- Kitty control keys;
- complete output byte count;
- image appearance in Ghostty;
- execution time within an explained range.

Parity failures block variant comparisons. Record each failure and correction in the experiment log.

## Phase 3: Stage-Level Baseline

Record separate timings for:

1. process startup and argument parsing;
2. file open and read;
3. metadata parsing;
4. PNG or JPEG decode;
5. target calculation;
6. resize;
7. opacity detection;
8. RGB/RGBA materialization;
9. zlib compression;
10. base64 encoding;
11. Kitty command construction;
12. output write;
13. complete pipeline.

Collect:

- Go CPU profile;
- allocation profile;
- heap profile;
- optional Linux `perf` profile;
- goroutine count;
- garbage-collection time;
- bytes processed per stage.

Use scaling behavior as supporting evidence:

- source-pixel scaling suggests decode cost;
- destination-pixel scaling suggests resize, conversion, or encode cost;
- payload-byte scaling suggests zlib, base64, or write cost;
- allocation growth identifies avoidable image-sized copies.

## Phase 4: Controlled Variant Matrix

Every variant starts from the parity-verified baseline and changes only the stated decision.

| ID | Variant | Sender Pipeline |
|---|---|---|
| A | `icat` baseline | Decode, resize, RGB/RGBA, conditional zlib, base64, direct |
| B | Existing-file PNG | Absolute PNG path with `f=100,t=f`; no sender image processing |
| C | Direct original PNG | Original PNG bytes, base64, direct; terminal performs placement scaling |
| D | mcat-style | Decode, resize, speed-oriented PNG encode, base64, direct |
| E | Chafa-style | Decode, resize, raw RGBA, base64, direct without zlib |
| F | Raw compressed | Decode, resize, RGB/RGBA, selected fast zlib, base64, direct |
| G | Shared memory | Prepared PNG or RGB/RGBA through `t=s` |
| H | Temporary PNG | Decode, resize, PNG encode, then `t=t` |
| I | Cached placement | Transmit once with stable image ID; repeat placement without retransmission |

For each variant, compare:

- sender latency;
- end-to-end Ghostty latency;
- sender CPU;
- terminal CPU where measurable;
- sender allocations;
- protocol bytes;
- local file or shared-memory bytes;
- first display latency;
- repeated display latency;
- visual equivalence;
- cleanup behavior.

## Phase 5: Component Substitutions

After the architectural matrix identifies competitive pipelines, substitute one component at a time.

### Base64

- Go standard library baseline.
- SIMD-capable implementation candidates.
- Whole-buffer versus streaming output.
- Allocation-free or reusable-buffer variants.

### Resize

- Kitty's current backend.
- Candidate pure-Go resizers.
- Candidate cgo-backed resizers.
- Box, bilinear, and higher-quality filters at equivalent visual quality.
- Direct resize into final RGB/RGBA storage.

### Color And Alpha

- RGB fast path for opaque images.
- RGBA preservation.
- Alpha compositing only when required.
- SIMD-capable conversion and compositing candidates.

### Compression

- Kitty's current zlib behavior.
- Faster zlib implementations.
- Compression levels optimized for latency.
- Compress-only-if-smaller threshold.
- PNG versus compressed raw pixels.

Do not optimize Kitty escape framing; measure it to demonstrate that it is immaterial, then leave it simple.

## Phase 6: Ghostty End-To-End Experiments

Run in a directly attached Ghostty session, not through tmux.

Ghostty receiver facts relevant to the matrix:

- direct base64 is decoded in place using SIMD when available;
- file and shared-memory transports bypass base64 and PTY image-byte transfer but currently copy data into owned storage;
- PNG is decoded once into RGBA with Wuffs;
- decoded images are retained as GPU textures keyed by image ID and generation.

Sources:

- [in-place base64 decode](https://github.com/ghostty-org/ghostty/blob/9c3ec931d64561a8407dde7ac984ce156ae91539/src/terminal/kitty/graphics_command.zig#L262-L289)
- [SIMD base64](https://github.com/ghostty-org/ghostty/blob/9c3ec931d64561a8407dde7ac984ce156ae91539/src/simd/base64.zig#L9-L37)
- [file and shared-memory loading](https://github.com/ghostty-org/ghostty/blob/9c3ec931d64561a8407dde7ac984ce156ae91539/src/terminal/kitty/graphics_image.zig#L147-L189)
- [Wuffs PNG decode](https://github.com/ghostty-org/ghostty/blob/9c3ec931d64561a8407dde7ac984ce156ae91539/src/terminal/sys.zig#L15-L53)
- [texture cache](https://github.com/ghostty-org/ghostty/blob/9c3ec931d64561a8407dde7ac984ce156ae91539/src/renderer/image.zig#L853-L877)

Measure:

- first display;
- acknowledgement or another reliable completion barrier;
- repeated placement of an unchanged image;
- replacement under the same image ID with a new generation;
- explicit deletion;
- terminal memory before and after cleanup;
- temporary-file and shared-memory cleanup.

## Tidy, First

Make the comparisons easy before making implementation choices:

1. Create one parity-verified baseline.
2. Add stage recording before adding alternatives.
3. Separate image preparation, payload encoding, and transport only where substitution requires it.
4. Add one variant at a time.
5. Preserve identical geometry and semantic checks across variants.
6. Extract product code only after a winning path is demonstrated.

This prevents premature framework design and ensures each optimization has a measurable cause and effect.

## Benchmark Corpus

Start with the existing screenshot corpus:

```text
/home/vikram_orbio_earth/Desktop/Screenshots
```

Record a manifest containing file name, byte size, dimensions, format, alpha presence, and content hash. Do not commit personal screenshots.

Add generated fixtures for:

- small opaque PNG;
- alpha-heavy PNG;
- noisy photograph-like PNG;
- JPEG photograph;
- portrait image;
- already-target-sized PNG;
- corrupt input.

Run at approximately:

- 360x210;
- 720x420;
- 1440x840.

## Acceptance Criteria

The experiment phase is complete when:

- the Go baseline has behavioral parity with pinned `kitten icat`;
- the cause of the baseline's dominant cost is demonstrated by stage timings and profiles;
- every architectural variant has valid sender-only results;
- local transports and cached placement have valid end-to-end Ghostty results;
- output dimensions and image semantics are equivalent;
- SIMD recommendations are backed by component benchmarks;
- a winning local path and portable fallback are identified;
- all conclusions reference experiment-log entries;
- all temporary packages and artifacts are cleaned up.

## Decision Rule

Select the product path using measured total latency, not one isolated metric.

Expected decision structure:

```text
existing local PNG and file transport supported?
    yes -> use t=f if Ghostty end-to-end results win
    no  -> run the selected processing pipeline

processing required?
    choose the fastest equivalent decode + resize + encode combination

direct transport required?
    choose PNG or compressed RGB/RGBA by total measured latency
    use SIMD only for demonstrated hotspots

same image shown again?
    reuse image ID and placement if Ghostty cache measurements win
```

The final production implementation should be independently written from the selected measured behavior, remain smaller than the experiment harness, and exclude variants that did not win or serve as necessary fallbacks.
