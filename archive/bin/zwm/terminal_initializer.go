package zwm

import (
	"fmt"

	"zwm/internal/inventory"
)

type TerminalPlan struct {
	Session inventory.Session
	Create  bool
}

func PlanTerminal(worktree string, sessions []inventory.Session) (TerminalPlan, error) {
	short, err := inventory.SessionForWorktree(worktree, 8)
	if err != nil {
		return TerminalPlan{}, err
	}
	for _, session := range sessions {
		if session.Name != short.Name {
			continue
		}
		if session.Worktree == "" || session.Worktree == short.Worktree {
			return TerminalPlan{Session: short}, nil
		}

		long, err := inventory.SessionForWorktree(worktree, 16)
		if err != nil {
			return TerminalPlan{}, err
		}
		for _, candidate := range sessions {
			if candidate.Name != long.Name {
				continue
			}
			if candidate.Worktree == "" || candidate.Worktree == long.Worktree {
				return TerminalPlan{Session: long}, nil
			}
			return TerminalPlan{}, fmt.Errorf("hash collision persists for worktree %q", long.Worktree)
		}
		return TerminalPlan{Session: long, Create: true}, nil
	}

	return TerminalPlan{Session: short, Create: true}, nil
}
