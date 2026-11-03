# Go — code sample

My production Go work is on a proprietary enterprise cloud-billing platform (gRPC services,
MySQL, BigQuery pipelines) that I can't share, so this is a small self-contained service I
wrote as a sample in the same domain: it ingests metered usage records and reports
per-customer profit margins.

It compiles and its tests pass (`go vet ./... && go test ./...`), uses only the standard
library, and is deliberately small — the point is style, not features.

| File | What it shows |
|---|---|
| `cmd/server/main.go` | Wiring, env config, graceful shutdown with bounded drain |
| `internal/store/store.go` | Repository interface + thread-safe in-memory implementation; storage-enforced idempotency |
| `internal/ingest/ingest.go` | Concurrent batch ingestion: worker pool, validation, retry with backoff + jitter, context cancellation |
| `internal/report/report.go` | Margin aggregation in integer cents / basis points — no float money math |
| `internal/api/api.go` | HTTP/JSON layer: DTO separation, body limits, error envelopes, partial-success responses |
| `internal/ingest/ingest_test.go` | Table-driven tests with failure injection: dedup, retries, give-up, cancellation |
| `internal/report/report_test.go` | Aggregation and margin math tests |

Run it:

```sh
go test ./...
go run ./cmd/server
curl -s localhost:8090/healthz -i | head -1
```
