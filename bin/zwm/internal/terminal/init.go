package terminal

import (
	"fmt"

	"github.com/vikramsg/dotfiles/bin/zwm/internal/inventory"
)

type Plan struct {
	Session inventory.Session
	Create  bool
}

func PlanForWorktree(worktree string, sessions []inventory.Session) (Plan, error) {
	short, err := inventory.SessionForWorktree(worktree, 8)
	if err != nil {
		return Plan{}, err
	}
	for _, session := range sessions {
		if session.Name != short.Name {
			continue
		}
		if session.Worktree == "" || session.Worktree == short.Worktree {
			return Plan{Session: short}, nil
		}

		long, err := inventory.SessionForWorktree(worktree, 16)
		if err != nil {
			return Plan{}, err
		}
		for _, candidate := range sessions {
			if candidate.Name != long.Name {
				continue
			}
			if candidate.Worktree == "" || candidate.Worktree == long.Worktree {
				return Plan{Session: long}, nil
			}
			return Plan{}, fmt.Errorf("hash collision persists for worktree %q", long.Worktree)
		}
		return Plan{Session: long, Create: true}, nil
	}

	return Plan{Session: short, Create: true}, nil
}
