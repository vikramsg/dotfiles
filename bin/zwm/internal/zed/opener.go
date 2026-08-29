package zed

import (
	"context"
	"fmt"
	"os/exec"

	"github.com/vikramsg/dotfiles/bin/zwm/internal/state"
)

type Opener struct {
	Command string
}

func (opener Opener) Open(context context.Context, mode string, mapping state.Mapping) error {
	command := opener.Command
	if command == "" {
		command = "zed"
	}
	url := fmt.Sprintf("ssh://%s:%s", mapping.Host, mapping.Worktree)
	process := exec.CommandContext(context, command, mode, url)
	if output, err := process.CombinedOutput(); err != nil {
		return fmt.Errorf("open %s: %w: %s", mapping.Worktree, err, output)
	}
	return nil
}
