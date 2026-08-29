package tmux

import (
	"context"
	"fmt"
	"os/exec"
	"runtime"
	"strings"

	"github.com/vikramsg/dotfiles/bin/zwm/internal/inventory"
)

const remoteTmux = "/home/linuxbrew/.linuxbrew/bin/tmux"

type Runner struct {
	Host       string
	Executable string
}

func Executable() string {
	if runtime.GOOS == "linux" {
		return remoteTmux
	}
	return "tmux"
}

func (runner Runner) List(context context.Context) ([]inventory.Session, error) {
	arguments := []string{"list-sessions", "-F", "#{session_name}\t#{@zwm_worktree}"}
	output, err := runner.run(context, arguments...)
	if err != nil {
		if isEmptyServerError(err) {
			return nil, nil
		}
		return nil, err
	}

	return parseSessions(output), nil
}

func parseSessions(output string) []inventory.Session {
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

func (runner Runner) run(context context.Context, arguments ...string) (string, error) {
	command := runner.Executable
	if command == "" {
		command = Executable()
	}
	commandArguments := arguments
	if runner.Host != "" {
		command = "ssh"
		commandArguments = sshArguments(runner.Host, arguments)
	}
	process := exec.CommandContext(context, command, commandArguments...)
	output, err := process.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("run %s %s: %w: %s", command, strings.Join(commandArguments, " "), err, output)
	}
	return string(output), nil
}

func sshArguments(host string, tmuxArguments []string) []string {
	remoteCommand := append([]string{remoteTmux}, tmuxArguments...)
	return []string{"-T", "-o", "BatchMode=yes", host, shellCommand(remoteCommand)}
}

func shellCommand(arguments []string) string {
	quoted := make([]string, 0, len(arguments))
	for _, argument := range arguments {
		quoted = append(quoted, shellQuote(argument))
	}
	return strings.Join(quoted, " ")
}

func shellQuote(argument string) string {
	return "'" + strings.ReplaceAll(argument, "'", "'\"'\"'") + "'"
}
