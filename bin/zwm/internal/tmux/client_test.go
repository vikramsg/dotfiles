package tmux

import (
	"errors"
	"testing"
)

func TestListTreatsMissingDefaultSocketAsEmptyInventory(t *testing.T) {
	if !isEmptyServerError(errors.New("error connecting to /tmp/tmux/default (No such file or directory)")) {
		t.Fatal("missing tmux socket was not treated as an empty inventory")
	}
	if isEmptyServerError(errors.New("server exited unexpectedly")) {
		t.Fatal("unhealthy tmux server was treated as an empty inventory")
	}
}

func TestShellCommandPreservesTmuxFormatArgument(t *testing.T) {
	command := shellCommand([]string{remoteTmux, "list-sessions", "-F", "#{session_name}\t#{@zwm_worktree}"})
	want := "'/home/linuxbrew/.linuxbrew/bin/tmux' 'list-sessions' '-F' '#{session_name}\t#{@zwm_worktree}'"
	if command != want {
		t.Fatalf("shell command = %q, want %q", command, want)
	}
}

func TestSSHArgumentsDisableTTYAllocationForInventoryCommands(t *testing.T) {
	arguments := sshArguments("vm-us", []string{"list-sessions", "-F", "#{session_name}\t#{@zwm_worktree}"})
	if arguments[0] != "-T" {
		t.Fatalf("ssh arguments = %#v, want explicit -T", arguments)
	}
	if arguments[3] != "vm-us" {
		t.Fatalf("ssh host argument = %q, want vm-us", arguments[3])
	}
}

func TestParseSessionsPreservesEmptyMetadataOnFinalRow(t *testing.T) {
	sessions := parseSessions("zwm-v1-1beec1f3-meanderx-kunda\t\nzwm-v1-f7c9927e-meanderx-kunda-wt2\t\n")
	if len(sessions) != 2 {
		t.Fatalf("sessions = %#v, want two", sessions)
	}
	if sessions[1].Name != "zwm-v1-f7c9927e-meanderx-kunda-wt2" || sessions[1].Worktree != "" {
		t.Fatalf("final session = %#v", sessions[1])
	}
}
