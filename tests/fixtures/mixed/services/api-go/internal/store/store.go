package store

import (
	"context"
	"database/sql"
)

type Store struct{ db *sql.DB }

func New(db *sql.DB) *Store { return &Store{db: db} }

func (s *Store) List(ctx context.Context) ([]string, error) {
	return nil, nil
}
