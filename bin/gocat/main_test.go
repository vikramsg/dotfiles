package main

import (
	"bytes"
	"encoding/base64"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const testWebPBase64 = "UklGRrIBAABXRUJQVlA4TKUBAAAvSsAYAA8w//M///MfeJAkbXvaSG7m8Q3GfYSBJekwQztm/IcZlgwnmWImn2BK7aFmBtnVir6q//8VOkFE/xm4baTIu8c48ArEo6+B3zFKYln3pqClSCKX0begFTAXFOLXHSyF8cCNcZEG4OywuA4KVVfJCiArU7GAgJI8+lJP/OKMT/fBAjevg1cYB7YVkFuWga2lyPi5I0HFy5YTpWIHg0RZpkniRVW9odHAKOwosWuOGdxIyn2OvaCDvhg/we6TwadPBPbqBV58MsLmMJ8yZnOWk8SRz4N+QoyPL+MnamzMvcE1rHNEr91F9GKZPVUcS9w7PhhH36suB9qPeYb/oLk6cuTiJ0wOK3m5h1cKjW6EVZCYMK7dxcKCBdgP9HkKr9gkAO2P8GKZGWVdIAatQa+1IDpt6qyorVwdy01xdW8Jkfk6xjEXmVQQ+HQdFr6OKhIN34dXWq0+0qr6EJSCeeVLH9+gvGTLyqM65PQ44ihzlTXxQKjKbAvshXgir7Lil9w4L2bvMycmjQcqXaMCO6BlY28i+FOLzbfI1vEqxAhotocAAA=="

func createTestPNG(t *testing.T, dir, filename string, w, h int) string {
	t.Helper()
	p := filepath.Join(dir, filename)
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			img.Set(x, y, color.RGBA{R: 200, G: 100, B: 50, A: 255})
		}
	}
	f, err := os.Create(p)
	if err != nil {
		t.Fatalf("failed to create image file: %v", err)
	}
	defer f.Close()

	if err := png.Encode(f, img); err != nil {
		t.Fatalf("failed to encode png: %v", err)
	}
	return p
}

func createTestJPEG(t *testing.T, dir, filename string, w, h int) string {
	t.Helper()
	p := filepath.Join(dir, filename)
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	f, err := os.Create(p)
	if err != nil {
		t.Fatalf("failed to create image file: %v", err)
	}
	defer f.Close()

	if err := jpeg.Encode(f, img, nil); err != nil {
		t.Fatalf("failed to encode jpeg: %v", err)
	}
	return p
}

func createTestWebP(t *testing.T, dir, filename string) string {
	t.Helper()
	raw, err := base64.StdEncoding.DecodeString(testWebPBase64)
	if err != nil {
		t.Fatalf("failed to decode WebP fixture: %v", err)
	}
	p := filepath.Join(dir, filename)
	if err := os.WriteFile(p, raw, 0o600); err != nil {
		t.Fatalf("failed to create WebP fixture: %v", err)
	}
	return p
}

func decodeDirectStreamPNG(t *testing.T, out string) image.Image {
	t.Helper()
	commands := strings.Split(out, "\x1b\\")
	if len(commands) > 0 && commands[len(commands)-1] == "" {
		commands = commands[:len(commands)-1]
	}

	var assembledB64 strings.Builder
	for _, cmd := range commands {
		clean := strings.TrimPrefix(cmd, "\x1b_G")
		parts := strings.SplitN(clean, ";", 2)
		if len(parts) == 2 {
			assembledB64.WriteString(parts[1])
		}
	}

	pngBytes, err := base64.StdEncoding.DecodeString(assembledB64.String())
	if err != nil {
		t.Fatalf("failed to decode base64 from stream: %v", err)
	}
	decoded, err := png.Decode(bytes.NewReader(pngBytes))
	if err != nil {
		t.Fatalf("reconstructed stream is not a valid PNG: %v", err)
	}
	return decoded
}

