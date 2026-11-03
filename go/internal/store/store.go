// Package store defines the persistence boundary for usage records.
//
// The rest of the application depends only on the Store interface, so the
// in-memory implementation below can be swapped for MySQL/Postgres without
// touching ingestion or reporting logic.
package store

import (
	"context"
	"errors"
	"sync"
	"time"
)

// UsageRecord is a single metered usage line for a customer.
// Monetary amounts are integer cents: float arithmetic has no place in billing.
type UsageRecord struct {
	ID          string    // idempotency key, unique per record
	CustomerID  string
	Service     string    // e.g. "compute", "storage"
	CostCents   int64     // what the provider charges us
	PriceCents  int64     // what we charge the customer
	OccurredAt  time.Time
}

var (
	// ErrDuplicate is returned when a record with the same ID already exists.
	// Callers treat it as success: re-delivered batches must not double-bill.
	ErrDuplicate = errors.New("store: duplicate record")

	// ErrNotFound is returned when a customer has no recorded usage.
	ErrNotFound = errors.New("store: not found")
)

// Store persists usage records.
type Store interface {
	// Insert stores one record, returning ErrDuplicate if r.ID was seen before.
	Insert(ctx context.Context, r UsageRecord) error
	// ByCustomer returns all records for one customer.
	ByCustomer(ctx context.Context, customerID string) ([]UsageRecord, error)
}

// Memory is a thread-safe in-memory Store, used in tests and this sample's
// server. It mirrors the semantics the SQL implementation must provide:
// ID uniqueness enforced at the storage layer, not by callers.
type Memory struct {
	mu      sync.RWMutex
	byID    map[string]struct{}
	byOwner map[string][]UsageRecord
}

// NewMemory returns an empty in-memory store.
func NewMemory() *Memory {
	return &Memory{
		byID:    make(map[string]struct{}),
		byOwner: make(map[string][]UsageRecord),
	}
}

// Insert implements Store.
func (m *Memory) Insert(ctx context.Context, r UsageRecord) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.byID[r.ID]; ok {
		return ErrDuplicate
	}
	m.byID[r.ID] = struct{}{}
	m.byOwner[r.CustomerID] = append(m.byOwner[r.CustomerID], r)
	return nil
}

// ByCustomer implements Store.
func (m *Memory) ByCustomer(ctx context.Context, customerID string) ([]UsageRecord, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	m.mu.RLock()
	defer m.mu.RUnlock()
	records, ok := m.byOwner[customerID]
	if !ok {
		return nil, ErrNotFound
	}
	out := make([]UsageRecord, len(records))
	copy(out, records)
	return out, nil
}
