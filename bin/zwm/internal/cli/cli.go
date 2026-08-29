package cli

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/spf13/cobra"
	"zwm"
	"zwm/internal/zed"
)

func Execute(arguments []string, factory zwm.Factory) error {
	root := &cobra.Command{
		Use:           "zwm",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.SetArgs(arguments)
	handle := &applicationHandle{factory: factory}
	root.AddCommand(terminalInitCommandSession())
	root.AddCommand(reconcileCommand(handle))
	root.AddCommand(daemonCommand(handle))
	root.AddCommand(listCommand())
	root.AddCommand(statusCommand(handle))
	root.AddCommand(logsCommand())
	root.AddCommand(restoreCommand(handle))
	root.AddCommand(doctorCommand(handle))
	return root.Execute()
}

type applicationHandle struct {
	factory     zwm.Factory
	application *zwm.Application
}

func (handle *applicationHandle) get() (*zwm.Application, error) {
	if handle.application != nil {
		return handle.application, nil
	}
	application, err := handle.factory.Open()
	if err != nil {
		return nil, err
	}
	handle.application = application
	return application, nil
}

func openState() (*zwm.StateStore, error) {
	path, err := zwm.DefaultStatePath()
	if err != nil {
		return nil, err
	}
	return zwm.OpenStateStore(path)
}

func terminalInitCommandSession() *cobra.Command {
	return &cobra.Command{
		Use:    "terminal-init-command-session",
		Short:  "Print the shell initializer for the current ZWM tmux session",
		Hidden: true,
		RunE: func(command *cobra.Command, _ []string) error {
			return zwm.RunTerminalInitCommandSession(command.Context())
		},
	}
}

func reconcileCommand(handle *applicationHandle) *cobra.Command {
	return &cobra.Command{
		Use:    "reconcile",
		Short:  "Reconcile Zed worktrees with live ZWM tmux sessions",
		Hidden: true,
		RunE: func(command *cobra.Command, _ []string) error {
			application, err := handle.get()
			if err != nil {
				return err
			}
			_, err = application.Reconcile(command.Context(), time.Now().UTC(), true)
			return err
		},
	}
}

func daemonCommand(handle *applicationHandle) *cobra.Command {
	return &cobra.Command{
		Use:    "daemon",
		Short:  "Run the persistent ZWM reconciliation daemon",
		Hidden: true,
		RunE: func(command *cobra.Command, _ []string) error {
			application, err := handle.get()
			if err != nil {
				return err
			}
			defer application.Close()
			context, stop := signal.NotifyContext(command.Context(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			_, _ = application.Reconcile(context, time.Now().UTC(), true)
			ticker := time.NewTicker(10 * time.Minute)
			defer ticker.Stop()
			for {
				select {
				case <-context.Done():
					return nil
				case now := <-ticker.C:
					_, _ = application.Reconcile(context, now.UTC(), true)
				}
			}
		},
	}
}

func listCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List the active reconciled ZWM sessions",
		RunE: func(command *cobra.Command, _ []string) error {
			store, err := openState()
			if err != nil {
				return err
			}
			defer store.Close()
			mappings, err := store.ActiveMappings(command.Context())
			if err != nil {
				return err
			}
			for _, mapping := range mappings {
				fmt.Print(mappingOutput(mapping))
			}
			return nil
		},
	}
}

func statusCommand(handle *applicationHandle) *cobra.Command {
	return &cobra.Command{
		Use:   "status",
		Short: "Show current and persisted ZWM status",
		RunE: func(command *cobra.Command, _ []string) error {
			application, err := handle.get()
			if err != nil {
				return err
			}
			defer application.Close()
			current, err := application.Reconcile(command.Context(), time.Now().UTC(), false)
			if err != nil {
				return err
			}
			mappings, err := application.State.ActiveMappings(command.Context())
			if err != nil {
				return err
			}
			latestSuccess, hasSuccess, err := application.State.LatestEvent(command.Context(), "reconcile.completed", "reconcile.noop")
			if err != nil {
				return err
			}
			latestFailure, hasFailure, err := application.State.LatestEvent(command.Context(), "reconcile.failed")
			if err != nil {
				return err
			}
			fmt.Print(terminalRenderer(os.Stdout).status(current, len(mappings), latestSuccess, hasSuccess, latestFailure, hasFailure, launchAgentState(), time.Now()))
			return nil
		},
	}
}

func logsCommand() *cobra.Command {
	var lines int
	var follow bool
	command := &cobra.Command{
		Use:   "logs",
		Short: "Show ZWM event records",
		RunE: func(command *cobra.Command, _ []string) error {
			store, err := openState()
			if err != nil {
				return err
			}
			defer store.Close()
			var lastID int64
			for {
				events, err := store.Events(command.Context(), lines)
				if err != nil {
					return err
				}
				for index := len(events) - 1; index >= 0; index-- {
					event := events[index]
					if event.ID > lastID {
						fmt.Printf("source=zwm local state %s %s %s\n", event.At.Format(time.RFC3339), event.Kind, event.Message)
						lastID = event.ID
					}
				}
				if !follow {
					return nil
				}
				select {
				case <-command.Context().Done():
					return nil
				case <-time.After(time.Second):
				}
			}
		},
	}
	command.Flags().IntVar(&lines, "lines", 50, "number of recent records")
	command.Flags().BoolVar(&follow, "follow", false, "follow new records")
	return command
}

func restoreCommand(handle *applicationHandle) *cobra.Command {
	var dryRun bool
	var latest bool
	var reuseWindow bool
	var newWindow bool
	var worktrees []string
	command := &cobra.Command{
		Use:   "restore",
		Short: "Restore reconciled worktrees in Zed",
		RunE: func(command *cobra.Command, _ []string) error {
			if newWindow && reuseWindow {
				return fmt.Errorf("--new-window and --reuse-window cannot be used together")
			}
			application, err := handle.get()
			if err != nil {
				return err
			}
			defer application.Close()

			source := "persisted"
			var live zwm.Inventory
			var mappings []zwm.StateMapping
			if latest {
				live, err = application.Reconcile(command.Context(), time.Now().UTC(), !dryRun)
				if err != nil {
					return err
				}
				source = "latest"
				mappings = stateMappings(live)
			} else {
				mappings, err = application.State.ActiveMappings(command.Context())
				if err != nil {
					return err
				}
			}

			plan, err := zwm.BuildRestorePlan(mappings, worktrees)
			if err != nil {
				return err
			}
			if reuseWindow {
				for index := range plan.Opens {
					plan.Opens[index].Mode = "-r"
				}
			}
			if newWindow {
				for index := range plan.Opens {
					plan.Opens[index].Mode = "-n"
				}
			}
			if dryRun {
				fmt.Print(terminalRenderer(os.Stdout).restorePlan(source, live, plan))
				return nil
			}
			if err := plan.ValidationError(); err != nil {
				return err
			}
			return executeRestore(command.Context(), plan.Opens, zed.Opener{}, application.State, time.Sleep)
		},
	}
	command.Flags().BoolVar(&dryRun, "dry-run", false, "print workspace opens without running Zed")
	command.Flags().BoolVar(&latest, "latest", false, "build the restore plan from current tmux and Zed state")
	command.Flags().BoolVar(&newWindow, "new-window", false, "restore into a new Zed window")
	command.Flags().BoolVar(&reuseWindow, "reuse-window", false, "restore into an existing Zed window")
	command.Flags().StringSliceVar(&worktrees, "worktree", nil, "restore only this worktree (repeatable)")
	return command
}

func stateMappings(inventory zwm.Inventory) []zwm.StateMapping {
	mappings := make([]zwm.StateMapping, 0, len(inventory.Mappings))
	for _, mapping := range inventory.Mappings {
		mappings = append(mappings, zwm.StateMapping{
			Host:        mapping.Host,
			SessionID:   mapping.Session.ID,
			SessionName: mapping.Session.Name,
			Worktree:    mapping.Worktree,
			TerminalID:  mapping.TerminalID,
		})
	}
	return mappings
}

type workspaceOpener interface {
	Open(context.Context, string, string, string) error
}

type eventAppender interface {
	AppendEvent(context.Context, zwm.StateEvent) error
}

func executeRestore(context context.Context, opens []zwm.RestoreAction, opener workspaceOpener, events eventAppender, pause func(time.Duration)) error {
	for index, open := range opens {
		if err := opener.Open(context, open.Mode, open.Mapping.Host, open.Mapping.Worktree); err != nil {
			_ = events.AppendEvent(context, zwm.StateEvent{At: time.Now().UTC(), Kind: "restore.failed", Message: open.Mapping.Worktree + ": " + err.Error()})
			return err
		}
		if err := events.AppendEvent(context, zwm.StateEvent{At: time.Now().UTC(), Kind: "restore.opened", Message: open.Mapping.Worktree}); err != nil {
			return err
		}
		if index < len(opens)-1 {
			pause(3 * time.Second)
		}
	}
	return nil
}

func doctorCommand(handle *applicationHandle) *cobra.Command {
	return &cobra.Command{
		Use:   "doctor",
		Short: "Check ZWM local and remote prerequisites",
		RunE: func(command *cobra.Command, _ []string) error {
			application, err := handle.get()
			if err != nil {
				return err
			}
			if _, err := os.Stat(application.ZedPath); err != nil {
				return fmt.Errorf("Zed database: %w", err)
			}
			if _, err := (zwm.TmuxRunner{Host: application.Configuration.Host}).List(command.Context()); err != nil {
				return fmt.Errorf("remote tmux: %w", err)
			}
			fmt.Printf("host: %s\nzed_database: %s\n", application.Configuration.Host, application.ZedPath)
			return nil
		},
	}
}

func formatTimestamp(value time.Time) string {
	if value.IsZero() {
		return "unobserved"
	}
	return value.Format(time.RFC3339)
}

func mappingOutput(mapping zwm.StateMapping) string {
	return fmt.Sprintf("source: zwm local state\nsession: %s\nhost: %s\nworktree: %s\nrecorded_at: %s\nlast_seen_on_vm_at: %s\nlast_matched_to_zed_at: %s\nzed_database_observed_at: %s\n\n",
		mapping.SessionName,
		mapping.Host,
		mapping.Worktree,
		formatTimestamp(mapping.RecordedAt),
		formatTimestamp(mapping.LastSeenOnVMAt),
		formatTimestamp(mapping.LastMatchedToZedAt),
		formatTimestamp(mapping.ZedDatabaseObservedAt),
	)
}

func launchAgentState() string {
	domain := fmt.Sprintf("gui/%d/com.vikramsg.dotfiles.lch-zwm", os.Getuid())
	output, err := exec.Command("launchctl", "print", domain).Output()
	if err != nil {
		return "not loaded"
	}
	return parseLaunchctlState(string(output))
}

func parseLaunchctlState(output string) string {
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "state = ") {
			return strings.TrimSpace(strings.TrimPrefix(line, "state = "))
		}
	}
	return "loaded"
}

func latestReconciliationAttempt(success zwm.StateEvent, hasSuccess bool, failure zwm.StateEvent, hasFailure bool) (zwm.StateEvent, bool, string) {
	if hasFailure && (!hasSuccess || failure.At.After(success.At)) {
		return failure, true, "failed"
	}
	if hasSuccess {
		return success, true, "succeeded"
	}
	return zwm.StateEvent{}, false, "unobserved"
}
