package render

import (
	"strings"
	"testing"

	styles "github.com/charmbracelet/glamour/styles"
	ansi "github.com/charmbracelet/x/ansi"
)

func stripANSI(input string) string {
	return ansi.Strip(input)
}

func firstNonEmptyLine(input string) string {
	for _, line := range strings.Split(input, "\n") {
		if strings.TrimSpace(line) != "" {
			return line
		}
	}

	return ""
}

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

func TestRenderMarkdownUsesMcatHeadingIcons(t *testing.T) {
	t.Parallel()

	testCases := []struct {
		name  string
		input string
		icon  string
		text  string
	}{
		{name: "h1", input: "# Alpha\n", icon: "󰎤", text: "Alpha"},
		{name: "h2", input: "## Beta\n", icon: "󰎧", text: "Beta"},
		{name: "h3", input: "### Gamma\n", icon: "󰎬", text: "Gamma"},
		{name: "h4", input: "#### Delta\n", icon: "󰎮", text: "Delta"},
		{name: "h5", input: "##### Epsilon\n", icon: "󰎰", text: "Epsilon"},
		{name: "h6", input: "###### Zeta\n", icon: "󰎵", text: "Zeta"},
	}

	for _, tc := range testCases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			rendered, err := RenderMarkdown(tc.input, styles.TokyoNightStyle, 32)
			if err != nil {
				t.Fatalf("RenderMarkdown returned error: %v", err)
			}

			visible := firstNonEmptyLine(stripANSI(rendered))
			if !strings.Contains(visible, tc.icon) {
				t.Fatalf("heading line %q missing icon %q", visible, tc.icon)
			}

			if !strings.Contains(visible, tc.text) {
				t.Fatalf("heading line %q missing text %q", visible, tc.text)
			}

			if strings.Contains(visible, "#") {
				t.Fatalf("heading line should not contain markdown markers: %q", visible)
			}
		})
	}
}

func TestRenderMarkdownPadsHeadingBarsToRequestedWidth(t *testing.T) {
	t.Parallel()

	rendered, err := RenderMarkdown("# Heading\n", styles.TokyoNightStyle, 24)
	if err != nil {
		t.Fatalf("RenderMarkdown returned error: %v", err)
	}

	line := firstNonEmptyLine(rendered)
	if got := ansi.StringWidth(line); got != 24 {
		t.Fatalf("heading width = %d, want 24; line=%q", got, line)
	}
}

func TestRenderMarkdownKeepsBodyRenderingWithCustomBlocks(t *testing.T) {
	t.Parallel()

	input := strings.Join([]string{
		"# Heading",
		"",
		"This paragraph should still wrap normally inside the rendered output.",
		"",
		"```bash",
		"echo hello from bash",
		"```",
		"",
	}, "\n")

	rendered, err := RenderMarkdown(input, styles.TokyoNightStyle, 28)
	if err != nil {
		t.Fatalf("RenderMarkdown returned error: %v", err)
	}

	visible := stripANSI(rendered)
	if !strings.Contains(visible, "󰎤 Heading") {
		t.Fatalf("rendered output missing custom heading: %q", visible)
	}

	if !strings.Contains(visible, "This paragraph should") || !strings.Contains(visible, "still wrap normally") || !strings.Contains(visible, "inside the rendered") {
		t.Fatalf("rendered output should keep wrapped paragraph rendering: %q", visible)
	}

	if !strings.Contains(visible, " bash") {
		t.Fatalf("rendered output missing bash code-fence label: %q", visible)
	}

	if !strings.Contains(visible, "echo hello from bash") {
		t.Fatalf("rendered output missing code body: %q", visible)
	}
}

func TestRenderMarkdownAddsGlyphBasedCodeFenceLabels(t *testing.T) {
	t.Parallel()

	input := "```bash\necho hi\n```\n"
	rendered, err := RenderMarkdown(input, styles.TokyoNightStyle, 40)
	if err != nil {
		t.Fatalf("RenderMarkdown returned error: %v", err)
	}

	visible := stripANSI(rendered)
	if !strings.Contains(visible, " bash") {
		t.Fatalf("rendered output missing bash label: %q", visible)
	}

	if !strings.Contains(visible, "echo hi") {
		t.Fatalf("rendered output missing code content: %q", visible)
	}
}

func TestRenderMarkdownUsesCodeFenceLabelsAfterMermaidPreprocessing(t *testing.T) {
	t.Parallel()

	input := "```mermaid\nflowchart TD\n  A --> B\n```\n"
	preprocessed := PreprocessMarkdown(input, &stubRenderer{output: "graph TD\nA-->B"})

	rendered, err := RenderMarkdown(preprocessed, styles.TokyoNightStyle, 40)
	if err != nil {
		t.Fatalf("RenderMarkdown returned error: %v", err)
	}

	visible := stripANSI(rendered)
	if !strings.Contains(visible, "󰈙 text") {
		t.Fatalf("rendered output missing text fence label: %q", visible)
	}

	if !strings.Contains(visible, "graph TD") {
		t.Fatalf("rendered output missing mermaid ascii content: %q", visible)
	}
}
