package cli

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/google/go-cmp/cmp"
	"github.com/vikramsg/dotfiles/bin/zwm/internal/app"
	"github.com/vikramsg/dotfiles/bin/zwm/internal/inventory"
	"github.com/vikramsg/dotfiles/bin/zwm/internal/restore"
	"github.com/vikramsg/dotfiles/bin/zwm/internal/state"
)

func TestFormatTimestampMarksUnobservedValues(t *testing.T) {
	if value := formatTimestamp(time.Time{}); value != "unobserved" {
		t.Fatalf("formatTimestamp(zero) = %q, want unobserved", value)
	}
}

func TestFormatTimestampUsesRFC3339(t *testing.T) {
	value := time.Date(2026, time.August, 29, 12, 0, 0, 0, time.UTC)
	if formatted := formatTimestamp(value); formatted != "2026-08-29T12:00:00Z" {
		t.Fatalf("formatTimestamp = %q", formatted)
	}
}

func TestMappingOutputIncludesRequiredProvenance(t *testing.T) {
	at := time.Date(2026, time.August, 29, 12, 0, 0, 0, time.UTC)
	output := mappingOutput(state.Mapping{
		SessionName:           "zwm-v1-deadbeef-meanderx-kunda-wt",
		Host:                  "vm-us",
		Worktree:              "/home/vikram/projects/meanderx/kunda-wt",
		RecordedAt:            at,
		LastSeenOnVMAt:        at,
		LastMatchedToZedAt:    at,
		ZedDatabaseObservedAt: at,
	})

	for _, required := range []string{
		"source: zwm local state",
		"recorded_at: 2026-08-29T12:00:00Z",
		"last_seen_on_vm_at: 2026-08-29T12:00:00Z",
		"last_matched_to_zed_at: 2026-08-29T12:00:00Z",
		"zed_database_observed_at: 2026-08-29T12:00:00Z",
	} {
		if !strings.Contains(output, required) {
			t.Fatalf("mapping output missing %q: %s", required, output)
		}
	}
}

func TestStatusOutputShowsLiveInventoryAndLatestAttempt(t *testing.T) {
	success := state.Event{At: time.Date(2026, time.August, 29, 12, 0, 0, 0, time.UTC)}
	failure := state.Event{At: time.Date(2026, time.August, 29, 12, 10, 0, 0, time.UTC)}
	output := newRenderer(&bytes.Buffer{}, false).status(app.Inventory{
		Sessions: []inventory.Session{{Name: "zwm-v1-deadbeef-meanderx-kunda"}},
		Records:  []inventory.WorktreeRecord{{TerminalID: "terminal-1"}},
		Mappings: []inventory.Mapping{{Worktree: "/work/kunda", Session: inventory.Session{Name: "zwm-v1-deadbeef-meanderx-kunda"}}},
	}, 2, success, true, failure, true, "running", time.Date(2026, time.August, 29, 12, 12, 0, 0, time.UTC))

	for _, required := range []string{
		"Daemon          RUNNING",
		"Remote tmux     1 sessions",
		"Mappings        1 ready",
		"Mappings        2 mappings",
		"FAILED, 2m0s ago",
	} {
		if !strings.Contains(output, required) {
			t.Fatalf("status output missing %q: %s", required, output)
		}
	}
}

func TestRendererStylesTTYOutputOnly(t *testing.T) {
	if !stylesEnabled(true, false, "xterm-256color") {
		t.Fatal("styles disabled for color terminal")
	}
	if stylesEnabled(false, false, "xterm-256color") || stylesEnabled(true, true, "xterm-256color") || stylesEnabled(true, false, "dumb") {
		t.Fatal("styles enabled for plain-output condition")
	}
}

func TestParseLaunchctlState(t *testing.T) {
	if state := parseLaunchctlState("path = /tmp/job\n\tstate = running\n"); state != "running" {
		t.Fatalf("state = %q, want running", state)
	}
}

type fakeWorkspaceOpener struct {
	err error
}

func (opener fakeWorkspaceOpener) Open(context.Context, string, state.Mapping) error {
	return opener.err
}

type fakeEventAppender struct {
	events []state.Event
}

func (appender *fakeEventAppender) AppendEvent(_ context.Context, event state.Event) error {
	appender.events = append(appender.events, event)
	return nil
}

func TestExecuteRestoreRecordsOpenedOutcomes(t *testing.T) {
	appender := &fakeEventAppender{}
	paused := 0
	err := executeRestore(context.Background(), []restore.Open{
		{Mode: "-n", Mapping: state.Mapping{Worktree: "/work/one"}},
		{Mode: "-r", Mapping: state.Mapping{Worktree: "/work/two"}},
	}, fakeWorkspaceOpener{}, appender, func(time.Duration) { paused++ })
	if err != nil {
		t.Fatalf("execute restore: %v", err)
	}
	if paused != 1 {
		t.Fatalf("pause count = %d, want 1", paused)
	}
	if len(appender.events) != 2 || appender.events[0].Kind != "restore.opened" || appender.events[1].Kind != "restore.opened" {
		t.Fatalf("events = %#v, want two restore.opened events", appender.events)
	}
}

