package app

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
	"github.com/vikramsg/dotfiles/bin/zwm/internal/config"
	"github.com/vikramsg/dotfiles/bin/zwm/internal/inventory"
	"github.com/vikramsg/dotfiles/bin/zwm/internal/state"
)

type fakeSessionReader struct {
	sessions []inventory.Session
	err      error
}

func (reader fakeSessionReader) List(context.Context) ([]inventory.Session, error) {
	return reader.sessions, reader.err
}

type fakeWorktreeReader struct {
	records []inventory.WorktreeRecord
	err     error
}

func (reader fakeWorktreeReader) Worktrees(context.Context) ([]inventory.WorktreeRecord, error) {
	return reader.records, reader.err
}

type fakeStateRepository struct {
	active      []state.Mapping
	activeError error
	saveError   error
	saved       bool
	saveCalls   int
	events      []state.Event
	appendError error
}

func (repository *fakeStateRepository) ActiveMappings(context.Context) ([]state.Mapping, error) {
	return repository.active, repository.activeError
}

func (repository *fakeStateRepository) SaveSnapshot(_ context.Context, _ string, _ time.Time, _ []inventory.Session, _ []inventory.Mapping) error {
	repository.saved = true
	repository.saveCalls++
	return repository.saveError
}

func (repository *fakeStateRepository) AppendEvent(_ context.Context, event state.Event) error {
	repository.events = append(repository.events, event)
	return repository.appendError
}

func (repository *fakeStateRepository) LatestEvent(context.Context, ...string) (state.Event, bool, error) {
	return state.Event{}, false, nil
}

func TestReconcilePreservesPriorInventoryWhenTmuxReadFails(t *testing.T) {
	repository := &fakeStateRepository{active: []state.Mapping{{SessionName: "zwm-v1-aaaaaaaa-parent-leaf"}}}
	application := Application{
		Configuration: config.Config{Host: "vm-us"},
		State:         repository,
		SessionReader: fakeSessionReader{err: errors.New("tmux unavailable")},
	}

	_, err := application.Reconcile(context.Background(), time.Date(2026, time.August, 29, 0, 0, 0, 0, time.UTC), true)
	if err == nil {
		t.Fatal("Reconcile succeeded when tmux read failed")
	}
	if repository.saved {
		t.Fatal("SaveSnapshot ran after tmux read failure")
	}
	if difference := cmp.Diff([]state.Mapping{{SessionName: "zwm-v1-aaaaaaaa-parent-leaf"}}, repository.active); difference != "" {
		t.Fatalf("active inventory changed (-want +got):\n%s", difference)
	}
	if len(repository.events) != 1 || repository.events[0].Kind != "reconcile.failed" {
		t.Fatalf("events = %#v, want reconcile.failed", repository.events)
	}
}

func TestReconcileRecordsNoopForUnchangedInventory(t *testing.T) {
	worktree := "/home/vikram/projects/meanderx/kunda-wt"
	session, err := inventory.SessionForWorktree(worktree, 8)
	if err != nil {
		t.Fatalf("derive session: %v", err)
	}
	repository := &fakeStateRepository{active: []state.Mapping{{SessionName: session.Name, Worktree: worktree}}}
	application := Application{
		Configuration:  config.Config{Host: "vm-us"},
		State:          repository,
		SessionReader:  fakeSessionReader{sessions: []inventory.Session{session}},
		WorktreeReader: fakeWorktreeReader{records: []inventory.WorktreeRecord{{Host: "vm-us", TerminalID: "terminal-1", Worktree: worktree}}},
	}

	if _, err := application.Reconcile(context.Background(), time.Date(2026, time.August, 29, 0, 0, 0, 0, time.UTC), true); err != nil {
		t.Fatalf("Reconcile: %v", err)
	}
	if !repository.saved || repository.saveCalls != 1 {
		t.Fatalf("SaveSnapshot calls = %d, want 1", repository.saveCalls)
	}
	if len(repository.events) != 1 || repository.events[0].Kind != "reconcile.noop" {
		t.Fatalf("events = %#v, want reconcile.noop", repository.events)
	}
}

