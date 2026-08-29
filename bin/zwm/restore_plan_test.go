package zwm

import (
	"testing"
)

func TestBuildSortsWorktreesAndUsesNewThenReuse(t *testing.T) {
	plan, err := BuildRestorePlan([]StateMapping{
		{Worktree: "/work/zeta"},
		{Worktree: "/work/alpha"},
	}, nil)
	if err != nil {
		t.Fatalf("Build: %v", err)
	}
	opens := plan.Opens

	if len(opens) != 2 {
		t.Fatalf("open count = %d, want 2", len(opens))
	}
	if opens[0].Mode != "-n" || opens[0].Mapping.Worktree != "/work/alpha" {
		t.Fatalf("first open = %#v, want alpha with -n", opens[0])
	}
	if opens[1].Mode != "-r" || opens[1].Mapping.Worktree != "/work/zeta" {
		t.Fatalf("second open = %#v, want zeta with -r", opens[1])
	}
}

func TestBuildSelectsRequestedWorktreesAndReportsMissingOnes(t *testing.T) {
	plan, err := BuildRestorePlan([]StateMapping{{Worktree: "/work/alpha"}, {Worktree: "/work/zeta"}}, []string{"/work/zeta", "/work/missing"})
	if err != nil {
		t.Fatalf("Build: %v", err)
	}
	if len(plan.Opens) != 1 || plan.Opens[0].Mapping.Worktree != "/work/zeta" {
		t.Fatalf("opens = %#v", plan.Opens)
	}
	if len(plan.Missing) != 1 || plan.Missing[0] != "/work/missing" {
		t.Fatalf("missing = %#v", plan.Missing)
	}
	if plan.ValidationError() == nil {
		t.Fatal("ValidationError() = nil, want missing-worktree error")
	}
}
