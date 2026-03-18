package render

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/glamour"
	styles "github.com/charmbracelet/glamour/styles"
)

const DefaultStyle = styles.TokyoNightStyle

var builtinStyles = []string{
	styles.AsciiStyle,
	styles.AutoStyle,
	styles.DarkStyle,
	styles.DraculaStyle,
	styles.TokyoNightStyle,
	styles.LightStyle,
	styles.NoTTYStyle,
	styles.PinkStyle,
}

type TermRenderer struct {
	Style string
}

func (r TermRenderer) Render(input string, width int) (string, error) {
	return RenderMarkdown(input, r.Style, width)
}

func AvailableStyles() []string {
	available := make([]string, len(builtinStyles))
	copy(available, builtinStyles)
	return available
}

func AvailableStylesHelp() string {
	return strings.Join(AvailableStyles(), ", ")
}

func ResolveStyle(style string) (string, error) {
	if style == "" {
		return DefaultStyle, nil
	}

	for _, candidate := range builtinStyles {
		if style == candidate {
			return style, nil
		}
	}

	return "", fmt.Errorf("invalid style %q; available styles: %s", style, AvailableStylesHelp())
}

func RenderMarkdown(input string, style string, width int) (string, error) {
	if width < 1 {
		width = 1
	}

	resolvedStyle, err := ResolveStyle(style)
	if err != nil {
		return "", err
	}

	renderer, err := glamour.NewTermRenderer(
		glamour.WithStandardStyle(resolvedStyle),
		glamour.WithWordWrap(width),
	)
	if err != nil {
		return "", err
	}

	return renderer.Render(input)
}
