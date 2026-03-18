package render

import (
	"errors"
	"strings"
	"testing"
)

type stubRenderer struct {
	output string
	err    error
	inputs []string
}

func (s *stubRenderer) Render(input string) (string, error) {
	s.inputs = append(s.inputs, input)
	if s.err != nil {
		return "", s.err
	}
	return s.output, nil
}

func TestPreprocessMarkdownReplacesMermaidFence(t *testing.T) {
	t.Parallel()

	renderer := &stubRenderer{output: "graph TD\nA-->B"}
	input := "before\n\n```mermaid\nflowchart TD\n  A --> B\n```\n\nafter\n"

	got := PreprocessMarkdown(input, renderer)

	if len(renderer.inputs) != 1 {
		t.Fatalf("renderer called %d times, want 1", len(renderer.inputs))
	}

	if !strings.Contains(got, "```text\ngraph TD\nA-->B\n```") {
		t.Fatalf("preprocessed markdown missing text fence: %q", got)
	}

	if strings.Contains(got, "```mermaid") {
		t.Fatalf("preprocessed markdown still contains mermaid fence: %q", got)
	}
}

func TestPreprocessMarkdownHandlesMultipleMermaidFences(t *testing.T) {
	t.Parallel()

	renderer := &stubRenderer{output: "ASCII"}
	input := strings.Join([]string{
		"```mermaid",
		"flowchart TD",
		"  A --> B",
		"```",
		"",
		"```mermaid",
		"sequenceDiagram",
		"  Alice->>Bob: hi",
		"```",
		"",
	}, "\n")

	got := PreprocessMarkdown(input, renderer)

	if len(renderer.inputs) != 2 {
		t.Fatalf("renderer called %d times, want 2", len(renderer.inputs))
	}

	if strings.Count(got, "```text\nASCII\n```") != 2 {
		t.Fatalf("expected both mermaid fences to be replaced: %q", got)
	}
}

func TestPreprocessMarkdownLeavesNonMermaidFencesUntouched(t *testing.T) {
	t.Parallel()

	renderer := &stubRenderer{output: "unused"}
	input := "```go\nfmt.Println(\"hi\")\n```\n"

	got := PreprocessMarkdown(input, renderer)

	if len(renderer.inputs) != 0 {
		t.Fatalf("renderer called %d times, want 0", len(renderer.inputs))
	}

	if got != input {
		t.Fatalf("preprocessed markdown changed non-mermaid fence: %q", got)
	}
}

func TestPreprocessMarkdownKeepsFenceAndAddsWarningOnRenderFailure(t *testing.T) {
	t.Parallel()

	renderer := &stubRenderer{err: errors.New("unsupported diagram")}
	input := "```mermaid\nflowchart TD\n  A --> B\n```\n"

	got := PreprocessMarkdown(input, renderer)

	if !strings.Contains(got, "> Warning: failed to render Mermaid diagram: unsupported diagram") {
		t.Fatalf("preprocessed markdown missing warning block: %q", got)
	}

	if !strings.Contains(got, input) {
		t.Fatalf("preprocessed markdown should keep original mermaid fence: %q", got)
	}
}
