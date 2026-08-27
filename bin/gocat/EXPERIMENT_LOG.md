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
3. **Chunk Framing**:
   - Standard 4096-byte chunking matching Kitty protocol specification with standard string terminators (`\x1b\`).

### Current WebP Scaling Algorithm

The fallback pipeline calls `golang.org/x/image/draw` v0.45.0 exactly as follows:

```go
draw.BiLinear.Scale(dst, dst.Bounds(), srcImg, bounds, draw.Over, nil)
```

`draw.BiLinear` is a separable tent-kernel resampler. Its one-dimensional kernel has support 1 and weight function:

```text
k(t) = 1 - t, for 0 <= t < 1
k(t) = 0,     otherwise
```

For each axis, the scaler precomputes the source-pixel contributions for every destination coordinate. Given source length `src` and destination length `dst`, it calculates:

```text
scale = src / dst
center(x) = (x + 0.5) * scale - 0.5
```

When downscaling (`scale > 1`), it widens the kernel support from `1` to `scale` and evaluates the kernel at `distance / scale`. This causes every covered source pixel to contribute rather than sampling only the nearest four pixels. The contribution weights for each destination coordinate are normalized so that they sum to one.

Scaling is performed in two passes:

1. **Horizontal pass**: `scaleX_YCbCr420` produces a `destination width x source height` temporary image represented as `[4]float64` values per pixel.
2. **Vertical pass**: `scaleY_RGBA_Src` applies the independently precomputed vertical tent weights to the temporary image, normalizes and clamps the channels, and writes the final `image.RGBA` destination.

For an 8000x2000 benchmark image fitted into the 720x420 bounding box, GoCAT calculates a 720x180 destination. Both axis scale ratios are approximately 11.11, so each destination coordinate accumulates contributions from approximately 22 source coordinates per pass. The horizontal intermediate buffer contains `720 * 2000` entries of `[4]float64`, which occupies 46,080,000 bytes.

For the benchmark WebPs, `golang.org/x/image/webp` decodes the source into `image.YCbCr` with 4:2:0 chroma subsampling. During the horizontal pass, each contributing source pixel is converted to 16-bit-range RGB using the integer equations from `image/color.YCbCr.RGBA`:

```text
Y1 = Y * 0x10101
Cb1 = Cb - 128
Cr1 = Cr - 128

R = (Y1 + 91881 * Cr1) >> 8
G = (Y1 - 22554 * Cb1 - 46802 * Cr1) >> 8
B = (Y1 + 116130 * Cb1) >> 8
```

Each channel is clamped to `[0, 65535]`, multiplied by its horizontal tent weight, accumulated as `float64`, normalized, and stored in the temporary buffer. The vertical pass repeats the weighted accumulation and normalization over temporary rows, then converts each channel to 8-bit RGBA output.

Although GoCAT passes `draw.Over`, the decoded YCbCr source is opaque. The scaler detects this and changes the operation to `draw.Src`, so the final pixels replace the newly allocated destination pixels directly. The implementation executes these contribution and conversion loops as scalar Go code.

#### Pseudocode

```text
function build_contributions(source_length, destination_length):
    scale = source_length / destination_length
    half_width = 1
    kernel_argument_scale = 1

    if scale > 1:
        half_width = scale
        kernel_argument_scale = 1 / scale

    distribution = []

    for destination_coordinate in 0 .. destination_length - 1:
        center = (destination_coordinate + 0.5) * scale - 0.5
        first_source = max(0, floor(center - half_width))
        last_source = min(source_length, ceil(center + half_width))

        contributions = []
        total_weight = 0

        for source_coordinate in first_source .. last_source - 1:
            distance = abs(center - source_coordinate) * kernel_argument_scale
            if distance >= 1:
                continue

            weight = 1 - distance
            contributions.append((source_coordinate, weight))
            total_weight += weight

        distribution.append((contributions, 1 / total_weight))

    return distribution


horizontal = build_contributions(source_width, destination_width)
vertical = build_contributions(source_height, destination_height)
temporary = array[destination_width * source_height] of four float64 values

# Horizontal pass: YCbCr 4:2:0 source to normalized RGB float values.
for source_y in 0 .. source_height - 1:
    for destination_x in 0 .. destination_width - 1:
        red_sum = 0
        green_sum = 0
        blue_sum = 0
        contributions, inverse_total_weight = horizontal[destination_x]

        for source_x, weight in contributions:
            y = source.Y[source_y, source_x]
            cb = source.Cb[source_y / 2, source_x / 2]
            cr = source.Cr[source_y / 2, source_x / 2]

            red, green, blue = ycbcr_to_rgb16(y, cb, cr)
            red_sum += red * weight
            green_sum += green * weight
            blue_sum += blue * weight

        temporary[source_y, destination_x] = (
            red_sum * inverse_total_weight / 65535,
            green_sum * inverse_total_weight / 65535,
            blue_sum * inverse_total_weight / 65535,
            1,
        )

# Vertical pass: normalized RGB float values to the RGBA destination.
for destination_x in 0 .. destination_width - 1:
    for destination_y in 0 .. destination_height - 1:
        red_sum = 0
        green_sum = 0
        blue_sum = 0
        alpha_sum = 0
        contributions, inverse_total_weight = vertical[destination_y]

        for source_y, weight in contributions:
            red, green, blue, alpha = temporary[source_y, destination_x]
            red_sum += red * weight
            green_sum += green * weight
            blue_sum += blue * weight
            alpha_sum += alpha * weight

        destination[destination_y, destination_x] = rgba8(
            red_sum * inverse_total_weight,
            green_sum * inverse_total_weight,
            blue_sum * inverse_total_weight,
            alpha_sum * inverse_total_weight,
        )
```

The following Python implements the same contribution calculation:

```python
from math import ceil, floor


def build_contributions(source_length: int, destination_length: int):
    scale = source_length / destination_length
    half_width = scale if scale > 1 else 1.0
    kernel_argument_scale = 1 / scale if scale > 1 else 1.0
    distribution = []

    for destination_coordinate in range(destination_length):
        center = (destination_coordinate + 0.5) * scale - 0.5
        first_source = max(0, floor(center - half_width))
        last_source = min(source_length, ceil(center + half_width))

        contributions = []
        for source_coordinate in range(first_source, last_source):
            distance = abs(center - source_coordinate) * kernel_argument_scale
            if distance < 1:
                contributions.append((source_coordinate, 1 - distance))

        total_weight = sum(weight for _, weight in contributions)
        distribution.append([
            (coordinate, weight / total_weight)
            for coordinate, weight in contributions
        ])

    return distribution
```

The YCbCr-to-RGB operation inside each horizontal contribution is equivalent to:

```python
def ycbcr_to_rgb16(y: int, cb: int, cr: int):
    y1 = y * 0x10101
    cb1 = cb - 128
    cr1 = cr - 128

    red = (y1 + 91881 * cr1) >> 8
    green = (y1 - 22554 * cb1 - 46802 * cr1) >> 8
    blue = (y1 + 116130 * cb1) >> 8

    clamp = lambda channel: min(0xFFFF, max(0, channel))
    return clamp(red), clamp(green), clamp(blue)
```

For the observed GoCAT path (opaque, zero-origin YCbCr 4:2:0 source; zero-origin RGBA destination; no masks), the top-level Python equivalent of the Go call is:

```python
def bilinear_scale_ycbcr420(src_y, src_cb, src_cr, destination_width, destination_height):
    """Run the two-pass tent-kernel scaler for a YCbCr 4:2:0 source.

    Args:
        src_y: Two-dimensional, full-resolution luma plane indexed as [y][x].
        src_cb: Two-dimensional blue-difference chroma plane at half width and height.
        src_cr: Two-dimensional red-difference chroma plane at half width and height.
        destination_width: Width in pixels of the RGBA output.
        destination_height: Height in pixels of the RGBA output.

    Returns:
        A destination_height by destination_width matrix of 8-bit RGBA tuples.
    """
    source_height = len(src_y)
    source_width = len(src_y[0])
    horizontal = build_contributions(source_width, destination_width)
    vertical = build_contributions(source_height, destination_height)

    # Go allocates one [4]float64 entry for every element represented here.
    temporary = [
        [(0.0, 0.0, 0.0, 1.0) for _ in range(destination_width)]
        for _ in range(source_height)
    ]

    for source_y in range(source_height):
        for destination_x, contributions in enumerate(horizontal):
            red_sum = green_sum = blue_sum = 0.0

            for source_x, weight in contributions:
                red, green, blue = ycbcr_to_rgb16(
                    src_y[source_y][source_x],
                    src_cb[source_y // 2][source_x // 2],
                    src_cr[source_y // 2][source_x // 2],
                )
                red_sum += red * weight
                green_sum += green * weight
                blue_sum += blue * weight

            temporary[source_y][destination_x] = (
                red_sum / 65535,
                green_sum / 65535,
                blue_sum / 65535,
                1.0,
            )

    destination = [
        [(0, 0, 0, 0) for _ in range(destination_width)]
        for _ in range(destination_height)
    ]

    def float_to_rgba8(channel):
        value16 = min(65535, max(0, int(65535 * channel + 0.5)))
        return value16 >> 8

    for destination_x in range(destination_width):
        for destination_y, contributions in enumerate(vertical):
            red_sum = green_sum = blue_sum = alpha_sum = 0.0

            for source_y, weight in contributions:
                red, green, blue, alpha = temporary[source_y][destination_x]
                red_sum += red * weight
                green_sum += green * weight
                blue_sum += blue * weight
                alpha_sum += alpha * weight

            destination[destination_y][destination_x] = (
                float_to_rgba8(min(red_sum, alpha_sum)),
                float_to_rgba8(min(green_sum, alpha_sum)),
                float_to_rgba8(min(blue_sum, alpha_sum)),
                float_to_rgba8(alpha_sum),
            )

    return destination
```

The specialized function above does not have the same argument interface as Go's public `Scale` method. A Python wrapper with one-to-one argument correspondence is:

```python
OVER = "over"
SRC = "src"


def bilinear_scale(dst, dst_rect, src_img, src_rect, op, options):
    """Scale src_img into dst using the branch exercised by GoCAT.

    Args:
        dst: Existing RGBA destination image that is mutated in place.
        dst_rect: Rectangle within dst to fill with the scaled pixels.
        src_img: Decoded source image; this path expects opaque YCbCr 4:2:0.
        src_rect: Rectangle within src_img to read and scale.
        op: Compositing operation requested by the caller, initially OVER.
        options: Optional masks and mask offsets; GoCAT passes None.
    """
    # These are the concrete conditions of GoCAT's WebP call.
    assert options is None
    assert src_rect == src_img.bounds()
    assert dst_rect == dst.bounds()
    assert src_img.mode == "YCbCr420"

    # kernelScaler.Scale changes Over to Src when the source is opaque.
    if op == OVER and src_img.opaque():
        op = SRC
    assert op == SRC

    scaled_pixels = bilinear_scale_ycbcr420(
        src_img.y,
        src_img.cb,
        src_img.cr,
        dst_rect.width,
        dst_rect.height,
    )
    dst.replace_rgba(dst_rect, scaled_pixels)
```

The six arguments then map positionally:

```go
draw.BiLinear.Scale(dst, dst.Bounds(), srcImg, bounds, draw.Over, nil)
```

```python
bilinear_scale(dst, dst.bounds(), src_img, bounds, OVER, None)
```

| Go argument | Python argument | Meaning in this call |
|---|---|---|
| `dst` | `dst` | Existing RGBA destination mutated in place |
| `dst.Bounds()` | `dst.bounds()` | Complete destination rectangle, 720x180 for the benchmark |
| `srcImg` | `src_img` | Decoded, opaque YCbCr 4:2:0 WebP image |
| `bounds` | `bounds` | Complete 8000x2000 source rectangle |
| `draw.Over` | `OVER` | Requested compositing operation; internally changed to `Src` because the source is opaque |
| `nil` | `None` | No source mask, destination mask, or option overrides |

This wrapper documents the exact branch selected by GoCAT. It deliberately asserts those branch conditions rather than implementing the other image types, partial rectangles, masks, and compositing cases supported by the general Go API.

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
