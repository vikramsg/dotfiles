package render

import (
	"strings"
	"testing"

	styles "github.com/charmbracelet/glamour/styles"
)

func TestResolveStyleDefaultsToTokyoNight(t *testing.T) {
	t.Parallel()

	got, err := ResolveStyle("")
	if err != nil {
		t.Fatalf("ResolveStyle returned error: %v", err)
	}

	if got != styles.TokyoNightStyle {
		t.Fatalf("ResolveStyle(\"\") = %q, want %q", got, styles.TokyoNightStyle)
	}
}

func TestResolveStyleRejectsUnknownValues(t *testing.T) {
	t.Parallel()

	_, err := ResolveStyle("catppuccin")
	if err == nil {
		t.Fatal("ResolveStyle error = nil, want error")
	}

	if !strings.Contains(err.Error(), "invalid style") {
		t.Fatalf("ResolveStyle error = %q, want invalid style", err.Error())
	}
}

func TestRenderMarkdownWrapsToRequestedWidth(t *testing.T) {
	t.Parallel()

	input := "This paragraph should wrap differently when the terminal width changes."

	narrow, err := RenderMarkdown(input, styles.TokyoNightStyle, 20)
	if err != nil {
		t.Fatalf("RenderMarkdown returned error for narrow width: %v", err)
	}

	wide, err := RenderMarkdown(input, styles.TokyoNightStyle, 60)
	if err != nil {
		t.Fatalf("RenderMarkdown returned error for wide width: %v", err)
	}

	if narrow == wide {
		t.Fatal("RenderMarkdown should produce different output for different widths")
	}

	if !strings.Contains(narrow, "\n") {
		t.Fatalf("narrow output should wrap onto multiple lines: %q", narrow)
	}
}