func TestCLIFastPath(t *testing.T) {
	tempDir := t.TempDir()
	pngPath := createTestPNG(t, tempDir, "sample.png", 400, 200)

	var stdout, stderr bytes.Buffer
	exitCode := run([]string{pngPath}, nil, &stdout, &stderr)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Stderr: %s", exitCode, stderr.String())
	}

	out := stdout.String()
	if !strings.Contains(out, "t=f") {
		t.Errorf("expected fast-path output with t=f, got: %s", out)
	}
	if !strings.Contains(out, "a=T") {
		t.Errorf("expected Kitty action a=T, got: %s", out)
	}
}

func TestCLIFallbackJPEGAndReconstruct(t *testing.T) {
	tempDir := t.TempDir()
	jpgPath := createTestJPEG(t, tempDir, "sample.jpg", 400, 200)

	var stdout, stderr bytes.Buffer
	exitCode := run([]string{"--target", "100x100", jpgPath}, nil, &stdout, &stderr)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Stderr: %s", exitCode, stderr.String())
	}

	out := stdout.String()
	if !strings.Contains(out, "t=d") {
		t.Errorf("expected direct stream output with t=d, got: %s", out)
	}

	decodedImg := decodeDirectStreamPNG(t, out)

	// Since original was 400x200 and bbox was 100x100, target should be 100x50
	if decodedImg.Bounds().Dx() != 100 || decodedImg.Bounds().Dy() != 50 {
		t.Errorf("expected reconstructed image to be 100x50, got %dx%d", decodedImg.Bounds().Dx(), decodedImg.Bounds().Dy())
	}
}

func TestCLIWebPFallback(t *testing.T) {
	webpPath := createTestWebP(t, t.TempDir(), "sample.webp")

	var stdout, stderr bytes.Buffer
	exitCode := run([]string{"--target", "100x100", webpPath}, nil, &stdout, &stderr)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Stderr: %s", exitCode, stderr.String())
	}
	if !strings.Contains(stdout.String(), "t=d") {
		t.Errorf("expected WebP fallback output with t=d")
	}
	decodedImg := decodeDirectStreamPNG(t, stdout.String())
	if decodedImg.Bounds().Dx() != 75 || decodedImg.Bounds().Dy() != 100 {
		t.Errorf("expected reconstructed WebP to be 75x100, got %dx%d", decodedImg.Bounds().Dx(), decodedImg.Bounds().Dy())
	}

	stdout.Reset()
	stderr.Reset()
	exitCode = run([]string{"--mode", "passthrough", webpPath}, nil, &stdout, &stderr)
	if exitCode == 0 {
		t.Fatal("expected passthrough mode to reject WebP")
	}
}

func TestCLIWebPStdin(t *testing.T) {
	webpPath := createTestWebP(t, t.TempDir(), "sample.webp")
	raw, err := os.ReadFile(webpPath)
	if err != nil {
		t.Fatalf("failed to read WebP fixture: %v", err)
	}

	var stdout, stderr bytes.Buffer
	exitCode := run([]string{"--target", "100x100", "-"}, bytes.NewReader(raw), &stdout, &stderr)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Stderr: %s", exitCode, stderr.String())
	}
	if !strings.Contains(stdout.String(), "t=d") {
		t.Errorf("expected WebP stdin output with t=d")
	}
}

func TestCLIStdinStreaming(t *testing.T) {
	tempDir := t.TempDir()
	pngPath := createTestPNG(t, tempDir, "sample.png", 300, 150)
	rawBytes, err := os.ReadFile(pngPath)
	if err != nil {
		t.Fatalf("failed to read test png: %v", err)
	}

	var stdout, stderr bytes.Buffer
	stdin := bytes.NewReader(rawBytes)
	exitCode := run([]string{"-"}, stdin, &stdout, &stderr)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Stderr: %s", exitCode, stderr.String())
	}

	out := stdout.String()
	if !strings.Contains(out, "t=d") {
		t.Errorf("expected fallback t=d stream for stdin, got: %s", out)
	}
}

func TestCLIInvalidArguments(t *testing.T) {
	var stdout, stderr bytes.Buffer
	exitCode := run([]string{"--target", "invalid-geometry", "nonexistent.png"}, nil, &stdout, &stderr)
	if exitCode == 0 {
		t.Errorf("expected non-zero exit code for invalid geometry")
	}
}
