package state

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/vikramsg/dotfiles/bin/zwm/internal/inventory"
	_ "modernc.org/sqlite"
)

type Mapping struct {
	Host                  string
	SessionID             string
	SessionName           string
	Worktree              string
	TerminalID            string
	RecordedAt            time.Time
	LastSeenOnVMAt        time.Time
	LastMatchedToZedAt    time.Time
	ZedDatabaseObservedAt time.Time
}

type Event struct {
	ID      int64
	At      time.Time
	Kind    string
	Message string
}

type Store struct {
	database *sql.DB
}

func Open(databasePath string) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(databasePath), 0o755); err != nil {
		return nil, fmt.Errorf("create state directory: %w", err)
	}
	database, err := sql.Open("sqlite", databasePath)
	if err != nil {
		return nil, fmt.Errorf("open state database: %w", err)
	}
	store := &Store{database: database}
	if err := store.migrate(context.Background()); err != nil {
		database.Close()
		return nil, err
	}
	return store, nil
}

func (store *Store) Close() error {
	return store.database.Close()
}

func (store *Store) migrate(context context.Context) error {
	statements := []string{
		`CREATE TABLE IF NOT EXISTS mappings (
			host TEXT NOT NULL,
			session_id TEXT NOT NULL,
			session_name TEXT NOT NULL,
			worktree TEXT NOT NULL,
			terminal_id TEXT NOT NULL,
			recorded_at TEXT NOT NULL,
			last_seen_on_vm_at TEXT NOT NULL,
			last_matched_to_zed_at TEXT NOT NULL,
			zed_database_observed_at TEXT NOT NULL,
			active INTEGER NOT NULL,
			PRIMARY KEY (host, session_name)
		) STRICT`,
		`CREATE TABLE IF NOT EXISTS events (
			id INTEGER PRIMARY KEY,
			occurred_at TEXT NOT NULL,
			kind TEXT NOT NULL,
			message TEXT NOT NULL
		) STRICT`,
	}
	for _, statement := range statements {
		if _, err := store.database.ExecContext(context, statement); err != nil {
			return fmt.Errorf("migrate state database: %w", err)
		}
	}
	return nil
}

func (store *Store) SaveSnapshot(context context.Context, host string, at time.Time, live []inventory.Session, mappings []inventory.Mapping) error {
	transaction, err := store.database.BeginTx(context, nil)
	if err != nil {
		return fmt.Errorf("begin state snapshot: %w", err)
	}
	defer transaction.Rollback()

	if _, err := transaction.ExecContext(context, `UPDATE mappings SET active = 0 WHERE host = ?`, host); err != nil {
		return fmt.Errorf("deactivate prior mappings: %w", err)
	}
	for _, session := range live {
		if _, err := transaction.ExecContext(context, `
			INSERT INTO mappings (
				host, session_id, session_name, worktree, terminal_id, recorded_at,
				last_seen_on_vm_at, last_matched_to_zed_at, zed_database_observed_at, active
			) VALUES (?, ?, ?, ?, '', ?, ?, '', '', 1)
			ON CONFLICT(host, session_name) DO UPDATE SET
				session_id = excluded.session_id,
				worktree = excluded.worktree,
				terminal_id = '',
				last_seen_on_vm_at = excluded.last_seen_on_vm_at,
				last_matched_to_zed_at = '',
				zed_database_observed_at = '',
				active = 1`,
			host,
			session.ID,
			session.Name,
			session.Worktree,
			at.Format(time.RFC3339Nano),
			at.Format(time.RFC3339Nano),
		); err != nil {
			return fmt.Errorf("persist live session: %w", err)
		}
	}
	for _, mapping := range mappings {
		if _, err := transaction.ExecContext(context, `
			INSERT INTO mappings (
				host, session_id, session_name, worktree, terminal_id, recorded_at,
				last_seen_on_vm_at, last_matched_to_zed_at, zed_database_observed_at, active
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
			ON CONFLICT(host, session_name) DO UPDATE SET
				session_id = excluded.session_id,
				worktree = excluded.worktree,
				terminal_id = excluded.terminal_id,
				last_seen_on_vm_at = excluded.last_seen_on_vm_at,
				last_matched_to_zed_at = excluded.last_matched_to_zed_at,
				zed_database_observed_at = excluded.zed_database_observed_at,
				active = 1`,
			mapping.Host,
			mapping.Session.ID,
			mapping.Session.Name,
			mapping.Worktree,
			mapping.TerminalID,
			at.Format(time.RFC3339Nano),
			at.Format(time.RFC3339Nano),
			at.Format(time.RFC3339Nano),
			at.Format(time.RFC3339Nano),
		); err != nil {
			return fmt.Errorf("upsert mapping: %w", err)
		}
	}
	if err := transaction.Commit(); err != nil {
		return fmt.Errorf("commit state snapshot: %w", err)
	}
	return nil
}

