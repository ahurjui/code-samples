// Package api exposes ingestion and reporting over HTTP/JSON.
package api

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/ahurjui/usage-metering-sample/internal/ingest"
	"github.com/ahurjui/usage-metering-sample/internal/report"
	"github.com/ahurjui/usage-metering-sample/internal/store"
)

const maxBodyBytes = 1 << 20 // 1 MiB: a batch endpoint is not a file upload

// Server wires the HTTP layer to ingestion and reporting.
type Server struct {
	store    store.Store
	ingester *ingest.Ingester
	log      *slog.Logger
}

// NewServer returns a Server backed by s.
func NewServer(s store.Store, ing *ingest.Ingester, log *slog.Logger) *Server {
	return &Server{store: s, ingester: ing, log: log}
}

// Routes registers all endpoints on a fresh mux.
func (s *Server) Routes() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/usage", s.handleIngest)
	mux.HandleFunc("GET /v1/customers/{id}/summary", s.handleSummary)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	})
	return mux
}

// usageRecordDTO is the wire format; it is deliberately separate from the
// storage type so the API contract can evolve independently of persistence.
type usageRecordDTO struct {
	ID         string    `json:"id"`
	CustomerID string    `json:"customer_id"`
	Service    string    `json:"service"`
	CostCents  int64     `json:"cost_cents"`
	PriceCents int64     `json:"price_cents"`
	OccurredAt time.Time `json:"occurred_at"`
}

func (s *Server) handleIngest(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)

	var payload struct {
		Records []usageRecordDTO `json:"records"`
	}
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&payload); err != nil {
		s.writeError(w, http.StatusBadRequest, "invalid JSON body: "+err.Error())
		return
	}
	if len(payload.Records) == 0 {
		s.writeError(w, http.StatusBadRequest, "records must not be empty")
		return
	}

	batch := make([]store.UsageRecord, 0, len(payload.Records))
	for _, dto := range payload.Records {
		batch = append(batch, store.UsageRecord{
			ID:         dto.ID,
			CustomerID: dto.CustomerID,
			Service:    dto.Service,
			CostCents:  dto.CostCents,
			PriceCents: dto.PriceCents,
			OccurredAt: dto.OccurredAt,
		})
	}

	result, err := s.ingester.Run(r.Context(), batch)
	if err != nil {
		// Client went away mid-batch; the partial result is logged for ops
		// but there is no one left to answer.
		s.log.Warn("ingest interrupted", "error", err, "inserted", result.Inserted)
		return
	}

	status := http.StatusOK
	if len(result.Failed) > 0 {
		status = http.StatusMultiStatus
	}
	s.writeJSON(w, status, result)
}

func (s *Server) handleSummary(w http.ResponseWriter, r *http.Request) {
	customerID := r.PathValue("id")
	summary, err := report.Build(r.Context(), s.store, customerID)
	switch {
	case errors.Is(err, store.ErrNotFound):
		s.writeError(w, http.StatusNotFound, "no usage recorded for customer "+customerID)
	case err != nil:
		s.log.Error("building summary", "customer", customerID, "error", err)
		s.writeError(w, http.StatusInternalServerError, "internal error")
	default:
		s.writeJSON(w, http.StatusOK, summary)
	}
}

func (s *Server) writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		s.log.Error("encoding response", "error", err)
	}
}

func (s *Server) writeError(w http.ResponseWriter, status int, msg string) {
	s.writeJSON(w, status, map[string]string{"error": msg})
}
