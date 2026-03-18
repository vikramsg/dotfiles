package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"golang.org/x/term"

	"marxual/internal/app"
	"marxual/internal/render"
)

func main() {
	if err := run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}

func run(args []string, stdin io.Reader, stdout io.Writer, stderr io.Writer) error {
	fs := flag.NewFlagSet("marxual", flag.ContinueOnError)
	fs.SetOutput(stderr)
	styleFlag := fs.String("style", render.DefaultStyle, "Built-in Glamour style")
	fs.Usage = func() {
		fmt.Fprintln(stderr, "Usage: marxual [--style STYLE] PATH")
		fmt.Fprintln(stderr, "       marxual [--style STYLE] -")
		fmt.Fprintln(stderr)
		fmt.Fprintln(stderr, "Render Markdown from a file path or stdin in a terminal viewer.")
		fmt.Fprintln(stderr)
		fmt.Fprintf(stderr, "Options:\n  --style STYLE   Built-in Glamour style (default: %s)\n", render.DefaultStyle)
		fmt.Fprintf(stderr, "                  Available: %s\n", render.AvailableStylesHelp())
	}

	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return err
	}

	if fs.NArg() != 1 {
		fs.Usage()
		return fmt.Errorf("expected exactly one path argument")
	}

	style, err := render.ResolveStyle(*styleFlag)
	if err != nil {
		return err
	}

	originalMarkdown, err := loadInput(fs.Arg(0), stdin)
	if err != nil {
		return err
	}

	mermaidRenderer := render.NewMermaidASCIIRenderer()
	transformedMarkdown := render.PreprocessMarkdown(originalMarkdown, mermaidRenderer)
	model := app.NewModel(originalMarkdown, transformedMarkdown, render.TermRenderer{Style: style})
	if initialWidth, initialHeight, ok := initialWindowSize(stdout); ok {
		model = model.WithSize(initialWidth, initialHeight)
	}

	program := tea.NewProgram(
		model,
		tea.WithOutput(stdout),
		tea.WithInputTTY(),
	)

	if _, err := program.Run(); err != nil {
		return fmt.Errorf("failed to run terminal viewer: %w", err)
	}

	return nil
}

func loadInput(path string, stdin io.Reader) (string, error) {
	if path == "-" {
		data, err := io.ReadAll(stdin)
		if err != nil {
			return "", fmt.Errorf("failed to read stdin: %w", err)
		}

		content := string(data)
		if strings.TrimSpace(content) == "" {
			return "", errors.New("stdin is empty")
		}

		return content, nil
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("failed to read %q: %w", path, err)
	}

	return string(data), nil
}

func initialWindowSize(output io.Writer) (int, int, bool) {
	file, ok := output.(*os.File)
	if !ok {
		return 0, 0, false
	}

	fd := int(file.Fd())
	if !term.IsTerminal(fd) {
		return 0, 0, false
	}

	width, height, err := term.GetSize(fd)
	if err != nil {
		return 0, 0, false
	}

	return width, height, true
}
