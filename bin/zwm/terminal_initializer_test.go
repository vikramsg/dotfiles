package zwm

import (
	"testing"

	"zwm/internal/inventory"
)

func TestPlanForWorktreeCreatesShortSessionWhenNoSessionExists(t *testing.T) {
	plan, err := PlanTerminal("/home/vikram/projects/meanderx/kunda-wt", nil)
	if err != nil {
		t.Fatalf("plan terminal init: %v", err)
	}
	if !plan.Create {
		t.Fatal("Create = false, want true")
	}
	if len(plan.Session.ID) != 8 {
		t.Fatalf("session ID length = %d, want 8", len(plan.Session.ID))
	}
}

func TestPlanForWorktreeAttachesExistingMatchingSession(t *testing.T) {
	session, err := inventory.SessionForWorktree("/home/vikram/projects/meanderx/kunda-wt", 8)
	if err != nil {
		t.Fatalf("derive session: %v", err)
	}

	plan, err := PlanTerminal(session.Worktree, []inventory.Session{session})
	if err != nil {
		t.Fatalf("plan terminal init: %v", err)
	}
	if plan.Create {
		t.Fatal("Create = true, want false")
	}
	if plan.Session != session {
		t.Fatalf("session = %#v, want %#v", plan.Session, session)
	}
}

func TestPlanForWorktreeRepairsContinuumSessionWithoutMetadata(t *testing.T) {
	worktree := "/home/vikram/projects/meanderx/kunda-wt"
	session, err := inventory.SessionForWorktree(worktree, 8)
	if err != nil {
		t.Fatalf("derive session: %v", err)
	}
	session.Worktree = ""

	plan, err := PlanTerminal(worktree, []inventory.Session{session})
	if err != nil {
		t.Fatalf("plan terminal init: %v", err)
	}
	if plan.Create || plan.Session.Worktree != worktree || len(plan.Session.ID) != 8 {
		t.Fatalf("plan = %#v", plan)
	}
}

func TestPlanForWorktreeUsesLongIDAfterShortNameCollision(t *testing.T) {
	worktree := "/home/vikram/projects/meanderx/kunda-wt"
	short, err := inventory.SessionForWorktree(worktree, 8)
	if err != nil {
		t.Fatalf("derive short session: %v", err)
	}
	short.Worktree = "/other/root/kunda-wt"

	plan, err := PlanTerminal(worktree, []inventory.Session{short})
	if err != nil {
		t.Fatalf("plan terminal init: %v", err)
	}
	if !plan.Create {
		t.Fatal("Create = false, want true")
	}
	if len(plan.Session.ID) != 16 {
		t.Fatalf("session ID length = %d, want 16", len(plan.Session.ID))
	}
}
