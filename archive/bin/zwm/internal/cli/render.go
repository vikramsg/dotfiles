package cli

import (
	"fmt"
	"io"
	"os"
	"path"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/muesli/termenv"
	"golang.org/x/term"
	"zwm"
)

type renderer struct {
	width   int
	heading lipgloss.Style
	section lipgloss.Style
	label   lipgloss.Style
	ready   lipgloss.Style
	warning lipgloss.Style
	dim     lipgloss.Style
}

func terminalRenderer(output *os.File) renderer {
	_, noColor := os.LookupEnv("NO_COLOR")
	styled := stylesEnabled(term.IsTerminal(int(output.Fd())), noColor, os.Getenv("TERM"))
	width, _, _ := term.GetSize(int(output.Fd()))
	return newRendererAtWidth(output, styled, width)
}

func stylesEnabled(isTerminal bool, noColor bool, terminal string) bool {
	return isTerminal && !noColor && terminal != "dumb"
}

func newRenderer(output io.Writer, styled bool) renderer {
	return newRendererAtWidth(output, styled, 0)
}

func newRendererAtWidth(output io.Writer, styled bool, width int) renderer {
	lipglossRenderer := lipgloss.NewRenderer(output)
	if styled {
		lipglossRenderer.SetColorProfile(termenv.ANSI256)
	} else {
		lipglossRenderer.SetColorProfile(termenv.Ascii)
	}
	return renderer{
		width:   width,
		heading: lipglossRenderer.NewStyle().Bold(true).Foreground(lipgloss.Color("69")),
		section: lipglossRenderer.NewStyle().Bold(true).Foreground(lipgloss.Color("117")),
		label:   lipglossRenderer.NewStyle().Foreground(lipgloss.Color("244")).Width(15),
		ready:   lipglossRenderer.NewStyle().Bold(true).Foreground(lipgloss.Color("42")),
		warning: lipglossRenderer.NewStyle().Bold(true).Foreground(lipgloss.Color("214")),
		dim:     lipglossRenderer.NewStyle().Foreground(lipgloss.Color("244")),
	}
}

func (renderer renderer) restorePlan(source string, inventory zwm.Inventory, plan zwm.RestorePlan) string {
	var output strings.Builder
	fmt.Fprintf(&output, "%s  %s\n\n", renderer.heading.Render("RESTORE PLAN"), renderer.dim.Render(strings.ToUpper(source)))
	if source == "latest" {
		fmt.Fprintf(&output, "%s %d sessions\n", renderer.label.Render("Remote tmux"), len(inventory.Sessions))
		fmt.Fprintf(&output, "%s %d records\n", renderer.label.Render("Zed terminals"), len(inventory.Records))
		fmt.Fprintf(&output, "%s %s\n", renderer.label.Render("Mappings"), renderer.ready.Render(fmt.Sprintf("%d ready", len(inventory.Mappings))))
		if len(inventory.Unresolved) > 0 {
			fmt.Fprintf(&output, "%s %s\n", renderer.label.Render("Unresolved"), renderer.warning.Render(fmt.Sprintf("%d sessions", len(inventory.Unresolved))))
		}
	}
	fmt.Fprintf(&output, "%s %d\n", renderer.label.Render("Planned opens"), len(plan.Opens))

	for index, open := range plan.Opens {
		fmt.Fprintf(&output, "%s %s\n", renderer.ready.Render(fmt.Sprintf("%d READY", index+1)), path.Base(open.Mapping.Worktree))
		output.WriteString(renderer.restoreField("Worktree", open.Mapping.Worktree))
		output.WriteString(renderer.restoreField("Session", open.Mapping.SessionName))
		output.WriteString(renderer.restoreField("Terminal", open.Mapping.TerminalID))
		output.WriteString(renderer.restoreField("Command", renderer.dim.Render(fmt.Sprintf("zed %s ssh://%s:%s", open.Mode, open.Mapping.Host, open.Mapping.Worktree))))
		output.WriteString("\n")
	}
	if len(plan.Missing) > 0 {
		fmt.Fprintf(&output, "%s\n", renderer.warning.Render("MISSING REQUESTED WORKTREES"))
		for _, worktree := range plan.Missing {
			fmt.Fprintf(&output, "  %s\n", worktree)
		}
		output.WriteString("\n")
	}
	if len(plan.Opens) == 0 {
		fmt.Fprintf(&output, "%s No restorable worktrees found.\n", renderer.warning.Render("EMPTY"))
	} else {
		fmt.Fprintf(&output, "%s No Zed workspaces opened; no state persisted.\n", renderer.ready.Render("DRY RUN"))
	}
	return output.String()
}

