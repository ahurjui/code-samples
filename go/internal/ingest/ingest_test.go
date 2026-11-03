package ingest

import (
	"context"
	"errors"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/ahurjui/usage-metering-sample/internal/store"
)

func record(id string) store.UsageRecord {
	return store.UsageRecord{
		ID:         id,
		CustomerID: "cust-1",
		Service:    "compute",
		CostCents:  100,
		PriceCents: 130,
		OccurredAt: time.Date(2026, 1, 15, 0, 0, 0, 0, time.UTC),
	}
}

// flakyStore fails the first n Insert calls per record with a transient error.
type flakyStore struct {
	inner    *store.Memory
	mu       sync.Mutex
	failures map[string]int
}

func (f *flakyStore) Insert(ctx context.Context, r store.UsageRecord) error {
	f.mu.Lock()
	remaining := f.failures[r.ID]
	if remaining > 0 {
		f.failures[r.ID] = remaining - 1
		f.mu.Unlock()
		return errors.New("transient: connection reset")
	}
	f.mu.Unlock()
	return f.inner.Insert(ctx, r)
}

func (f *flakyStore) ByCustomer(ctx context.Context, id string) ([]store.UsageRecord, error) {
	return f.inner.ByCustomer(ctx, id)
}

func newTestIngester(s store.Store) *Ingester {
	ing := New(s, Options{Workers: 4, MaxRetries: 3})
	ing.sleep = func(context.Context, time.Duration) error { return nil } // no real backoff in tests
	return ing
}

func TestRunValidation(t *testing.T) {
	missingID := record("")
	negative := record("neg")
	negative.CostCents = -5

	tests := []struct {
		name       string
		batch      []store.UsageRecord
		wantOK     int
		wantFailed int
	}{
		{"all valid", []store.UsageRecord{record("a"), record("b")}, 2, 0},
		{"missing id rejected", []store.UsageRecord{missingID, record("c")}, 1, 1},
		{"negative amount rejected", []store.UsageRecord{negative}, 0, 1},
		{"empty batch", nil, 0, 0},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ing := newTestIngester(store.NewMemory())
			res, err := ing.Run(context.Background(), tt.batch)
			if err != nil {
				t.Fatalf("Run: %v", err)
			}
			if res.Inserted != tt.wantOK || len(res.Failed) != tt.wantFailed {
				t.Errorf("got inserted=%d failed=%d, want %d/%d",
					res.Inserted, len(res.Failed), tt.wantOK, tt.wantFailed)
			}
		})
	}
}

func TestRunDeduplicates(t *testing.T) {
	ing := newTestIngester(store.NewMemory())

	// Same batch delivered twice — second delivery must be all duplicates.
	batch := []store.UsageRecord{record("a"), record("b"), record("c")}
	if _, err := ing.Run(context.Background(), batch); err != nil {
		t.Fatalf("first run: %v", err)
	}
	res, err := ing.Run(context.Background(), batch)
	if err != nil {
		t.Fatalf("second run: %v", err)
	}
	if res.Inserted != 0 || res.Duplicates != 3 || len(res.Failed) != 0 {
		t.Errorf("redelivery: got %+v, want 0 inserted / 3 duplicates / 0 failed", res)
	}
}

func TestRunRetriesTransientErrors(t *testing.T) {
	flaky := &flakyStore{
		inner:    store.NewMemory(),
		failures: map[string]int{"a": 2}, // fails twice, succeeds on third attempt
	}
	ing := newTestIngester(flaky)

	res, err := ing.Run(context.Background(), []store.UsageRecord{record("a")})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if res.Inserted != 1 || len(res.Failed) != 0 {
		t.Errorf("got %+v, want the record inserted after retries", res)
	}
}

func TestRunGivesUpAfterMaxRetries(t *testing.T) {
	flaky := &flakyStore{
		inner:    store.NewMemory(),
		failures: map[string]int{"a": 100}, // more failures than retries
	}
	ing := newTestIngester(flaky)

	res, err := ing.Run(context.Background(), []store.UsageRecord{record("a"), record("b")})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if res.Inserted != 1 || len(res.Failed) != 1 || res.Failed[0].ID != "a" {
		t.Errorf("got %+v, want b inserted and a failed", res)
	}
}

func TestRunStopsOnCancelledContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancelled before the batch is fed

	batch := make([]store.UsageRecord, 100)
	for i := range batch {
		batch[i] = record("r" + strconv.Itoa(i))
	}
	ing := newTestIngester(store.NewMemory())
	res, err := ing.Run(ctx, batch)
	if err == nil {
		t.Fatal("want error from cancelled context")
	}
	if res.Inserted == len(batch) {
		t.Error("cancelled run should not have completed the whole batch")
	}
}