func TestExecuteRestoreRecordsFailedOutcome(t *testing.T) {
	appender := &fakeEventAppender{}
	cause := errors.New("Zed unavailable")
	err := executeRestore(context.Background(), []restore.Open{{Mapping: state.Mapping{Worktree: "/work/one"}}}, fakeWorkspaceOpener{err: cause}, appender, func(time.Duration) {})
	if !errors.Is(err, cause) {
		t.Fatalf("execute restore error = %v, want %v", err, cause)
	}
	if len(appender.events) != 1 || appender.events[0].Kind != "restore.failed" {
		t.Fatalf("events = %#v, want restore.failed", appender.events)
	}
}

func TestRestorePlanOutputDescribesLatestPlanWithoutHidingMissingTargets(t *testing.T) {
	output := newRenderer(&bytes.Buffer{}, false).restorePlan("latest", app.Inventory{
		Sessions:   []inventory.Session{{Name: "zwm-v1-deadbeef-meanderx-kunda", Worktree: "/work/kunda"}},
		Records:    []inventory.WorktreeRecord{{Host: "vm-us", TerminalID: "terminal-1", Worktree: "/work/kunda"}},
		Mappings:   []inventory.Mapping{{Host: "vm-us", Session: inventory.Session{Name: "zwm-v1-deadbeef-meanderx-kunda"}, TerminalID: "terminal-1", Worktree: "/work/kunda"}},
		Unresolved: []inventory.Session{{Name: "zwm-v1-feedface-meanderx-missing"}},
	}, restore.Plan{
		Opens:   []restore.Open{{Mode: "-n", Mapping: state.Mapping{Host: "vm-us", SessionName: "zwm-v1-deadbeef-meanderx-kunda", TerminalID: "terminal-1", Worktree: "/work/kunda"}}},
		Missing: []string{"/work/missing"},
	})

	for _, required := range []string{
		"RESTORE PLAN  LATEST",
		"Remote tmux     1 sessions",
		"Zed terminals   1 records",
		"Mappings        1 ready",
		"Unresolved      1 sessions",
		"Planned opens   1",
		"zed -n ssh://vm-us:/work/kunda",
		"MISSING REQUESTED WORKTREES",
		"/work/missing",
		"DRY RUN No Zed workspaces opened; no state persisted.",
	} {
		if !strings.Contains(output, required) {
			t.Fatalf("restore plan output missing %q:\n%s", required, output)
		}
	}
}

func TestRestorePlanOutputExplainsAnEmptyPlan(t *testing.T) {
	output := newRenderer(&bytes.Buffer{}, false).restorePlan("latest", app.Inventory{}, restore.Plan{})
	if !strings.Contains(output, "EMPTY No restorable worktrees found.") {
		t.Fatalf("restore plan output = %q", output)
	}
	if strings.Count(output, "No restorable worktrees found") != 1 {
		t.Fatalf("empty-plan result repeated: %q", output)
	}
}

func TestStyledAndPlainRestorePlansHaveTheSameContent(t *testing.T) {
	plan := restore.Plan{Opens: []restore.Open{{Mode: "-n", Mapping: state.Mapping{Host: "vm-us", SessionName: "zwm-v1-deadbeef-meanderx-kunda", TerminalID: "terminal-1", Worktree: "/work/kunda"}}}}
	plain := newRenderer(&bytes.Buffer{}, false).restorePlan("latest", app.Inventory{}, plan)
	styled := newRenderer(&bytes.Buffer{}, true).restorePlan("latest", app.Inventory{}, plan)
	if !strings.Contains(styled, "\x1b[") {
		t.Fatalf("styled output has no ANSI sequences: %q", styled)
	}
	if strings.Contains(plain, "\x1b[") {
		t.Fatalf("plain output contains ANSI sequences: %q", plain)
	}
	if stripped := stripANSI(styled); stripped != plain {
		t.Fatalf("styled content differs from plain (-want +got):\n%s", cmp.Diff(plain, stripped))
	}
}

func TestNarrowRestorePlanStacksFieldValues(t *testing.T) {
	plan := restore.Plan{Opens: []restore.Open{{Mode: "-n", Mapping: state.Mapping{Host: "vm-us", SessionName: "zwm-v1-deadbeef-meanderx-kunda", TerminalID: "terminal-1", Worktree: "/work/kunda"}}}}
	output := newRendererAtWidth(&bytes.Buffer{}, false, 60).restorePlan("latest", app.Inventory{}, plan)
	if !strings.Contains(output, "  Worktree\n  /work/kunda\n") {
		t.Fatalf("narrow fields are not stacked:\n%s", output)
	}
}

func stripANSI(value string) string {
	for {
		start := strings.Index(value, "\x1b[")
		if start < 0 {
			return value
		}
		end := start + 2
		for end < len(value) && (value[end] < '@' || value[end] > '~') {
			end++
		}
		if end < len(value) {
			end++
		}
		value = value[:start] + value[end:]
	}
}