func (renderer renderer) restoreField(label string, value string) string {
	if renderer.width > 0 && renderer.width < 80 {
		return fmt.Sprintf("  %s\n  %s\n", renderer.label.UnsetWidth().Render(label), value)
	}
	return fmt.Sprintf("  %s %s\n", renderer.label.Render(label), value)
}

func (renderer renderer) status(current zwm.Inventory, persistedCount int, latestSuccess zwm.StateEvent, hasSuccess bool, latestFailure zwm.StateEvent, hasFailure bool, daemonState string, now time.Time) string {
	var output strings.Builder
	output.WriteString(renderer.heading.Render("ZWM STATUS") + "\n\n")
	output.WriteString(renderer.section.Render("LIVE INVENTORY") + "\n")
	daemon := renderer.ready.Render(strings.ToUpper(daemonState))
	if daemonState != "running" {
		daemon = renderer.warning.Render(strings.ToUpper(daemonState))
	}
	fmt.Fprintf(&output, "%s %s\n", renderer.label.Render("Daemon"), daemon)
	fmt.Fprintf(&output, "%s %d sessions\n", renderer.label.Render("Remote tmux"), len(current.Sessions))
	fmt.Fprintf(&output, "%s %d records\n", renderer.label.Render("Zed terminals"), len(current.Records))
	fmt.Fprintf(&output, "%s %s\n", renderer.label.Render("Mappings"), renderer.ready.Render(fmt.Sprintf("%d ready", len(current.Mappings))))
	if len(current.Unresolved) > 0 {
		fmt.Fprintf(&output, "%s %s\n", renderer.label.Render("Unresolved"), renderer.warning.Render(fmt.Sprintf("%d sessions", len(current.Unresolved))))
	}
	output.WriteString("\n")
	for _, mapping := range current.Mappings {
		fmt.Fprintf(&output, "%s %s\n", renderer.ready.Render("READY"), path.Base(mapping.Worktree))
		fmt.Fprintf(&output, "  %s\n", mapping.Worktree)
		fmt.Fprintf(&output, "  %s\n", renderer.dim.Render(mapping.Session.Name))
	}

	output.WriteString("\n" + renderer.section.Render("PERSISTED STATE") + "\n")
	fmt.Fprintf(&output, "%s %d mappings\n", renderer.label.Render("Mappings"), persistedCount)
	latestAttempt, hasAttempt, outcome := latestReconciliationAttempt(latestSuccess, hasSuccess, latestFailure, hasFailure)
	if hasAttempt {
		outcomeStyle := renderer.ready
		if outcome == "failed" {
			outcomeStyle = renderer.warning
		}
		fmt.Fprintf(&output, "%s %s\n", renderer.label.Render("Last attempt"), latestAttempt.At.Local().Format(time.RFC3339))
		fmt.Fprintf(&output, "%s %s, %s\n", renderer.label.Render("Result"), outcomeStyle.Render(strings.ToUpper(outcome)), formatAge(now.Sub(latestAttempt.At)))
	} else {
		fmt.Fprintf(&output, "%s %s\n", renderer.label.Render("Last attempt"), renderer.warning.Render("UNOBSERVED"))
	}
	if hasSuccess {
		fmt.Fprintf(&output, "%s %s\n", renderer.label.Render("Last success"), latestSuccess.At.Local().Format(time.RFC3339))
	} else {
		fmt.Fprintf(&output, "%s %s\n", renderer.label.Render("Last success"), renderer.warning.Render("UNOBSERVED"))
	}
	return output.String()
}

func formatAge(age time.Duration) string {
	if age < 0 {
		age = 0
	}
	return age.Round(time.Second).String() + " ago"
}
