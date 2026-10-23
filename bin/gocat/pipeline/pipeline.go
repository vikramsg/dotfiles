package pipeline

import (
	"bytes"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	"image/png"
	"io"
	"math"
	"os"
	"path/filepath"
	"time"

	"golang.org/x/image/draw"
	_ "golang.org/x/image/webp"
)

var pngMagic = []byte{0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A}

// FastPathCheck checks if a given file path is a valid local PNG file.
// If valid, it returns true and the resolved canonical absolute path.
func FastPathCheck(filePath string) (bool, string, error) {
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		return false, "", err
	}

	info, err := os.Stat(absPath)
	if err != nil {
		return false, "", err
	}
	if info.IsDir() {
		return false, "", fmt.Errorf("%s is a directory", absPath)
	}

	f, err := os.Open(absPath)
	if err != nil {
		return false, "", err
	}
	defer f.Close()

	header := make([]byte, 8)
	n, err := io.ReadFull(f, header)
	if err != nil || n < 8 {
		return false, "", nil
	}

	if !bytes.Equal(header, pngMagic) {
		return false, "", nil
	}

	return true, absPath, nil
}

// BoundingBox holds width and height constraints.
type BoundingBox struct {
	MaxWidth  int
	MaxHeight int
}

// Timings records the duration of each image-processing stage.
type Timings struct {
	Decode     time.Duration
	Dimensions time.Duration
	Resize     time.Duration
	Encode     time.Duration
	Resized    bool
}

// ProcessedImage contains the encoded output and processing metadata.
type ProcessedImage struct {
	PNGData      []byte
	SourceWidth  int
	SourceHeight int
	OutputWidth  int
	OutputHeight int
	Timings      Timings
}

// CalculateTargetDimensions computes target dimensions preserving aspect ratio.
func CalculateTargetDimensions(origWidth, origHeight int, bbox BoundingBox) (int, int) {
	if origWidth <= 0 || origHeight <= 0 {
		return 1, 1
	}

	if bbox.MaxWidth <= 0 && bbox.MaxHeight <= 0 {
		return origWidth, origHeight
	}

	maxW := float64(bbox.MaxWidth)
	maxH := float64(bbox.MaxHeight)

	if maxW <= 0 {
		maxW = math.MaxFloat64
	}
	if maxH <= 0 {
		maxH = math.MaxFloat64
	}

	origW := float64(origWidth)
	origH := float64(origHeight)

	scaleW := maxW / origW
	scaleH := maxH / origH

	scale := math.Min(scaleW, scaleH)
	if scale >= 1.0 {
		// Image is smaller than bounding box; do not upscale by default
		return origWidth, origHeight
	}

	dstW := int(math.Round(origW * scale))
	dstH := int(math.Round(origH * scale))

	if dstW < 1 {
		dstW = 1
	}
	if dstH < 1 {
		dstH = 1
	}

	return dstW, dstH
}

// ProcessImage reads an image from reader, downscales to bbox if needed, and encodes to PNG.

func ProcessImage(r io.Reader, bbox BoundingBox) (ProcessedImage, error) {
	var timings Timings
	decodeStart := time.Now()
	srcImg, _, err := image.Decode(r)
	timings.Decode = time.Since(decodeStart)
	if err != nil {
		return ProcessedImage{}, fmt.Errorf("failed to decode image: %w", err)
	}

	dimensionsStart := time.Now()
	bounds := srcImg.Bounds()
	origW := bounds.Dx()
	origH := bounds.Dy()

	targetW, targetH := CalculateTargetDimensions(origW, origH, bbox)
	timings.Dimensions = time.Since(dimensionsStart)

	var finalImg image.Image = srcImg

	if targetW != origW || targetH != origH {
		timings.Resized = true
		resizeStart := time.Now()
		dst := image.NewRGBA(image.Rect(0, 0, targetW, targetH))
		// Use BiLinear downscaling for balanced speed and quality
		draw.BiLinear.Scale(dst, dst.Bounds(), srcImg, bounds, draw.Over, nil)
		finalImg = dst
		timings.Resize = time.Since(resizeStart)
	}

	var buf bytes.Buffer
	enc := png.Encoder{
		CompressionLevel: png.BestSpeed,
	}

	encodeStart := time.Now()
	if err := enc.Encode(&buf, finalImg); err != nil {
		return ProcessedImage{}, fmt.Errorf("failed to encode PNG: %w", err)
	}
	timings.Encode = time.Since(encodeStart)

	return ProcessedImage{
		PNGData:      buf.Bytes(),
		SourceWidth:  origW,
		SourceHeight: origH,
		OutputWidth:  targetW,
		OutputHeight: targetH,
		Timings:      timings,
	}, nil
}
