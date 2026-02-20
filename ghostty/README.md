# Ghostty Terminal Setup Guide

This directory contains information regarding the configuration for Ghostty, a GPU-accelerated terminal emulator.

## Terminal Cell Math & The "Bottom Gap"

When using terminal multiplexers (like Tmux) or full-screen applications (like Neovim), you may occasionally notice a small, empty gap at the absolute bottom of the terminal window, below your status bar.

### Why This Happens
Terminal emulators render content strictly within a grid of fixed-size blocks (cells), determined by your font size. 

If you resize the Ghostty window, or if it opens at a default physical size, its total pixel height is rarely perfectly divisible by the exact pixel height of a single row of text. 

For example, if your window height can fit `50.5` rows of text, Tmux and Neovim can only draw exactly `50` rows. They cannot render half a row. Therefore, the remaining `0.5` rows of space (e.g., `10px`) is left completely blank at the bottom of the window, showing the default background color.

This is **not a bug** in Tmux or Neovim; it is a fundamental constraint of rendering text on a fixed grid within an arbitrary pixel resolution.

### Ghostty Configuration Fixes

If this gap is visually distracting, you can adjust how Ghostty handles "dead space" by modifying your `~/.config/ghostty/config` file.

#### 1. Balance the Padding (Recommended)
This takes the leftover pixel gap at the bottom/right and distributes it evenly across all four sides of the window. This softens the visual impact by creating a uniform border rather than one thick bar at the bottom.

```text
window-padding-balance = true
```

#### 2. Snap Resizing
This forces the Ghostty window frame to "snap" exclusively to dimensions that perfectly fit your grid cell sizes when you manually resize the window. This mathematically eliminates the possibility of leftover space, but some macOS window managers (or tiling setups) may fight or ignore this behavior.

```text
window-step-resize = true
```

#### 3. Color Extension
By default, the padding uses the `background` color. If you have a solid-colored Neovim status line or Tmux bar at the bottom, the gap might contrast sharply. You can tell Ghostty to extend the color of the *nearest grid cell* into the padding area, making the gap visually blend into your status bar.

```text
window-padding-color = extend
```