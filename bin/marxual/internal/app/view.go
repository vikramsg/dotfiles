package app

import "fmt"

func (m Model) View() string {
	if m.err != nil {
		return fmt.Sprintf("Error: %v", m.err)
	}

	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

	return m.viewport.View()
}
