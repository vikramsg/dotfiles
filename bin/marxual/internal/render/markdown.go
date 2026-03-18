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

type codeFenceTheme struct {
	icon  string
	color string
}

type renderTheme struct {
	headingFG string
	headingBG string
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

var codeFenceThemes = map[string]codeFenceTheme{
	"bash":       {icon: "", color: "#22c55e"},
	"console":    {icon: "", color: "#22c55e"},
	"fish":       {icon: "", color: "#22c55e"},
	"go":         {icon: "", color: "#67e8f9"},
	"golang":     {icon: "", color: "#67e8f9"},
	"javascript": {icon: "", color: "#fde047"},
	"js":         {icon: "", color: "#fde047"},
	"json":       {icon: "", color: "#eab308"},
	"lua":        {icon: "", color: "#60a5fa"},
	"markdown":   {icon: "󰍔", color: "#e5e7eb"},
	"md":         {icon: "󰍔", color: "#e5e7eb"},
	"python":     {icon: "", color: "#f59e0b"},
	"py":         {icon: "", color: "#f59e0b"},
	"shell":      {icon: "", color: "#22c55e"},
	"sh":         {icon: "", color: "#22c55e"},
	"text":       {icon: "󰈙", color: "#9ca3af"},
	"toml":       {icon: "", color: "#c084fc"},
	"ts":         {icon: "", color: "#60a5fa"},
	"typescript": {icon: "", color: "#60a5fa"},
	"yaml":       {icon: "", color: "#f97316"},
	"yml":        {icon: "", color: "#f97316"},
	"zsh":        {icon: "", color: "#22c55e"},
}

var styleThemes = map[string]renderTheme{
	styles.AsciiStyle:      {plain: true},
	styles.AutoStyle:       {headingFG: "#1f2937", headingBG: "#cbd5e1"},
	styles.DarkStyle:       {headingFG: "#f8fafc", headingBG: "#334155"},
	styles.DraculaStyle:    {headingFG: "#f8f8f2", headingBG: "#44475a"},
	styles.TokyoNightStyle: {headingFG: "#c0caf5", headingBG: "#3b4261"},
	styles.LightStyle:      {headingFG: "#1f2937", headingBG: "#dbe4f0"},
	styles.NoTTYStyle:      {plain: true},
	styles.PinkStyle:       {headingFG: "#fff1f2", headingBG: "#be185d"},
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
	body = trimRenderedBlankLines(body)
	indent := renderedContentIndent(body)

	language := fence.language
	if language == "" {
		language = "text"
	}

	label := renderCodeFenceLabel(theme, language, indent)
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
	theme, ok := codeFenceThemes[language]
	if !ok {
		theme = codeFenceTheme{icon: "󰆍", color: "#9ca3af"}
	}

	return strings.TrimSpace(strings.Join([]string{theme.icon, language}, " "))
}

func renderCodeFenceLabel(theme renderTheme, language string, indent string) string {
	label := codeFenceLabel(language)
	if theme.plain {
		return indent + label
	}

	style := lipgloss.NewStyle().Faint(true)
	if fenceTheme, ok := codeFenceThemes[strings.ToLower(strings.TrimSpace(language))]; ok && fenceTheme.color != "" {
		style = style.Foreground(lipgloss.Color(fenceTheme.color))
	}

	return indent + style.Render(label)
}

func trimRenderedBlankLines(content string) string {
	if content == "" {
		return ""
	}

	lines := strings.Split(content, "\n")
	start := 0
	for start < len(lines) && isVisuallyBlank(lines[start]) {
		start++
	}

	end := len(lines)
	for end > start && isVisuallyBlank(lines[end-1]) {
		end--
	}

	return strings.Join(lines[start:end], "\n")
}

func isVisuallyBlank(line string) bool {
	return strings.TrimSpace(ansi.Strip(line)) == ""
}

func renderedContentIndent(content string) string {
	for _, line := range strings.Split(content, "\n") {
		if isVisuallyBlank(line) {
			continue
		}

		visible := ansi.Strip(line)
		width := 0
		for _, r := range visible {
			if r != ' ' && r != '\t' {
				break
			}
			if r == '\t' {
				width += 4
				continue
			}
			width++
		}

		return strings.Repeat(" ", width)
	}

	return ""
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
