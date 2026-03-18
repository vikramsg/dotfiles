package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestRunHelpListsAvailableStyles(t *testing.T) {
	t.Parallel()

	var stdout bytes.Buffer
	var stderr bytes.Buffer

	err := run([]string{"--help"}, strings.NewReader("ignored"), &stdout, &stderr)
	if err != nil {
		t.Fatalf("run returned error: %v", err)
	}

	helpText := stderr.String()
	for _, want := range []string{
		"--style",
		"tokyo-night",
		"dracula",
		"ascii",
		"notty",
	} {
		if !strings.Contains(helpText, want) {
			t.Fatalf("help output missing %q: %s", want, helpText)
		}
	}
}

func TestRunRejectsUnknownStyle(t *testing.T) {
	t.Parallel()

	var stdout bytes.Buffer
	var stderr bytes.Buffer

	err := run([]string{"--style", "catppuccin", "internal/testdata/basic.md"}, strings.NewReader("ignored"), &stdout, &stderr)
	if err == nil {
		t.Fatal("run error = nil, want error")
	}

	if !strings.Contains(err.Error(), "invalid style") {
		t.Fatalf("run error = %q, want invalid style message", err.Error())
	}

	if !strings.Contains(err.Error(), "tokyo-night") {
		t.Fatalf("run error = %q, want available styles listed", err.Error())
	}
	if stdout.Len() != 0 {
		t.Fatalf("stdout should be empty on validation error: %q", stdout.String())
	}
}

func TestLoadInputFromFile(t *testing.T) {
	t.Parallel()

	got, err := loadInput("internal/testdata/basic.md", strings.NewReader("ignored"))
	if err != nil {
		t.Fatalf("loadInput returned error: %v", err)
	}

	if !strings.Contains(got, "# Marxual") {
		t.Fatalf("loadInput() did not return file content: %q", got)
	}
}

func TestLoadInputFromStdin(t *testing.T) {
	t.Parallel()

	got, err := loadInput("-", strings.NewReader("# from stdin\n"))
	if err != nil {
		t.Fatalf("loadInput returned error: %v", err)
	}

	if got != "# from stdin\n" {
		t.Fatalf("loadInput() = %q, want %q", got, "# from stdin\n")
	}
}

func TestLoadInputRejectsEmptyStdin(t *testing.T) {
	t.Parallel()

	_, err := loadInput("-", strings.NewReader("   \n\t"))
	if err == nil {
		t.Fatal("loadInput() error = nil, want error")
	}

	if !strings.Contains(err.Error(), "stdin is empty") {
		t.Fatalf("loadInput() error = %q, want substring %q", err.Error(), "stdin is empty")
	}
}

func TestLoadInputRejectsMissingFile(t *testing.T) {
	t.Parallel()

	_, err := loadInput("internal/testdata/does-not-exist.md", strings.NewReader("ignored"))
	if err == nil {
		t.Fatal("loadInput() error = nil, want error")
	}

	if !strings.Contains(err.Error(), "failed to read") {
		t.Fatalf("loadInput() error = %q, want substring %q", err.Error(), "failed to read")
	}
}
