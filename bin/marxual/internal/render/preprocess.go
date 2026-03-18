package render

import "strings"

func PreprocessMarkdown(input string, renderer MermaidRenderer) string {
	if input == "" {
		return ""
	}

	lines := strings.SplitAfter(input, "\n")
	var output strings.Builder

	for index := 0; index < len(lines); {
		marker, info, ok := parseFenceStart(lines[index])
		if !ok {
			output.WriteString(lines[index])
			index++
			continue
		}

		end := findFenceEnd(lines, index+1, marker)
		if end == -1 {
			output.WriteString(lines[index])
			index++
			continue
		}

		block := strings.Join(lines[index:end+1], "")
		if fenceLanguage(info) != "mermaid" {
			output.WriteString(block)
			index = end + 1
			continue
		}

		body := strings.Join(lines[index+1:end], "")
		ascii, err := renderer.Render(body)
		if err != nil {
			output.WriteString("> Warning: failed to render Mermaid diagram: ")
			output.WriteString(err.Error())
			output.WriteString("\n\n")
			output.WriteString(block)
			index = end + 1
			continue
		}

		output.WriteString("```text\n")
		output.WriteString(strings.TrimRight(ascii, "\n"))
		output.WriteString("\n```")
		if strings.HasSuffix(lines[end], "\n") {
			output.WriteString("\n")
		}

		index = end + 1
	}

	return output.String()
}

func parseFenceStart(line string) (string, string, bool) {
	trimmed := strings.TrimSpace(line)
	if len(trimmed) < 3 {
		return "", "", false
	}

	markerChar := trimmed[0]
	if markerChar != '`' && markerChar != '~' {
		return "", "", false
	}

	markerLength := 0
	for markerLength < len(trimmed) && trimmed[markerLength] == markerChar {
		markerLength++
	}

	if markerLength < 3 {
		return "", "", false
	}

	marker := trimmed[:markerLength]
	info := strings.TrimSpace(trimmed[markerLength:])
	return marker, info, true
}

func findFenceEnd(lines []string, start int, marker string) int {
	for index := start; index < len(lines); index++ {
		trimmed := strings.TrimSpace(lines[index])
		if strings.HasPrefix(trimmed, marker) && strings.TrimSpace(trimmed[len(marker):]) == "" {
			return index
		}
	}

	return -1
}

func fenceLanguage(info string) string {
	fields := strings.Fields(strings.ToLower(info))
	if len(fields) == 0 {
		return ""
	}

	return fields[0]
}
