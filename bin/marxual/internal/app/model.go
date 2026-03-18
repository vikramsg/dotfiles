package app

import (
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
)

type MarkdownRenderer interface {
	Render(input string, width int) (string, error)
}

type Model struct {
	originalMarkdown    string
	transformedMarkdown string
	rendered            string
	viewport            viewport.Model
	width               int
	height              int
	err                 error
	renderer            MarkdownRenderer
}

func NewModel(originalMarkdown string, transformedMarkdown string, renderer MarkdownRenderer) Model {
	vp := viewport.New(0, 0)
	vp.MouseWheelEnabled = true

	return Model{
		originalMarkdown:    originalMarkdown,
		transformedMarkdown: transformedMarkdown,
		viewport:            vp,
		renderer:            renderer,
	}
}

func (m Model) WithSize(width int, height int) Model {
	m.width = width
	m.height = height
	m.rerender()
	return m
}

func (m Model) Init() tea.Cmd {
	return nil
}

func (m *Model) rerender() {
	if m.width < 1 || m.height < 1 || m.renderer == nil {
		return
	}

	previousOffset := m.viewport.YOffset
	content, err := m.renderer.Render(m.transformedMarkdown, m.width)
	if err != nil {
		m.err = err
		return
	}

	m.err = nil
	m.rendered = content
	m.viewport.Width = m.width
	m.viewport.Height = m.height
	m.viewport.SetContent(content)
	m.viewport.SetYOffset(clampOffset(previousOffset, m.viewport))
}

func clampOffset(offset int, vp viewport.Model) int {
	maxOffset := vp.TotalLineCount() - vp.Height
	if maxOffset < 0 {
		maxOffset = 0
	}
	if offset < 0 {
		return 0
	}
	if offset > maxOffset {
		return maxOffset
	}
	return offset
}
