package zwm

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"zwm/internal/inventory"
	"zwm/internal/zed"
)

type Application struct {
	Configuration  Configuration
	State          StateRepository
	SessionReader  SessionReader
	WorktreeReader WorktreeReader
	ZedPath        string
	closer         interface{ Close() error }
}

// Inventory is the current live relationship between tmux and Zed. Discover
// builds it without changing persisted state so callers can safely preview it.
type Inventory struct {
	Sessions   []inventory.Session
	Records    []inventory.WorktreeRecord
	Mappings   []inventory.Mapping
	Unresolved []inventory.Session
}

type SessionReader interface {
	List(context.Context) ([]inventory.Session, error)
}

type WorktreeReader interface {
	Worktrees(context.Context) ([]inventory.WorktreeRecord, error)
}

type StateRepository interface {
	ActiveMappings(context.Context) ([]StateMapping, error)
	SaveSnapshot(context.Context, string, time.Time, []inventory.Session, []inventory.Mapping) error
	AppendEvent(context.Context, StateEvent) error
	LatestEvent(context.Context, ...string) (StateEvent, bool, error)
}

type Factory struct{}

func NewFactory() Factory {
	return Factory{}
}

func (Factory) Open() (*Application, error) {
	return OpenApplication()
}

func DefaultConfigPath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("resolve home directory: %w", err)
	}
	return filepath.Join(home, ".config", "zwm", "config.json"), nil
}

func DefaultStatePath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("resolve home directory: %w", err)
	}
	stateHome := os.Getenv("XDG_STATE_HOME")
	if stateHome == "" {
		stateHome = filepath.Join(home, ".local", "state")
	}
	return filepath.Join(stateHome, "zwm", "zwm.sqlite"), nil
}

func OpenApplication() (*Application, error) {
	configPath, err := DefaultConfigPath()
	if err != nil {
		return nil, err
	}
	configuration, err := LoadConfiguration(configPath)
	if err != nil {
		return nil, err
	}
	statePath, err := DefaultStatePath()
	if err != nil {
		return nil, err
	}
	store, err := OpenStateStore(statePath)
	if err != nil {
		return nil, err
	}
	zedPath, err := zed.DefaultDatabasePath()
	if err != nil {
		store.Close()
		return nil, err
	}
	return &Application{
		Configuration:  configuration,
		State:          store,
		SessionReader:  TmuxRunner{Host: configuration.Host},
		WorktreeReader: zed.Reader{Path: zedPath},
		ZedPath:        zedPath,
		closer:         store,
	}, nil
}

func (application *Application) Close() error {
	return application.closer.Close()
}

func (application *Application) Reconcile(context context.Context, now time.Time, persist bool) (Inventory, error) {
	sessions, err := application.SessionReader.List(context)
	if err != nil {
		return application.reconciliationFailure(context, now, persist, fmt.Errorf("list tmux sessions: %w", err))
	}
	records, err := application.WorktreeReader.Worktrees(context)
	if err != nil {
		return application.reconciliationFailure(context, now, persist, fmt.Errorf("read Zed terminal metadata: %w", err))
	}
	mappings, unresolved := inventory.Reconcile(application.Configuration.Host, sessions, records)
	current := Inventory{Sessions: sessions, Records: records, Mappings: mappings, Unresolved: unresolved}
	if persist {
		if err := application.PersistInventory(context, now, current); err != nil {
			return application.reconciliationFailure(context, now, true, err)
		}
	}
	return current, nil
}

func (application *Application) reconciliationFailure(context context.Context, now time.Time, persist bool, err error) (Inventory, error) {
	if persist {
		application.recordFailure(context, now, err)
		slog.Error("ZWM reconciliation failed", "host", application.Configuration.Host, "error", err)
	}
	return Inventory{}, err
}

func (application *Application) PersistInventory(context context.Context, now time.Time, inventory Inventory) error {
	active, err := application.State.ActiveMappings(context)
	if err != nil {
		return fmt.Errorf("read current inventory: %w", err)
	}
	unchanged := sameInventory(inventory.Sessions, active)
	if err := application.State.SaveSnapshot(context, application.Configuration.Host, now, inventory.Sessions, inventory.Mappings); err != nil {
		return fmt.Errorf("persist inventory: %w", err)
	}
	message := fmt.Sprintf("host=%s sessions=%d mappings=%d unresolved=%d", application.Configuration.Host, len(inventory.Sessions), len(inventory.Mappings), len(inventory.Unresolved))
	kind := "reconcile.completed"
	if unchanged {
		kind = "reconcile.noop"
	}
	if err := application.State.AppendEvent(context, StateEvent{At: now, Kind: kind, Message: message}); err != nil {
		return err
	}
	if len(inventory.Unresolved) > 0 {
		if err := application.State.AppendEvent(context, StateEvent{At: now, Kind: "reconcile.unresolved", Message: fmt.Sprintf("host=%s sessions=%d", application.Configuration.Host, len(inventory.Unresolved))}); err != nil {
			return err
		}
	}
	slog.Info("ZWM reconciliation completed", "host", application.Configuration.Host, "sessions", len(inventory.Sessions), "mappings", len(inventory.Mappings), "unresolved", len(inventory.Unresolved), "outcome", kind)
	return nil
}

func sameInventory(sessions []inventory.Session, mappings []StateMapping) bool {
	if len(sessions) != len(mappings) {
		return false
	}
	active := make(map[string]string, len(mappings))
	for _, mapping := range mappings {
		active[mapping.SessionName] = mapping.Worktree
	}
	for _, session := range sessions {
		if active[session.Name] != session.Worktree {
			return false
		}
	}
	return true
}

func (application *Application) recordFailure(context context.Context, now time.Time, cause error) {
	_ = application.State.AppendEvent(context, StateEvent{
		At:      now,
		Kind:    "reconcile.failed",
		Message: cause.Error(),
	})
}

func RunTerminalInitCommandSession(context context.Context) error {
	workingDirectory, err := os.Getwd()
	if err != nil {
		return fmt.Errorf("get working directory: %w", err)
	}
	root, err := gitWorktreeRoot(context, workingDirectory)
	if err != nil {
		return err
	}
	runner := TmuxRunner{Executable: TmuxExecutable()}
	sessions, err := runner.List(context)
	if err != nil {
		return err
	}
	plan, err := PlanTerminal(root, sessions)
	if err != nil {
		return err
	}
	_, err = fmt.Fprint(os.Stdout, terminalInitScript(plan.Session, TmuxExecutable()))
	return err
}

func terminalInitScript(session inventory.Session, tmuxExecutable string) string {
	return fmt.Sprintf(`session=%s
worktree=%s
tmux_command=%s

if ! "$tmux_command" has-session -t "$session" 2>/dev/null; then
  "$tmux_command" new-session -d -s "$session" -c "$worktree"
fi
"$tmux_command" set-option -t "$session" @zwm_worktree "$worktree"

title="$(basename "$(dirname "$worktree")")/$(basename "$worktree")"
printf '\033]2;%%s\007' "$title"
exec "$tmux_command" attach-session -t "$session"
`, shellQuoteValue(session.Name), shellQuoteValue(session.Worktree), shellQuoteValue(tmuxExecutable))
}

func shellQuoteValue(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}

func gitWorktreeRoot(context context.Context, workingDirectory string) (string, error) {
	process := exec.CommandContext(context, "git", "-C", workingDirectory, "rev-parse", "--show-toplevel")
	output, err := process.Output()
	if err != nil {
		return "", fmt.Errorf("resolve Git worktree root: %w", err)
	}
	return inventory.NormalizeWorktree(strings.TrimSpace(string(output)))
}
