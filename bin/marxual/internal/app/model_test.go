package app

import (
	"fmt"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
)

type stubMarkdownRenderer struct {
	widths []int
	output string
	err    error
}

func (s *stubMarkdownRenderer) Render(input string, width int) (string, error) {
	s.widths = append(s.widths, width)
	if s.err != nil {
		return "", s.err
	}
	if s.output != "" {
		return s.output, nil
	}
	return fmt.Sprintf("width=%d\n%s", width, input), nil
}

func TestModelRerendersOnResize(t *testing.T) {
	t.Parallel()

	renderer := &stubMarkdownRenderer{}
	m := NewModel("# Original", "# Transformed", renderer)

	next, _ := m.Update(tea.WindowSizeMsg{Width: 40, Height: 10})
	updated := next.(Model)

	if len(renderer.widths) != 1 || renderer.widths[0] != 40 {
		t.Fatalf("renderer widths = %v, want [40]", renderer.widths)
	}

	next, _ = updated.Update(tea.WindowSizeMsg{Width: 20, Height: 10})
	updated = next.(Model)

	if len(renderer.widths) != 2 || renderer.widths[1] != 20 {
		t.Fatalf("renderer widths = %v, want second width 20", renderer.widths)
	}

	if !strings.Contains(updated.rendered, "width=20") {
		t.Fatalf("rendered output was not refreshed on resize: %q", updated.rendered)
	}
}

func TestModelWithSizeRendersImmediately(t *testing.T) {
	t.Parallel()

	renderer := &stubMarkdownRenderer{}
	m := NewModel("# Original", "# Transformed", renderer).WithSize(50, 12)

	if len(renderer.widths) != 1 || renderer.widths[0] != 50 {
		t.Fatalf("renderer widths = %v, want [50]", renderer.widths)
	}

	if !strings.Contains(m.rendered, "width=50") {
		t.Fatalf("rendered output was not created during WithSize: %q", m.rendered)
	}
}

func TestModelScrollKeysMoveViewport(t *testing.T) {
	t.Parallel()

	renderer := &stubMarkdownRenderer{output: strings.Repeat("line\n", 30)}
	m := NewModel("# Original", "# Transformed", renderer)

	next, _ := m.Update(tea.WindowSizeMsg{Width: 30, Height: 5})
	updated := next.(Model)

	if updated.viewport.YOffset != 0 {
		t.Fatalf("initial YOffset = %d, want 0", updated.viewport.YOffset)
	}

	next, _ = updated.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'j'}})
	updated = next.(Model)

	if updated.viewport.YOffset == 0 {
		t.Fatal("expected j key to scroll viewport down")
	}

	next, _ = updated.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'g'}})
	updated = next.(Model)

	if updated.viewport.YOffset != 0 {
		t.Fatalf("expected g key to jump to top, got %d", updated.viewport.YOffset)
	}

	next, _ = updated.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'G'}})
	updated = next.(Model)

	if !updated.viewport.AtBottom() {
		t.Fatal("expected G key to jump to bottom")
	}
}
