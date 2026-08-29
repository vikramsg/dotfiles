package zed

import (
	"context"
	"fmt"
	"os/exec"
)

type Opener struct {
	Command string
}

func (opener Opener) Open(context context.Context, mode string, host string, worktree string) error {
	command := opener.Command
	if command == "" {
		command = "zed"
	}
	url := fmt.Sprintf("ssh://%s:%s", host, worktree)
	process := exec.CommandContext(context, command, mode, url)
	if output, err := process.CombinedOutput(); err != nil {
		return fmt.Errorf("open %s: %w: %s", worktree, err, output)
	}
	return nil
}
