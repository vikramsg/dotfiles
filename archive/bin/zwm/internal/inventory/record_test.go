package inventory

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestSessionForWorktreeUsesDeterministicEightCharacterHash(t *testing.T) {
	worktree := "/home/user/projects/example/project-wt"

	session, err := SessionForWorktree(worktree, shortIDWidth)
	if err != nil {
		t.Fatalf("derive session: %v", err)
	}

	if session.Worktree != worktree {
		t.Fatalf("worktree = %q, want %q", session.Worktree, worktree)
	}
	if len(session.ID) != shortIDWidth {
		t.Fatalf("session ID length = %d, want %d", len(session.ID), shortIDWidth)
	}
	if session.Name == "" {
		t.Fatal("session name is empty")
	}

	again, err := SessionForWorktree(worktree, shortIDWidth)
	if err != nil {
		t.Fatalf("derive session again: %v", err)
	}
	if difference := cmp.Diff(session, again); difference != "" {
		t.Fatalf("session mismatch (-want +got):\n%s", difference)
	}
}

func TestNormalizeWorktreeRejectsRelativePaths(t *testing.T) {
	if _, err := NormalizeWorktree("worktree"); err == nil {
		t.Fatal("NormalizeWorktree succeeded for relative path")
	}
}

func TestParseSessionRejectsForeignSession(t *testing.T) {
	if _, ok := ParseSession("zed-example-project-wt", "/home/user/projects/example/project-wt"); ok {
		t.Fatal("ParseSession accepted foreign session")
	}
}

func TestParseSessionRejectsSessionIDThatDoesNotMatchWorktree(t *testing.T) {
	if _, ok := ParseSession("zwm-v1-deadbeef-example-project-wt", "/home/user/projects/example/project-wt"); ok {
		t.Fatal("ParseSession accepted a session ID unrelated to its worktree")
	}
}

func TestParseSessionNameAcceptsDeterministicSessionWithoutMetadata(t *testing.T) {
	session, ok := ParseSessionName("zwm-v1-deadbeef-example-project-wt")
	if !ok {
		t.Fatal("ParseSessionName rejected deterministic session name")
	}
	if session.ID != "deadbeef" || session.Worktree != "" {
		t.Fatalf("session = %#v", session)
	}
}
