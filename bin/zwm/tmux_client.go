package zwm

import (
	"context"
	"fmt"
	"os/exec"
	"runtime"
	"strings"

	"zwm/internal/inventory"
)

const remoteTmux = "/home/linuxbrew/.linuxbrew/bin/tmux"

type TmuxRunner struct {
	Host       string
	Executable string
}

func TmuxExecutable() string {
	if runtime.GOOS == "linux" {
		return remoteTmux
	}
	return "tmux"
}

func (runner TmuxRunner) List(context context.Context) ([]inventory.Session, error) {
	arguments := []string{"list-sessions", "-F", "#{session_name}\t#{@zwm_worktree}"}
	output, err := runner.run(context, arguments...)
	if err != nil {
		if isEmptyServerError(err) {
			return nil, nil
		}
		return nil, err
	}

	return parseTmuxSessions(output), nil
}

func parseTmuxSessions(output string) []inventory.Session {
	sessions := make([]inventory.Session, 0)
	for _, line := range strings.Split(strings.TrimRight(output, "\r\n"), "\n") {
		if line == "" {
			continue
		}
		fields := strings.SplitN(line, "\t", 2)
		if len(fields) != 2 {
			continue
		}
		session, ok := inventory.ParseSession(fields[0], fields[1])
		if !ok && fields[1] == "" {
			session, ok = inventory.ParseSessionName(fields[0])
		}
		if ok {
			sessions = append(sessions, session)
		}
	}
	return sessions
}

func isEmptyServerError(err error) bool {
	if err == nil {
		return false
	}
	message := err.Error()
	return strings.Contains(message, "no server running") || (strings.Contains(message, "error connecting to") && strings.Contains(message, "No such file or directory"))
}

func (runner TmuxRunner) run(context context.Context, arguments ...string) (string, error) {
	command := runner.Executable
	if command == "" {
		command = TmuxExecutable()
	}
	commandArguments := arguments
	if runner.Host != "" {
		command = "ssh"
		commandArguments = tmuxSSHArguments(runner.Host, arguments)
	}
	process := exec.CommandContext(context, command, commandArguments...)
	output, err := process.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("run %s %s: %w: %s", command, strings.Join(commandArguments, " "), err, output)
	}
	return string(output), nil
}

func tmuxSSHArguments(host string, tmuxArguments []string) []string {
	remoteCommand := append([]string{remoteTmux}, tmuxArguments...)
	return []string{"-T", "-o", "BatchMode=yes", host, remoteShellCommand(remoteCommand)}
}

func remoteShellCommand(arguments []string) string {
	quoted := make([]string, 0, len(arguments))
	for _, argument := range arguments {
		quoted = append(quoted, shellQuoteArgument(argument))
	}
	return strings.Join(quoted, " ")
}

func shellQuoteArgument(argument string) string {
	return "'" + strings.ReplaceAll(argument, "'", "'\"'\"'") + "'"
}
