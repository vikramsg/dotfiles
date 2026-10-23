package zwm

import (
	"fmt"
	"sort"

	"zwm/internal/inventory"
)

type RestoreAction struct {
	Mode    string
	Mapping StateMapping
}

type RestorePlan struct {
	Opens   []RestoreAction
	Missing []string
}

func BuildRestorePlan(mappings []StateMapping, worktrees []string) (RestorePlan, error) {
	selected, missing, err := selectMappings(mappings, worktrees)
	if err != nil {
		return RestorePlan{}, err
	}
	return RestorePlan{Opens: restoreActionsFor(selected), Missing: missing}, nil
}

func (plan RestorePlan) ValidationError() error {
	if len(plan.Missing) > 0 {
		return fmt.Errorf("requested worktrees are not restorable: %v", plan.Missing)
	}
	if len(plan.Opens) == 0 {
		return fmt.Errorf("no restorable worktrees found")
	}
	return nil
}

func selectMappings(mappings []StateMapping, worktrees []string) ([]StateMapping, []string, error) {
	if len(worktrees) == 0 {
		return mappings, nil, nil
	}
	byWorktree := make(map[string]StateMapping, len(mappings))
	for _, mapping := range mappings {
		byWorktree[mapping.Worktree] = mapping
	}
	selected := make([]StateMapping, 0, len(worktrees))
	missing := make([]string, 0)
	seen := make(map[string]bool, len(worktrees))
	for _, worktree := range worktrees {
		normalized, err := inventory.NormalizeWorktree(worktree)
		if err != nil {
			return nil, nil, err
		}
		if seen[normalized] {
			continue
		}
		seen[normalized] = true
		mapping, ok := byWorktree[normalized]
		if !ok {
			missing = append(missing, normalized)
			continue
		}
		selected = append(selected, mapping)
	}
	return selected, missing, nil
}

func restoreActionsFor(mappings []StateMapping) []RestoreAction {
	sorted := append([]StateMapping(nil), mappings...)
	sort.Slice(sorted, func(left int, right int) bool {
		return sorted[left].Worktree < sorted[right].Worktree
	})
	opens := make([]RestoreAction, 0, len(sorted))
	for index, mapping := range sorted {
		mode := "-r"
		if index == 0 {
			mode = "-n"
		}
		opens = append(opens, RestoreAction{Mode: mode, Mapping: mapping})
	}
	return opens
}
