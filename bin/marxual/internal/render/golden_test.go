package render

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPreprocessMarkdownGoldenFixtures(t *testing.T) {
	t.Parallel()

	renderer := NewMermaidASCIIRenderer()
	fixtures := []string{
		"basic.md",
		"mermaid-flow.md",
		"mermaid-sequence.md",
		"unsupported-mermaid.md",
	}

	for _, fixture := range fixtures {
		fixture := fixture
		t.Run(fixture, func(t *testing.T) {
			t.Parallel()

			inputPath := filepath.Join("..", "testdata", fixture)
			goldenPath := filepath.Join("..", "testdata", fixture+".golden")

			input, err := os.ReadFile(inputPath)
			if err != nil {
				t.Fatalf("read fixture: %v", err)
			}

			got := PreprocessMarkdown(string(input), renderer)

			if os.Getenv("UPDATE_GOLDEN") == "1" {
				if err := os.WriteFile(goldenPath, []byte(got), 0o644); err != nil {
					t.Fatalf("write golden: %v", err)
				}
			}

			want, err := os.ReadFile(goldenPath)
			if err != nil {
				t.Fatalf("read golden: %v", err)
			}

			if got != string(want) {
				t.Fatalf("golden mismatch for %s\n--- got ---\n%s\n--- want ---\n%s", fixture, got, string(want))
			}
		})
	}
}