func TestReconcilePreviewDoesNotPersistOrRecordEvents(t *testing.T) {
	worktree := "/home/vikram/projects/meanderx/kunda-wt"
	session, err := inventory.SessionForWorktree(worktree, 8)
	if err != nil {
		t.Fatalf("derive session: %v", err)
	}
	repository := &fakeStateRepository{}
	application := Application{
		Configuration:  config.Config{Host: "vm-us"},
		State:          repository,
		SessionReader:  fakeSessionReader{sessions: []inventory.Session{session}},
		WorktreeReader: fakeWorktreeReader{records: []inventory.WorktreeRecord{{Host: "vm-us", TerminalID: "terminal-1", Worktree: worktree}}},
	}

	current, err := application.Reconcile(context.Background(), time.Now().UTC(), false)
	if err != nil {
		t.Fatalf("preview reconciliation: %v", err)
	}
	if len(current.Mappings) != 1 {
		t.Fatalf("mappings = %#v", current.Mappings)
	}
	if repository.saved || len(repository.events) != 0 {
		t.Fatalf("preview mutated state: saved=%v events=%#v", repository.saved, repository.events)
	}
}

func TestReconcileRecordsUnresolvedLiveSession(t *testing.T) {
	session, err := inventory.SessionForWorktree("/home/vikram/projects/meanderx/kunda-wt", 8)
	if err != nil {
		t.Fatalf("derive session: %v", err)
	}
	repository := &fakeStateRepository{}
	application := Application{
		Configuration:  config.Config{Host: "vm-us"},
		State:          repository,
		SessionReader:  fakeSessionReader{sessions: []inventory.Session{session}},
		WorktreeReader: fakeWorktreeReader{},
	}

	if _, err := application.Reconcile(context.Background(), time.Date(2026, time.August, 29, 0, 0, 0, 0, time.UTC), true); err != nil {
		t.Fatalf("Reconcile: %v", err)
	}
	if len(repository.events) != 2 {
		t.Fatalf("event count = %d, want 2", len(repository.events))
	}
	if repository.events[0].Kind != "reconcile.completed" || repository.events[1].Kind != "reconcile.unresolved" {
		t.Fatalf("events = %#v, want completed then unresolved", repository.events)
	}
}

func TestReconcileRecordsFailureWhenReadingPriorInventoryFails(t *testing.T) {
	repository := &fakeStateRepository{activeError: errors.New("state unavailable")}
	application := Application{
		Configuration:  config.Config{Host: "vm-us"},
		State:          repository,
		SessionReader:  fakeSessionReader{},
		WorktreeReader: fakeWorktreeReader{},
	}

	if _, err := application.Reconcile(context.Background(), time.Now().UTC(), true); err == nil {
		t.Fatal("Reconcile succeeded when current inventory failed")
	}
	if len(repository.events) != 1 || repository.events[0].Kind != "reconcile.failed" {
		t.Fatalf("events = %#v, want reconcile.failed", repository.events)
	}
}

func TestReconcileRecordsFailureWhenPersistingSnapshotFails(t *testing.T) {
	repository := &fakeStateRepository{saveError: errors.New("state write failed")}
	application := Application{
		Configuration:  config.Config{Host: "vm-us"},
		State:          repository,
		SessionReader:  fakeSessionReader{},
		WorktreeReader: fakeWorktreeReader{},
	}

	if _, err := application.Reconcile(context.Background(), time.Now().UTC(), true); err == nil {
		t.Fatal("Reconcile succeeded when snapshot persistence failed")
	}
	if len(repository.events) != 1 || repository.events[0].Kind != "reconcile.failed" {
		t.Fatalf("events = %#v, want reconcile.failed", repository.events)
	}
}

func TestTerminalInitScriptKeepsTmuxExecutionInTheShell(t *testing.T) {
	script := terminalInitScript(inventory.Session{
		Name:     "zwm-v1-deadbeef-meanderx-kunda-wt",
		Worktree: "/home/vikram/projects/meanderx/kunda-wt",
	}, "/home/linuxbrew/.linuxbrew/bin/tmux")

	for _, required := range []string{
		"session='zwm-v1-deadbeef-meanderx-kunda-wt'",
		"worktree='/home/vikram/projects/meanderx/kunda-wt'",
		"tmux_command='/home/linuxbrew/.linuxbrew/bin/tmux'",
		"\"$tmux_command\" new-session -d -s \"$session\" -c \"$worktree\"",
		"\"$tmux_command\" set-option -t \"$session\" @zwm_worktree \"$worktree\"",
		"exec \"$tmux_command\" attach-session -t \"$session\"",
	} {
		if !strings.Contains(script, required) {
			t.Fatalf("initializer missing %q:\n%s", required, script)
		}
	}
	if strings.Index(script, "set-option") < strings.Index(script, "fi\n") {
		t.Fatalf("initializer sets metadata only during session creation:\n%s", script)
	}
}
