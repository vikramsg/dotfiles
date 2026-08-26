# Experiment & Performance Benchmark Log: Gocat

## 1. Executive Summary & Objective

**Gocat** is a minimal, performance-first terminal image renderer written in Go targeting terminals that support the **Kitty Graphics Protocol** (with a primary focus on Ghostty).

This experiment log documents the architectural validation, micro-benchmarks, end-to-end process timings, and comparison against **MCAT (Rust + SIMD)** across a representative corpus of high-resolution retina screenshots.

---

## 2. Architecture & Pipeline Design

### Control Flow
```text
                     +---------------------------+
                     |        Input File         |
                     +---------------------------+
                                   |
                         Is local PNG file?
                               /       \
                        [YES] /         \ [NO / Stdin / Explicit Resize]
                             /           \
               +-------------------+    +------------------------------------+
               | Fast Path (t=f)   |    | Fallback Pipeline (t=d)            |
               | Canonical Path    |    | 1. Decode (PNG, JPEG, GIF, WebP)   |
               | Emit Kitty t=f    |    | 2. Downscale (draw.BiLinear)       |
               | Latency: ~0.03 ms |    | 3. Encode (png.BestSpeed)          |
               | Payload: 140 bytes|    | 4. Base64 Chunk (4096 B chunks)   |
               +-------------------+    +------------------------------------+
                             \           /
                              \         /
                     +---------------------------+
                     | Standard Output (Ghostty) |
                     +---------------------------+
```

