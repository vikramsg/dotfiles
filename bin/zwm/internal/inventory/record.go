package inventory

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"path"
	"strings"
)

const (
	prefix       = "zwm-v1"
	shortIDWidth = 8
	longIDWidth  = 16
)

type Session struct {
	Name     string
	ID       string
	Worktree string
}

type WorktreeRecord struct {
	Host       string
	TerminalID string
	Worktree   string
}

type Mapping struct {
	Host       string
	Session    Session
	TerminalID string
	Worktree   string
}

func NormalizeWorktree(worktree string) (string, error) {
	if !path.IsAbs(worktree) {
		return "", fmt.Errorf("worktree must be an absolute path: %q", worktree)
	}

	return path.Clean(worktree), nil
}

func SessionForWorktree(worktree string, width int) (Session, error) {
	normalized, err := NormalizeWorktree(worktree)
	if err != nil {
		return Session{}, err
	}
	if width != shortIDWidth && width != longIDWidth {
		return Session{}, fmt.Errorf("unsupported session ID width: %d", width)
	}

	digest := sha256.Sum256([]byte(normalized))
	id := hex.EncodeToString(digest[:])[:width]
	parent := path.Base(path.Dir(normalized))
	leaf := path.Base(normalized)
	return Session{
		Name:     fmt.Sprintf("%s-%s-%s-%s", prefix, id, parent, leaf),
		ID:       id,
		Worktree: normalized,
	}, nil
}

func ParseSession(name string, worktree string) (Session, bool) {
	session, ok := ParseSessionName(name)
	if !ok {
		return Session{}, false
	}

	normalized, err := NormalizeWorktree(worktree)
	if err != nil {
		return Session{}, false
	}
	expected, err := SessionForWorktree(normalized, len(session.ID))
	if err != nil || expected.Name != name {
		return Session{}, false
	}
	return expected, true
}

func ParseSessionName(name string) (Session, bool) {
	parts := strings.SplitN(name, "-", 4)
	if len(parts) != 4 || parts[0] != "zwm" || parts[1] != "v1" {
		return Session{}, false
	}

	id := parts[2]
	if len(id) != shortIDWidth && len(id) != longIDWidth {
		return Session{}, false
	}
	for _, character := range id {
		if !(character >= '0' && character <= '9') && !(character >= 'a' && character <= 'f') {
			return Session{}, false
		}
	}
	if strings.TrimSpace(parts[3]) == "" {
		return Session{}, false
	}
	return Session{Name: name, ID: id}, true
}
