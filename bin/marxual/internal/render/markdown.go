package render

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/glamour"
	styles "github.com/charmbracelet/glamour/styles"
	"github.com/charmbracelet/lipgloss"
	ansi "github.com/charmbracelet/x/ansi"
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

type segmentKind int

const (
	segmentMarkdown segmentKind = iota
	segmentHeading
	segmentFence
)

type markdownSegment struct {
	kind      segmentKind
	content   string
	heading   headingSegment
	codeFence codeFenceSegment
}

type headingSegment struct {
	level int
	text  string
}

type codeFenceSegment struct {
	block    string
	language string
}

type renderTheme struct {
	headingFG string
	headingBG string
	labelFG   string
	labelBG   string
	plain     bool
}

var headingIcons = map[int]string{
	1: "󰎤",
	2: "󰎧",
	3: "󰎬",
	4: "󰎮",
	5: "󰎰",
	6: "󰎵",
}

var codeFenceIcons = map[string]string{
	"bash":       "",
	"console":    "",
	"fish":       "",
	"go":         "",
	"golang":     "",
	"javascript": "",
	"js":         "",
	"json":       "",
	"lua":        "",
	"markdown":   "󰍔",
	"md":         "󰍔",
	"python":     "",
	"py":         "",
	"shell":      "",
	"sh":         "",
	"text":       "󰈙",
	"toml":       "",
	"ts":         "",
	"typescript": "",
	"yaml":       "",
	"yml":        "",
	"zsh":        "",
}

var styleThemes = map[string]renderTheme{
	styles.AsciiStyle:      {plain: true},
	styles.AutoStyle:       {headingFG: "#1f2937", headingBG: "#cbd5e1", labelFG: "#1f2937", labelBG: "#dbe4f0"},
	styles.DarkStyle:       {headingFG: "#f8fafc", headingBG: "#334155", labelFG: "#e2e8f0", labelBG: "#1e293b"},
	styles.DraculaStyle:    {headingFG: "#f8f8f2", headingBG: "#44475a", labelFG: "#f1fa8c", labelBG: "#282a36"},
	styles.TokyoNightStyle: {headingFG: "#c0caf5", headingBG: "#3b4261", labelFG: "#c0caf5", labelBG: "#24283b"},
	styles.LightStyle:      {headingFG: "#1f2937", headingBG: "#dbe4f0", labelFG: "#334155", labelBG: "#e5edf7"},
	styles.NoTTYStyle:      {plain: true},
	styles.PinkStyle:       {headingFG: "#fff1f2", headingBG: "#be185d", labelFG: "#831843", labelBG: "#fbcfe8"},
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

	segments := splitMarkdownSegments(input)
	if len(segments) == 0 {
		return "", nil
	}

	theme := themeForStyle(resolvedStyle)
	parts := make([]string, 0, len(segments))
	for _, segment := range segments {
		part, err := renderSegment(renderer, theme, segment, width)
		if err != nil {
			return "", err
		}
		if part == "" {
			continue
		}
		parts = append(parts, part)
	}

	return strings.Join(parts, "\n\n"), nil
}

func splitMarkdownSegments(input string) []markdownSegment {
	if input == "" {
		return nil
	}

	lines := strings.SplitAfter(input, "\n")
	segments := make([]markdownSegment, 0, len(lines))
	var markdown strings.Builder

	flushMarkdown := func() {
		if markdown.Len() == 0 {
			return
		}
		segments = append(segments, markdownSegment{kind: segmentMarkdown, content: markdown.String()})
		markdown.Reset()
	}

	for index := 0; index < len(lines); {
		marker, info, ok := parseFenceStart(lines[index])
		if ok {
			if end := findFenceEnd(lines, index+1, marker); end != -1 {
				flushMarkdown()
				segments = append(segments, markdownSegment{
					kind: segmentFence,
					codeFence: codeFenceSegment{
						block:    strings.Join(lines[index:end+1], ""),
						language: fenceLanguage(info),
					},
				})
				index = end + 1
				continue
			}
		}

		if level, text, ok := parseATXHeading(lines[index]); ok {
			flushMarkdown()
			segments = append(segments, markdownSegment{
				kind:    segmentHeading,
				heading: headingSegment{level: level, text: text},
			})
			index++
			continue
		}

		markdown.WriteString(lines[index])
		index++
	}

	flushMarkdown()
	return segments
}

