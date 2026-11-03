// Package ingest validates and persists batches of usage records concurrently.
package ingest

import (
	"context"
	"errors"
	"fmt"
	"math/rand"
	"sync"
	"time"

	"github.com/ahurjui/usage-metering-sample/internal/store"
)

// Options tune ingestion behaviour; zero values fall back to safe defaults.
type Options struct {
	Workers    int           // concurrent insert workers (default 4)
	MaxRetries int           // retries per record on transient errors (default 3)
	BaseDelay  time.Duration // backoff base (default 50ms)
}

// Result summarises one batch: what was written, what was skipped, what failed.
// Duplicates are reported separately from errors — a redelivered batch is
// normal operation, not a failure.
type Result struct {
	Inserted   int
	Duplicates int
	Failed     []FailedRecord
}

// FailedRecord pairs a rejected record ID with the reason it was rejected.
type FailedRecord struct {
	ID  string
	Err string
}

// Ingester writes validated usage records to a Store using a worker pool.
type Ingester struct {
	store store.Store
	opts  Options
	// sleep is swapped out in tests so backoff paths run instantly.
	sleep func(context.Context, time.Duration) error
}

// New returns an Ingester writing to s.
func New(s store.Store, opts Options) *Ingester {
	if opts.Workers <= 0 {
		opts.Workers = 4
	}
	if opts.MaxRetries <= 0 {
		opts.MaxRetries = 3
	}
	if opts.BaseDelay <= 0 {
		opts.BaseDelay = 50 * time.Millisecond
	}
	return &Ingester{store: s, opts: opts, sleep: sleepCtx}
}

// Run ingests one batch. Records are validated up front; valid records are
// inserted concurrently. Run only returns an error when the context is
// cancelled — per-record problems are reported in Result so one bad record
// never discards the rest of the batch.
func (ing *Ingester) Run(ctx context.Context, batch []store.UsageRecord) (Result, error) {
	var (
		mu     sync.Mutex
		res    Result
		jobs   = make(chan store.UsageRecord)
		wg     sync.WaitGroup
	)

	for i := 0; i < ing.opts.Workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for r := range jobs {
				err := ing.insertWithRetry(ctx, r)
				mu.Lock()
				switch {
				case err == nil:
					res.Inserted++
				case errors.Is(err, store.ErrDuplicate):
					res.Duplicates++
				default:
					res.Failed = append(res.Failed, FailedRecord{ID: r.ID, Err: err.Error()})
				}
				mu.Unlock()
			}
		}()
	}

feed:
	for _, r := range batch {
		if err := validate(r); err != nil {
			mu.Lock()
			res.Failed = append(res.Failed, FailedRecord{ID: r.ID, Err: err.Error()})
			mu.Unlock()
			continue
		}
		select {
		case jobs <- r:
		case <-ctx.Done():
			break feed
		}
	}
	close(jobs)
	wg.Wait()

	if err := ctx.Err(); err != nil {
		return res, fmt.Errorf("ingest interrupted: %w", err)
	}
	return res, nil
}

// insertWithRetry retries transient store errors with exponential backoff and
// jitter. Duplicates are permanent by definition and returned immediately.
func (ing *Ingester) insertWithRetry(ctx context.Context, r store.UsageRecord) error {
	var lastErr error
	for attempt := 0; attempt <= ing.opts.MaxRetries; attempt++ {
		if attempt > 0 {
			delay := ing.opts.BaseDelay << (attempt - 1)
			delay += time.Duration(rand.Int63n(int64(delay) + 1))
			if err := ing.sleep(ctx, delay); err != nil {
				return err
			}
		}
		lastErr = ing.store.Insert(ctx, r)
		if lastErr == nil || errors.Is(lastErr, store.ErrDuplicate) || errors.Is(lastErr, context.Canceled) {
			return lastErr
		}
	}
	return fmt.Errorf("after %d attempts: %w", ing.opts.MaxRetries+1, lastErr)
}

func validate(r store.UsageRecord) error {
	switch {
	case r.ID == "":
		return errors.New("missing record id")
	case r.CustomerID == "":
		return errors.New("missing customer id")
	case r.Service == "":
		return errors.New("missing service")
	case r.CostCents < 0 || r.PriceCents < 0:
		return errors.New("negative amounts not allowed; issue credits instead")
	case r.OccurredAt.IsZero():
		return errors.New("missing occurred_at")
	}
	return nil
}

func sleepCtx(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-t.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
