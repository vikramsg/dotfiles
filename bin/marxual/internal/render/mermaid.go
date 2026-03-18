package render

import (
	mermaidcmd "github.com/AlexanderGrooff/mermaid-ascii/cmd"
	"github.com/AlexanderGrooff/mermaid-ascii/pkg/diagram"
)

type MermaidRenderer interface {
	Render(input string) (string, error)
}

type MermaidASCIIRenderer struct {
	config *diagram.Config
}

func NewMermaidASCIIRenderer() MermaidASCIIRenderer {
	config := diagram.DefaultConfig()
	config.UseAscii = true
	config.StyleType = "cli"

	return MermaidASCIIRenderer{config: config}
}

func (r MermaidASCIIRenderer) Render(input string) (string, error) {
	return mermaidcmd.RenderDiagram(input, r.config)
}
