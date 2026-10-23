package inventory

import "testing"

func TestReconcileMatchesSessionToSameHashedWorktree(t *testing.T) {
	worktree := "/home/vikram/projects/meanderx/kunda-wt"
	session, err := SessionForWorktree(worktree, shortIDWidth)
	if err != nil {
		t.Fatalf("derive session: %v", err)
	}

	mappings, unresolved := Reconcile("vm-us", []Session{session}, []WorktreeRecord{{
		Host:       "vm-us",
		TerminalID: "terminal-1",
		Worktree:   worktree,
	}})

	if len(unresolved) != 0 {
		t.Fatalf("unresolved = %#v, want none", unresolved)
	}
	if len(mappings) != 1 {
		t.Fatalf("mappings = %#v, want one mapping", mappings)
	}
	if mappings[0].TerminalID != "terminal-1" {
		t.Fatalf("terminal ID = %q, want terminal-1", mappings[0].TerminalID)
	}
}

func TestReconcileDoesNotMatchDifferentWorktreeWithSameHost(t *testing.T) {
	session, err := SessionForWorktree("/home/vikram/projects/meanderx/kunda-wt", shortIDWidth)
	if err != nil {
		t.Fatalf("derive session: %v", err)
	}

	mappings, unresolved := Reconcile("vm-us", []Session{session}, []WorktreeRecord{{
		Host:       "vm-us",
		TerminalID: "terminal-1",
		Worktree:   "/home/vikram/projects/meanderx/kunda-wt2",
	}})

	if len(mappings) != 0 {
		t.Fatalf("mappings = %#v, want none", mappings)
	}
	if len(unresolved) != 1 {
		t.Fatalf("unresolved = %#v, want one session", unresolved)
	}
}

func TestMatchRecordRejectsAmbiguousHashCandidates(t *testing.T) {
	session := Session{ID: "deadbeef", Worktree: "/work/one"}
	_, ok := matchRecord(session, map[string][]WorktreeRecord{
		"deadbeef": {
			{Worktree: "/work/one"},
			{Worktree: "/work/two"},
		},
	})
	if ok {
		t.Fatal("matchRecord accepted an ambiguous hash")
	}
}

func TestReconcileRecoversContinuumSessionWithoutWorktreeMetadata(t *testing.T) {
	worktree := "/home/vikram/projects/meanderx/kunda-wt"
	expected, err := SessionForWorktree(worktree, shortIDWidth)
	if err != nil {
		t.Fatalf("derive session: %v", err)
	}
	restored := Session{Name: expected.Name, ID: expected.ID}

	mappings, unresolved := Reconcile("vm-us", []Session{restored}, []WorktreeRecord{{Host: "vm-us", TerminalID: "terminal-1", Worktree: worktree}})
	if len(unresolved) != 0 || len(mappings) != 1 {
		t.Fatalf("mappings = %#v, unresolved = %#v", mappings, unresolved)
	}
	if mappings[0].Session != expected {
		t.Fatalf("recovered session = %#v, want %#v", mappings[0].Session, expected)
	}
}