func parseATXHeading(line string) (int, string, bool) {
	trimmedLine := strings.TrimRight(line, "\r\n")
	if trimmedLine == "" {
		return 0, "", false
	}

	leadingSpaces := len(trimmedLine) - len(strings.TrimLeft(trimmedLine, " "))
	if leadingSpaces > 3 {
		return 0, "", false
	}

	rest := trimmedLine[leadingSpaces:]
	if rest == "" || rest[0] != '#' {
		return 0, "", false
	}

	level := 0
	for level < len(rest) && rest[level] == '#' {
		level++
	}

	if level == 0 || level > 6 {
		return 0, "", false
	}

	if len(rest) > level && rest[level] != ' ' && rest[level] != '\t' {
		return 0, "", false
	}

	content := trimClosingHeadingMarkers(strings.TrimSpace(rest[level:]))
	return level, content, true
}

func trimClosingHeadingMarkers(content string) string {
	content = strings.TrimSpace(content)
	if content == "" {
		return ""
	}

	trimmed := strings.TrimRight(content, " \t")
	markerStart := len(trimmed)
	for markerStart > 0 && trimmed[markerStart-1] == '#' {
		markerStart--
	}

	if markerStart == len(trimmed) {
		return content
	}

	if markerStart > 0 && (trimmed[markerStart-1] == ' ' || trimmed[markerStart-1] == '\t') {
		return strings.TrimSpace(trimmed[:markerStart])
	}

	return content
}

func renderSegment(renderer *glamour.TermRenderer, theme renderTheme, segment markdownSegment, width int) (string, error) {
	switch segment.kind {
	case segmentHeading:
		return renderHeadingBar(theme, segment.heading, width), nil
	case segmentFence:
		return renderCodeFence(renderer, theme, segment.codeFence, width)
	default:
		return renderMarkdownChunk(renderer, segment.content)
	}
}

func renderMarkdownChunk(renderer *glamour.TermRenderer, input string) (string, error) {
	if strings.TrimSpace(input) == "" {
		return "", nil
	}

	rendered, err := renderer.Render(input)
	if err != nil {
		return "", err
	}

	return strings.Trim(rendered, "\n"), nil
}

func renderHeadingBar(theme renderTheme, heading headingSegment, width int) string {
	icon := headingIcons[heading.level]
	content := strings.TrimSpace(heading.text)
	if content == "" {
		content = "Untitled"
	}

	line := strings.TrimSpace(strings.Join([]string{icon, content}, " "))
	return renderStyledBar(theme.headingStyle(), line, width)
}

func renderCodeFence(renderer *glamour.TermRenderer, theme renderTheme, fence codeFenceSegment, width int) (string, error) {
	body, err := renderMarkdownChunk(renderer, fence.block)
	if err != nil {
		return "", err
	}

	if fence.language == "" {
		return body, nil
	}

	label := renderStyledBar(theme.labelStyle(), codeFenceLabel(fence.language), width)
	if body == "" {
		return label, nil
	}

	return label + "\n" + body, nil
}

func renderStyledBar(style lipgloss.Style, content string, width int) string {
	if width < 1 {
		width = 1
	}

	truncated := ansi.Truncate(content, width, "")
	padding := strings.Repeat(" ", max(0, width-ansi.StringWidth(truncated)))
	return style.Render(truncated + padding)
}

func codeFenceLabel(language string) string {
	language = strings.ToLower(strings.TrimSpace(language))
	icon, ok := codeFenceIcons[language]
	if !ok {
		icon = "󰆍"
	}

	return strings.TrimSpace(strings.Join([]string{icon, language}, " "))
}

func themeForStyle(style string) renderTheme {
	theme, ok := styleThemes[style]
	if ok {
		return theme
	}

	return styleThemes[DefaultStyle]
}

func (t renderTheme) headingStyle() lipgloss.Style {
	style := lipgloss.NewStyle().Bold(true)
	if t.plain {
		return style
	}

	if t.headingFG != "" {
		style = style.Foreground(lipgloss.Color(t.headingFG))
	}
	if t.headingBG != "" {
		style = style.Background(lipgloss.Color(t.headingBG))
	}

	return style
}

func (t renderTheme) labelStyle() lipgloss.Style {
	style := lipgloss.NewStyle().Bold(true)
	if t.plain {
		return style
	}

	if t.labelFG != "" {
		style = style.Foreground(lipgloss.Color(t.labelFG))
	}
	if t.labelBG != "" {
		style = style.Background(lipgloss.Color(t.labelBG))
	}

	return style
}
