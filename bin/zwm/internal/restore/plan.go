package restore

import (
	"fmt"
	"sort"

	"github.com/vikramsg/dotfiles/bin/zwm/internal/inventory"
	"github.com/vikramsg/dotfiles/bin/zwm/internal/state"
)

type Open struct {
	Mode    string
	Mapping state.Mapping
}

type Plan struct {
	Opens   []Open
	Missing []string
}

func Build(mappings []state.Mapping, worktrees []string) (Plan, error) {
	selected, missing, err := selectMappings(mappings, worktrees)
	if err != nil {
		return Plan{}, err
	}
	return Plan{Opens: opensFor(selected), Missing: missing}, nil
}

func (plan Plan) ValidationError() error {
	if len(plan.Missing) > 0 {
		return fmt.Errorf("requested worktrees are not restorable: %v", plan.Missing)
	}
	if len(plan.Opens) == 0 {
		return fmt.Errorf("no restorable worktrees found")
	}
	return nil
}

func selectMappings(mappings []state.Mapping, worktrees []string) ([]state.Mapping, []string, error) {
	if len(worktrees) == 0 {
		return mappings, nil, nil
	}
	byWorktree := make(map[string]state.Mapping, len(mappings))
	for _, mapping := range mappings {
		byWorktree[mapping.Worktree] = mapping
	}
	selected := make([]state.Mapping, 0, len(worktrees))
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

func opensFor(mappings []state.Mapping) []Open {
	sorted := append([]state.Mapping(nil), mappings...)
	sort.Slice(sorted, func(left int, right int) bool {
		return sorted[left].Worktree < sorted[right].Worktree
	})
	opens := make([]Open, 0, len(sorted))
	for index, mapping := range sorted {
		mode := "-r"
		if index == 0 {
			mode = "-n"
		}
		opens = append(opens, Open{Mode: mode, Mapping: mapping})
	}
	return opens
}
