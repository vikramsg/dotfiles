package state

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/vikramsg/dotfiles/bin/zwm/internal/inventory"
)

type fakeScanner struct {
	values []any
}

func (scanner fakeScanner) Scan(destinations ...any) error {
	for index, destination := range destinations {
		*(destination.(*string)) = scanner.values[index].(string)
	}
	return nil
}

func TestScanMappingRepresentsMissingZedTimestampsAsUnobserved(t *testing.T) {
	mapping, err := scanMapping(fakeScanner{values: []any{
		"vm-us",
		"deadbeef",
		"zwm-v1-deadbeef-meanderx-kunda-wt",
		"/home/vikram/projects/meanderx/kunda-wt",
		"",
		"2026-08-29T12:00:00Z",
		"2026-08-29T12:00:00Z",
		"",
		"",
	}})
	if err != nil {
		t.Fatalf("scan mapping: %v", err)
	}
	if !mapping.LastMatchedToZedAt.IsZero() || !mapping.ZedDatabaseObservedAt.IsZero() {
		t.Fatalf("unobserved timestamps = %#v", mapping)
	}
}

func TestSaveSnapshotClearsStaleTerminalMatchForUnresolvedSession(t *testing.T) {
	store, err := Open(filepath.Join(t.TempDir(), "state-test"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()

	session := inventory.Session{Name: "zwm-v1-deadbeef-meanderx-kunda", ID: "deadbeef", Worktree: "/work/kunda"}
	mapping := inventory.Mapping{Host: "vm-us", Session: session, TerminalID: "terminal-1", Worktree: session.Worktree}
	if err := store.SaveSnapshot(context.Background(), "vm-us", time.Now().UTC(), []inventory.Session{session}, []inventory.Mapping{mapping}); err != nil {
		t.Fatalf("save matched snapshot: %v", err)
	}
	if err := store.SaveSnapshot(context.Background(), "vm-us", time.Now().UTC(), []inventory.Session{session}, nil); err != nil {
		t.Fatalf("save unresolved snapshot: %v", err)
	}

	active, err := store.ActiveMappings(context.Background())
	if err != nil {
		t.Fatalf("active mappings: %v", err)
	}
	if len(active) != 0 {
		t.Fatalf("active mappings = %#v, want none", active)
	}
}
