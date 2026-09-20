package inventory

import "sort"

func Reconcile(host string, sessions []Session, records []WorktreeRecord) ([]Mapping, []Session) {
	recordsByID := make(map[string][]WorktreeRecord)
	for _, record := range records {
		if record.Host != host {
			continue
		}
		normalized, err := NormalizeWorktree(record.Worktree)
		if err != nil {
			continue
		}
		short, err := SessionForWorktree(normalized, shortIDWidth)
		if err != nil {
			continue
		}
		normalizedRecord := WorktreeRecord{
			Host:       record.Host,
			TerminalID: record.TerminalID,
			Worktree:   normalized,
		}
		recordsByID[short.ID] = appendUniqueWorktree(recordsByID[short.ID], normalizedRecord)
		long, err := SessionForWorktree(normalized, longIDWidth)
		if err == nil {
			recordsByID[long.ID] = appendUniqueWorktree(recordsByID[long.ID], normalizedRecord)
		}
	}

	mappings := make([]Mapping, 0, len(sessions))
	unresolved := make([]Session, 0)
	for _, session := range sessions {
		record, ok := matchRecord(session, recordsByID)
		if !ok {
			unresolved = append(unresolved, session)
			continue
		}
		matchedSession, err := SessionForWorktree(record.Worktree, len(session.ID))
		if err != nil || matchedSession.Name != session.Name {
			unresolved = append(unresolved, session)
			continue
		}
		mappings = append(mappings, Mapping{
			Host:       host,
			Session:    matchedSession,
			TerminalID: record.TerminalID,
			Worktree:   record.Worktree,
		})
	}

	sort.Slice(mappings, func(left int, right int) bool {
		return mappings[left].Worktree < mappings[right].Worktree
	})
	sort.Slice(unresolved, func(left int, right int) bool {
		return unresolved[left].Name < unresolved[right].Name
	})
	return mappings, unresolved
}

func appendUniqueWorktree(records []WorktreeRecord, candidate WorktreeRecord) []WorktreeRecord {
	for _, record := range records {
		if record.Worktree == candidate.Worktree {
			return records
		}
	}
	return append(records, candidate)
}

func matchRecord(session Session, recordsByID map[string][]WorktreeRecord) (WorktreeRecord, bool) {
	candidates := recordsByID[session.ID]
	if len(candidates) != 1 || (session.Worktree != "" && candidates[0].Worktree != session.Worktree) {
		return WorktreeRecord{}, false
	}
	return candidates[0], true
}