func (store *Store) AppendEvent(context context.Context, event Event) error {
	_, err := store.database.ExecContext(context, `INSERT INTO events (occurred_at, kind, message) VALUES (?, ?, ?)`, event.At.Format(time.RFC3339Nano), event.Kind, event.Message)
	if err != nil {
		return fmt.Errorf("append event: %w", err)
	}
	return nil
}

func (store *Store) ActiveMappings(context context.Context) ([]Mapping, error) {
	rows, err := store.database.QueryContext(context, `
		SELECT host, session_id, session_name, worktree, terminal_id, recorded_at,
			last_seen_on_vm_at, last_matched_to_zed_at, zed_database_observed_at
		FROM mappings
		WHERE active = 1 AND terminal_id != ''
		ORDER BY worktree`)
	if err != nil {
		return nil, fmt.Errorf("list active mappings: %w", err)
	}
	defer rows.Close()

	mappings := make([]Mapping, 0)
	for rows.Next() {
		mapping, err := scanMapping(rows)
		if err != nil {
			return nil, err
		}
		mappings = append(mappings, mapping)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate active mappings: %w", err)
	}
	return mappings, nil
}

func (store *Store) Events(context context.Context, limit int) ([]Event, error) {
	rows, err := store.database.QueryContext(context, `
		SELECT id, occurred_at, kind, message
		FROM events
		ORDER BY id DESC
		LIMIT ?`, limit)
	if err != nil {
		return nil, fmt.Errorf("list events: %w", err)
	}
	defer rows.Close()

	events := make([]Event, 0)
	for rows.Next() {
		var occurredAt string
		var event Event
		if err := rows.Scan(&event.ID, &occurredAt, &event.Kind, &event.Message); err != nil {
			return nil, fmt.Errorf("scan event: %w", err)
		}
		at, err := time.Parse(time.RFC3339Nano, occurredAt)
		if err != nil {
			return nil, fmt.Errorf("parse event timestamp: %w", err)
		}
		event.At = at
		events = append(events, event)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate events: %w", err)
	}
	return events, nil
}

func (store *Store) LatestEvent(context context.Context, kinds ...string) (Event, bool, error) {
	if len(kinds) == 0 {
		return Event{}, false, nil
	}
	placeholders := strings.TrimSuffix(strings.Repeat("?,", len(kinds)), ",")
	arguments := make([]any, len(kinds))
	for index, kind := range kinds {
		arguments[index] = kind
	}
	row := store.database.QueryRowContext(context, `
		SELECT id, occurred_at, kind, message
		FROM events
		WHERE kind IN (`+placeholders+`)
		ORDER BY id DESC
		LIMIT 1`, arguments...)
	var event Event
	var occurredAt string
	if err := row.Scan(&event.ID, &occurredAt, &event.Kind, &event.Message); err != nil {
		if err == sql.ErrNoRows {
			return Event{}, false, nil
		}
		return Event{}, false, fmt.Errorf("read latest event: %w", err)
	}
	at, err := time.Parse(time.RFC3339Nano, occurredAt)
	if err != nil {
		return Event{}, false, fmt.Errorf("parse latest event timestamp: %w", err)
	}
	event.At = at
	return event, true, nil
}

type scanner interface {
	Scan(...any) error
}

func scanMapping(row scanner) (Mapping, error) {
	var values [4]string
	mapping := Mapping{}
	if err := row.Scan(
		&mapping.Host,
		&mapping.SessionID,
		&mapping.SessionName,
		&mapping.Worktree,
		&mapping.TerminalID,
		&values[0],
		&values[1],
		&values[2],
		&values[3],
	); err != nil {
		return Mapping{}, fmt.Errorf("scan mapping: %w", err)
	}
	timestamps := []*time.Time{
		&mapping.RecordedAt,
		&mapping.LastSeenOnVMAt,
		&mapping.LastMatchedToZedAt,
		&mapping.ZedDatabaseObservedAt,
	}
	for index, value := range values {
		if value == "" {
			continue
		}
		parsed, err := time.Parse(time.RFC3339Nano, value)
		if err != nil {
			return Mapping{}, fmt.Errorf("parse mapping timestamp: %w", err)
		}
		*timestamps[index] = parsed
	}
	return mapping, nil
}
