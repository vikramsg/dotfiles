package pipeline

import (
	"bytes"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"os"
	"path/filepath"
	"testing"
)

func TestCalculateTargetDimensions(t *testing.T) {
	tests := []struct {
		name      string
		origW     int
		origH     int
		bbox      BoundingBox
		expectedW int
		expectedH int
	}{
		{
			name:      "no constraint",
			origW:     1920,
			origH:     1080,
			bbox:      BoundingBox{MaxWidth: 0, MaxHeight: 0},
			expectedW: 1920,
			expectedH: 1080,
		},
		{
			name:      "image smaller than constraint (no upscale)",
			origW:     500,
			origH:     300,
			bbox:      BoundingBox{MaxWidth: 1000, MaxHeight: 1000},
			expectedW: 500,
			expectedH: 300,
		},
		{
			name:      "constrained by width",
			origW:     2000,
			origH:     1000,
			bbox:      BoundingBox{MaxWidth: 1000, MaxHeight: 1000},
			expectedW: 1000,
			expectedH: 500,
		},
		{
			name:      "constrained by height",
			origW:     1000,
			origH:     2000,
			bbox:      BoundingBox{MaxWidth: 1000, MaxHeight: 1000},
			expectedW: 500,
			expectedH: 1000,
		},
		{
			name:      "arbitrary ratio fit",
			origW:     1600,
			origH:     1200,
			bbox:      BoundingBox{MaxWidth: 800, MaxHeight: 600},
			expectedW: 800,
			expectedH: 600,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			w, h := CalculateTargetDimensions(tc.origW, tc.origH, tc.bbox)
			if w != tc.expectedW || h != tc.expectedH {
				t.Errorf("got (%d, %d), expected (%d, %d)", w, h, tc.expectedW, tc.expectedH)
			}
		})
	}
}

func TestFastPathCheck(t *testing.T) {
	tempDir := t.TempDir()

	// Create a valid PNG file
	pngPath := filepath.Join(tempDir, "test.png")
	img := image.NewRGBA(image.Rect(0, 0, 10, 10))
	f, err := os.Create(pngPath)
	if err != nil {
		t.Fatalf("failed to create file: %v", err)
	}
	if err := png.Encode(f, img); err != nil {
		t.Fatalf("failed to encode PNG: %v", err)
	}
	f.Close()

	// Create a non-PNG file (JPEG)
	jpgPath := filepath.Join(tempDir, "test.jpg")
	fj, err := os.Create(jpgPath)
	if err != nil {
		t.Fatalf("failed to create jpg: %v", err)
	}
	if err := jpeg.Encode(fj, img, nil); err != nil {
		t.Fatalf("failed to encode JPEG: %v", err)
	}
	fj.Close()

	// Test valid PNG
	isPNG, absPath, err := FastPathCheck(pngPath)
	if err != nil || !isPNG {
		t.Errorf("expected FastPathCheck to return true for PNG, got %v (err: %v)", isPNG, err)
	}
	if absPath != pngPath {
		t.Errorf("expected absPath %s, got %s", pngPath, absPath)
	}

	// Test non-PNG
	isPNG, _, err = FastPathCheck(jpgPath)
	if err != nil || isPNG {
		t.Errorf("expected FastPathCheck to return false for JPEG, got %v (err: %v)", isPNG, err)
	}

	// Test non-existent file
	isPNG, _, err = FastPathCheck(filepath.Join(tempDir, "non-existent.png"))
	if err == nil || isPNG {
		t.Errorf("expected error for non-existent file")
	}
}

func TestProcessImage(t *testing.T) {
	// Create a test RGBA image
	src := image.NewRGBA(image.Rect(0, 0, 200, 100))
	for y := 0; y < 100; y++ {
		for x := 0; x < 200; x++ {
			src.Set(x, y, color.RGBA{R: uint8(x), G: uint8(y), B: 100, A: 255})
		}
	}

	var rawPNG bytes.Buffer
	if err := png.Encode(&rawPNG, src); err != nil {
		t.Fatalf("failed to encode test png: %v", err)
	}

	// Downscale to max 100x100
	bbox := BoundingBox{MaxWidth: 100, MaxHeight: 100}
	processed, err := ProcessImage(bytes.NewReader(rawPNG.Bytes()), bbox)
	if err != nil {
		t.Fatalf("ProcessImage failed: %v", err)
	}

	if processed.OutputWidth != 100 || processed.OutputHeight != 50 {
		t.Errorf("expected target 100x50, got %dx%d", processed.OutputWidth, processed.OutputHeight)
	}
	if !processed.Timings.Resized {
		t.Error("expected resize timing to be recorded")
	}

	// Decode result to verify valid PNG output
	decoded, err := png.Decode(bytes.NewReader(processed.PNGData))
	if err != nil {
		t.Fatalf("failed to decode output PNG: %v", err)
	}
	if decoded.Bounds().Dx() != 100 || decoded.Bounds().Dy() != 50 {
		t.Errorf("decoded bounds mismatch: got %v", decoded.Bounds())
	}
}