### Key Engineering Decisions (Tidy, First)
1. **Zero-Work Fast Path (`t=f`)**:
   - For existing local PNG files, Ghostty can directly read, decode with its internal SIMD/Wuffs engine, and cache the image as a GPU texture.
   - Gocat resolves the canonical absolute path and transmits `\x1b_Ga=T,f=100,t=f,q=2;<b64_path>\x1b\`.
   - Payload size is fixed to **~140 bytes**, eliminating all sender-side decompression, downsampling, PNG re-compression, and PTY base64 ballooning.
2. **Deterministic Scalar Fallback (`t=d`)**:
   - For WebP, JPEG, GIF, stdin streams, or non-PNG inputs: decode, downscale preserving aspect ratio to bounding box (`draw.BiLinear`), encode with `png.BestSpeed`, and transmit chunked Base64 stream (`m=1`/`m=0`).
   - The current scaling operation is exactly:

     ```go
     draw.BiLinear.Scale(dst, dst.Bounds(), srcImg, bounds, draw.Over, nil)
     ```

   - `golang.org/x/image/draw` executes scalar Go loops for this path. WebP decoding supplies a YCbCr 4:2:0 source image, so this operation performs horizontal scaling and YCbCr-to-RGBA color conversion without AVX2 acceleration.
3. **Chunk Framing**:
   - Standard 4096-byte chunking matching Kitty protocol specification with standard string terminators (`\x1b\`).

---

## 3. Benchmarks & Performance Results

### Environment
- **Platform**: Linux x86-64 (Intel Xeon 2.80GHz, 4 vCPUs)
- **Go Version**: `go1.27.0 linux/amd64`
- **Reference Baseline**: `mcat 0.6.4` (Rust + SIMD `fast_image_resize`)
- **Corpus**: 18 high-resolution RGBA screenshots (up to 2.8MB / 3586x2226 pixels)

### Test Case 1: Single Large Retina Screenshot (2.8MB, 1600x1592)
Averaged across 10 warm process executions:

| Implementation | Mode | Average Wall Time | Data Emitted | Speedup vs MCAT |
|---|---|---:|---:|---:|
| **Gocat** | **Fast Path (`t=f`)** | **17.77 ms** | **140 bytes** | **~5.1x faster** |
| **MCAT** | Rust + SIMD Resize | 89.85 ms | 297 KB | Baseline (1.0x) |
| **Gocat** | Scalar Go (Decode + Resize) | 213.59 ms | 297 KB | 0.42x |

### Test Case 2: Internal Go Engine Throughput (Go Benchmark `b.N`)
Measuring pure in-process execution overhead:

| Benchmark Target | Latency / op | Memory Allocated / op | Allocations / op |
|---|---:|---:|---:|
| **Go Fast Path (`t=f`)** | **37.3 µs (0.037 ms)** | 67.9 KB | 42 |
| **MCAT Process Spawn** | 68,400 µs (68.4 ms) | - | - |
| **Go Scalar Decode + Resize** | 224,863 µs (224.8 ms) | 36.2 MB | 2,937 |

### Test Case 3: Entire Screenshot Corpus (18 Images Combined)

| Operation | Total In-Process Time | Average Time Per Image |
|---|---:|---:|
| **Fast Path (`t=f`) Batch** | **0.67 ms (676 µs)** | **~37.5 µs** |
| **MCAT Batch** | 1,481.69 ms | ~82.3 ms |
| **Go Scalar Fallback Batch** | 4,575.92 ms | ~254.2 ms |

---

## 4. Observations & Conclusions

1. **Passthrough is King**: Avoiding sender-side raster operations yields a **>1,000x speedup in computation** and reduces wire bytes from **~300 KB to ~140 bytes**.
2. **SIMD Opportunity Boundary**: SIMD is valuable when pixels *must* be crunched (resizing JPEGs or in-memory generated bitmaps), but avoiding decoding entirely for local PNGs dominates any SIMD optimization.
3. **Memory Footprint**: Fast-path allocations in Go are bounded to filepath strings (~67 KB), with zero large raster heap buffers.

---

## 5. Native WebP Benchmark

### Corpus

- **Source**: `public.asset_plume_silver.qa_rgb_image_location` in the Data Product worktree database.
- **Files**: 10 unchanged GCS WebP objects.
- **Dimensions**: 8000x2000 pixels each.
- **Compressed size**: 2,130,306 bytes total (131-243 KB per image).
- **Target**: 720x420 pixels, preserving aspect ratio.
- **Local corpus**: `/tmp/opencode/gocat-webp-corpus`.
- **Checksum manifest SHA-256**: `9d8ccb3808dc8962e768cec6ec099e55ff68b0cc7b318d606fd117043c7f4d96`.

The source files remained WebP. No external conversion or generated PNG corpus was used. GoCAT decodes WebP directly and emits the protocol-supported PNG stream in memory.

### Process Wall Time

Averaged over 10 warm process executions of the largest compressed file (`885_910625664_visualization.webp`, 247,876 bytes):

| Implementation | Average Wall Time | Data Emitted |
|---|---:|---:|
| **Gocat automatic WebP fallback** | **837.05 ms** | 59,273 bytes |
| **MCAT WebP resize** | **526.04 ms** | 71,317 bytes |
| **Gocat forced WebP fallback** | **840.56 ms** | 59,273 bytes |

### Go Benchmark Results

Five benchmark samples were collected. Corpus values are for all 10 images per operation.

| Benchmark | Median Time | Observed Range | Allocations |
|---|---:|---:|---:|
| **Gocat automatic, full corpus** | 7.80 s | 6.34-8.30 s | ~726 MB/op |
| **Gocat forced fallback, full corpus** | 6.37 s | 6.28-6.64 s | ~726 MB/op |
| **MCAT, full corpus** | 4.00 s | 3.78-4.41 s | process allocations not measured |
| **Gocat automatic, largest image** | 596.41 ms | 579.21-648.79 ms | ~72.7 MB/op |
| **Gocat forced fallback, largest image** | 592.30 ms | 585.92-611.96 ms | ~72.7 MB/op |
| **MCAT, largest image** | 390.51 ms | 380.95-408.63 ms | process allocations not measured |

MCAT is approximately 1.5-1.6x faster on this native WebP workload. GoCAT's automatic and forced fallback paths perform the same work; the small corpus-level difference is benchmark variance.

### Reproduction

```bash
cd bin/gocat
GOCAT_BENCH_CORPUS=/tmp/opencode/gocat-webp-corpus go test -v -run '^TestProcessWallTimeComparison$' .
GOCAT_BENCH_CORPUS=/tmp/opencode/gocat-webp-corpus go test -run '^$' -bench 'Benchmark(Corpus|SingleLargeImage)$' -benchmem -count=5 .
```
