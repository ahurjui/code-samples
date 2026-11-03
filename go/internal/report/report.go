// Package report aggregates stored usage into per-customer margin summaries.
package report

import (
	"context"
	"fmt"
	"sort"

	"github.com/ahurjui/usage-metering-sample/internal/store"
)

// ServiceLine is the aggregated cost/revenue for one service.
type ServiceLine struct {
	Service      string `json:"service"`
	Records      int    `json:"records"`
	CostCents    int64  `json:"cost_cents"`
	RevenueCents int64  `json:"revenue_cents"`
	MarginCents  int64  `json:"margin_cents"`
	// MarginBps is the margin in basis points (1/100th of a percent).
	// Integer basis points instead of a float percentage: exact, sortable,
	// and safe to compare in tests.
	MarginBps int64 `json:"margin_bps"`
}

// Summary is the customer-level rollup returned by the API.
type Summary struct {
	CustomerID   string        `json:"customer_id"`
	Records      int           `json:"records"`
	CostCents    int64         `json:"cost_cents"`
	RevenueCents int64         `json:"revenue_cents"`
	MarginCents  int64         `json:"margin_cents"`
	MarginBps    int64         `json:"margin_bps"`
	Services     []ServiceLine `json:"services"`
}

// Build computes the margin summary for one customer.
func Build(ctx context.Context, s store.Store, customerID string) (Summary, error) {
	records, err := s.ByCustomer(ctx, customerID)
	if err != nil {
		return Summary{}, fmt.Errorf("loading usage for %q: %w", customerID, err)
	}

	sum := Summary{CustomerID: customerID}
	perService := make(map[string]*ServiceLine)
	for _, r := range records {
		line, ok := perService[r.Service]
		if !ok {
			line = &ServiceLine{Service: r.Service}
			perService[r.Service] = line
		}
		line.Records++
		line.CostCents += r.CostCents
		line.RevenueCents += r.PriceCents

		sum.Records++
		sum.CostCents += r.CostCents
		sum.RevenueCents += r.PriceCents
	}

	for _, line := range perService {
		line.MarginCents = line.RevenueCents - line.CostCents
		line.MarginBps = marginBps(line.RevenueCents, line.CostCents)
		sum.Services = append(sum.Services, *line)
	}
	sort.Slice(sum.Services, func(i, j int) bool {
		return sum.Services[i].Service < sum.Services[j].Service
	})

	sum.MarginCents = sum.RevenueCents - sum.CostCents
	sum.MarginBps = marginBps(sum.RevenueCents, sum.CostCents)
	return sum, nil
}

// marginBps returns (revenue-cost)/revenue in basis points, 0 for zero revenue.
func marginBps(revenue, cost int64) int64 {
	if revenue == 0 {
		return 0
	}
	return (revenue - cost) * 10_000 / revenue
}
