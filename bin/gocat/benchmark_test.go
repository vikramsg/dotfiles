package main

import (
	"bytes"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const defaultCorpusDir = "/home/vikram_orbio_earth/Desktop/Screenshots"

func benchmarkCorpus(t testing.TB) ([]string, string) {
	t.Helper()
	dir := os.Getenv("GOCAT_BENCH_CORPUS")
	if dir == "" {
		dir = defaultCorpusDir
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Skipf("benchmark corpus not available: %v", err)
	}

	var files []string
	var largest string
	var largestSize int64
	for _, entry := range entries {
		ext := strings.ToLower(filepath.Ext(entry.Name()))
		if ext != ".png" && ext != ".jpg" && ext != ".jpeg" && ext != ".gif" && ext != ".webp" {
			continue
		}
		path := filepath.Join(dir, entry.Name())
		files = append(files, path)
		if info, err := entry.Info(); err == nil && info.Size() > largestSize {
			largest = path
			largestSize = info.Size()
		}
	}
	if len(files) == 0 {
		t.Skipf("no supported images found in %s", dir)
	}
	return files, largest
}

func BenchmarkCorpus(b *testing.B) {
	imageFiles, _ := benchmarkCorpus(b)

	b.Run("Auto_AllFiles", func(b *testing.B) {
		for i := 0; i < b.N; i++ {
			for _, f := range imageFiles {
				var out bytes.Buffer
				run([]string{"--target", "720x420", f}, nil, &out, io.Discard)
			}
		}
	})

	b.Run("Fallback_AllFiles_720x420", func(b *testing.B) {
		for i := 0; i < b.N; i++ {
			for _, f := range imageFiles {
				var out bytes.Buffer
				run([]string{"--mode", "fallback", "--target", "720x420", f}, nil, &out, io.Discard)
			}
		}
	})

	mcatPath, err := exec.LookPath("mcat")
	if err == nil {
		b.Run("MCAT_AllFiles_720x420", func(b *testing.B) {
			for i := 0; i < b.N; i++ {
				for _, f := range imageFiles {
					cmd := exec.Command(mcatPath, "-i", "--kitty", "--spx", "720x420", "--img-width", "720px", "--img-height", "420px", "--no-center", "--silent", f)
					cmd.Stdout = io.Discard
					cmd.Stderr = io.Discard
					_ = cmd.Run()
				}
			}
		})
	}
}

func BenchmarkSingleLargeImage(b *testing.B) {
	_, targetFile := benchmarkCorpus(b)

	b.Run("Go_Auto", func(b *testing.B) {
		for i := 0; i < b.N; i++ {
			var out bytes.Buffer
			run([]string{"--target", "720x420", targetFile}, nil, &out, io.Discard)
		}
	})

	b.Run("Go_Fallback_DecodeResize_720x420", func(b *testing.B) {
		for i := 0; i < b.N; i++ {
			var out bytes.Buffer
			run([]string{"--mode", "fallback", "--target", "720x420", targetFile}, nil, &out, io.Discard)
		}
	})

	mcatPath, err := exec.LookPath("mcat")
	if err == nil {
		b.Run("MCAT_Process_720x420", func(b *testing.B) {
			for i := 0; i < b.N; i++ {
				cmd := exec.Command(mcatPath, "-i", "--kitty", "--spx", "720x420", "--img-width", "720px", "--img-height", "420px", "--no-center", "--silent", targetFile)
				cmd.Stdout = io.Discard
				cmd.Stderr = io.Discard
				_ = cmd.Run()
			}
		})
	}
}

func TestProcessWallTimeComparison(t *testing.T) {
	_, targetFile := benchmarkCorpus(t)

	gocatBin, err := filepath.Abs("gocat")
	if err != nil {
		t.Fatalf("failed to get absolute path to gocat: %v", err)
	}

	mcatPath, err := exec.LookPath("mcat")
	if err != nil {
		t.Skip("mcat not found")
	}

	// Warmup
	for i := 0; i < 3; i++ {
		_ = exec.Command(gocatBin, "--target", "720x420", targetFile).Run()
		_ = exec.Command(mcatPath, "-i", "--kitty", "--spx", "720x420", targetFile).Run()
	}

	iterations := 10

	// 1. gocat automatic path
	var gocatAutoTotal time.Duration
	for i := 0; i < iterations; i++ {
		start := time.Now()
		cmd := exec.Command(gocatBin, "--target", "720x420", targetFile)
		cmd.Stdout = io.Discard
		if err := cmd.Run(); err != nil {
			t.Fatalf("gocat failed: %v", err)
		}
		gocatAutoTotal += time.Since(start)
	}
	avgGocatAuto := gocatAutoTotal / time.Duration(iterations)

	// 2. mcat
	var mcatTotal time.Duration
	for i := 0; i < iterations; i++ {
		start := time.Now()
		cmd := exec.Command(mcatPath, "-i", "--kitty", "--spx", "720x420", "--img-width", "720px", "--img-height", "420px", "--no-center", "--silent", targetFile)
		cmd.Stdout = io.Discard
		if err := cmd.Run(); err != nil {
			t.Fatalf("mcat failed: %v", err)
		}
		mcatTotal += time.Since(start)
	}
	avgMcat := mcatTotal / time.Duration(iterations)

	// 3. gocat fallback (decode + resize)
	var gocatFallbackTotal time.Duration
	for i := 0; i < iterations; i++ {
		start := time.Now()
		cmd := exec.Command(gocatBin, "--mode", "fallback", "--target", "720x420", targetFile)
		cmd.Stdout = io.Discard
		if err := cmd.Run(); err != nil {
			t.Fatalf("gocat fallback failed: %v", err)
		}
		gocatFallbackTotal += time.Since(start)
	}
	avgGocatFallback := gocatFallbackTotal / time.Duration(iterations)

	info, _ := os.Stat(targetFile)
	t.Logf("\n=== Process Wall Time (%d warm runs on %s, %d bytes) ===", iterations, filepath.Base(targetFile), info.Size())
	t.Logf("gocat (automatic path):      %v", avgGocatAuto)
	t.Logf("mcat (Rust + SIMD resize):   %v", avgMcat)
	t.Logf("gocat (Scalar Go fallback):   %v", avgGocatFallback)
}
