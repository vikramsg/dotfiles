package zed

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"github.com/vikramsg/dotfiles/bin/zwm/internal/inventory"
	_ "modernc.org/sqlite"
)

type Reader struct {
	Path string
}

type remoteConnection struct {
	SSH *struct {
		Host struct {
			Hostname string
		}
	} `json:"Ssh"`
}

func DefaultDatabasePath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("resolve home directory: %w", err)
	}
	if runtime.GOOS == "darwin" {
		return filepath.Join(home, "Library", "Application Support", "Zed", "db", "0-stable", "db.sqlite"), nil
	}
	stateHome := os.Getenv("XDG_DATA_HOME")
	if stateHome == "" {
		stateHome = filepath.Join(home, ".local", "share")
	}
	return filepath.Join(stateHome, "zed", "db", "0-stable", "db.sqlite"), nil
}

func (reader Reader) Worktrees(context context.Context) ([]inventory.WorktreeRecord, error) {
	database, err := sql.Open("sqlite", "file:"+reader.Path+"?mode=ro")
	if err != nil {
		return nil, fmt.Errorf("open Zed database read-only: %w", err)
	}
	defer database.Close()
	if _, err := database.ExecContext(context, "PRAGMA query_only = ON"); err != nil {
		return nil, fmt.Errorf("set Zed database query-only mode: %w", err)
	}

	rows, err := database.QueryContext(context, `
		SELECT terminal_id, working_directory, remote_connection
		FROM sidebar_terminal_threads
		WHERE working_directory IS NOT NULL AND remote_connection IS NOT NULL`)
	if err != nil {
		return nil, fmt.Errorf("query Zed terminal metadata: %w", err)
	}
	defer rows.Close()

	records := make([]inventory.WorktreeRecord, 0)
	for rows.Next() {
		var terminalID string
		var worktree string
		var encodedConnection string
		if err := rows.Scan(&terminalID, &worktree, &encodedConnection); err != nil {
			return nil, fmt.Errorf("scan Zed terminal metadata: %w", err)
		}
		var connection remoteConnection
		if err := json.Unmarshal([]byte(encodedConnection), &connection); err != nil {
			return nil, fmt.Errorf("decode Zed remote connection: %w", err)
		}
		if connection.SSH == nil || connection.SSH.Host.Hostname == "" {
			continue
		}
		records = append(records, inventory.WorktreeRecord{
			Host:       connection.SSH.Host.Hostname,
			TerminalID: terminalID,
			Worktree:   worktree,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate Zed terminal metadata: %w", err)
	}
	return records, nil
}
