-- Monthly per-customer margin report over metered usage.
--
-- Assumed layout (BigQuery):
--   billing_demo.usage_events
--     partitioned by DATE(occurred_at), clustered by customer_id
--     one row per metered usage record; ingestion may re-deliver batches,
--     so the same record_id can appear more than once with different
--     ingested_at timestamps. Amounts are integer cents — no float money.

DECLARE report_month DATE DEFAULT DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH);

WITH deduped AS (
  SELECT
    record_id,
    customer_id,
    service,
    cost_cents,
    price_cents,
    occurred_at
  FROM `billing_demo.usage_events`
  -- Both bounds hit the partition column directly: BigQuery prunes to one
  -- month of partitions instead of scanning the table's full history.
  WHERE DATE(occurred_at) >= report_month
    AND DATE(occurred_at) < DATE_ADD(report_month, INTERVAL 1 MONTH)
  -- Redelivered batches must never double-bill: keep only the latest
  -- ingested copy of each record.
  QUALIFY ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY ingested_at DESC) = 1
),

per_service AS (
  SELECT
    customer_id,
    service,
    COUNT(*)          AS records,
    SUM(cost_cents)   AS cost_cents,
    SUM(price_cents)  AS revenue_cents
  FROM deduped
  GROUP BY customer_id, service
)

SELECT
  customer_id,
  service,
  records,
  cost_cents,
  revenue_cents,
  revenue_cents - cost_cents AS margin_cents,
  -- Margin in basis points, integer math end to end. SAFE_DIVIDE instead of
  -- "/" so a zero-revenue service yields NULL rather than failing the job.
  CAST(SAFE_DIVIDE((revenue_cents - cost_cents) * 10000, revenue_cents) AS INT64) AS margin_bps,
  -- Each service's share of the customer's total revenue, for ranking which
  -- services actually drive the account.
  ROUND(SAFE_DIVIDE(revenue_cents, SUM(revenue_cents) OVER (PARTITION BY customer_id)), 4) AS revenue_share,
  report_month
FROM per_service
ORDER BY customer_id, revenue_cents DESC;
