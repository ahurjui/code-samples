package report

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/ahurjui/usage-metering-sample/internal/store"
)

func seed(t *testing.T) *store.Memory {
	t.Helper()
	m := store.NewMemory()
	at := time.Date(2026, 1, 15, 0, 0, 0, 0, time.UTC)
	rows := []store.UsageRecord{
		{ID: "1", CustomerID: "acme", Service: "compute", CostCents: 8_000, PriceCents: 10_000, OccurredAt: at},
		{ID: "2", CustomerID: "acme", Service: "compute", CostCents: 2_000, PriceCents: 2_500, OccurredAt: at},
		{ID: "3", CustomerID: "acme", Service: "storage", CostCents: 900, PriceCents: 1_000, OccurredAt: at},
		{ID: "4", CustomerID: "other", Service: "compute", CostCents: 1, PriceCents: 2, OccurredAt: at},
	}
	for _, r := range rows {
		if err := m.Insert(context.Background(), r); err != nil {
			t.Fatalf("seed: %v", err)
		}
	}
	return m
}

func TestBuildAggregatesPerServiceAndTotal(t *testing.T) {
	sum, err := Build(context.Background(), seed(t), "acme")
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	if sum.Records != 3 || sum.CostCents != 10_900 || sum.RevenueCents != 13_500 {
		t.Errorf("totals: got %+v", sum)
	}
	if sum.MarginCents != 2_600 {
		t.Errorf("margin: got %d, want 2600", sum.MarginCents)
	}
	// 2600/13500 = 19.25..% -> 1925 bps, integer-truncated.
	if sum.MarginBps != 1925 {
		t.Errorf("margin bps: got %d, want 1925", sum.MarginBps)
	}

	if len(sum.Services) != 2 || sum.Services[0].Service != "compute" || sum.Services[1].Service != "storage" {
		t.Fatalf("services: got %+v, want sorted [compute storage]", sum.Services)
	}
	compute := sum.Services[0]
	if compute.Records != 2 || compute.MarginCents != 2_500 {
		t.Errorf("compute line: got %+v", compute)
	}
}

func TestBuildUnknownCustomer(t *testing.T) {
	_, err := Build(context.Background(), seed(t), "nobody")
	if !errors.Is(err, store.ErrNotFound) {
		t.Errorf("got %v, want store.ErrNotFound", err)
	}
}

func TestMarginBpsZeroRevenue(t *testing.T) {
	if got := marginBps(0, 500); got != 0 {
		t.Errorf("zero revenue must yield 0 bps, got %d", got)
	}
}
