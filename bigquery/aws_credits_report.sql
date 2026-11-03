-- AWS credit allocation report over the AWS Cost & Usage Report (CUR 2.0).
--
-- Source: the standard CUR export loaded into BigQuery, using AWS's public
-- column naming (athena-style snake_case). Assumed layout:
--   aws_billing.cur_line_items   partitioned by DATE(bill_billing_period_start_date),
--                                clustered by line_item_usage_account_id
--   aws_billing.account_map      payer-account hierarchy: account id -> customer
--
-- What it answers, per customer and billing month:
--   how much AWS credit landed on their accounts, against which services,
--   what their gross usage was, and the effective net position — the numbers
--   a reseller reconciles before invoicing.

DECLARE billing_period DATE DEFAULT DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH);

WITH line_items AS (
  SELECT
    line_item_usage_account_id                       AS account_id,
    line_item_line_item_type                         AS line_type,
    product_product_name                             AS service,
    line_item_line_item_description                  AS description,
    -- CUR amounts arrive as high-precision decimals; keep NUMERIC end to end
    -- and round once at presentation. Never SUM(FLOAT64) on money.
    CAST(line_item_unblended_cost AS NUMERIC)        AS unblended_cost,
    DATE(bill_billing_period_start_date)             AS period_start
  FROM `aws_billing.cur_line_items`
  -- Partition pruning: exactly one billing period, both bounds explicit.
  WHERE DATE(bill_billing_period_start_date) = billing_period
    -- Credits and the usage they offset; refunds handled separately on
    -- purpose — mixing RIFee/Refund/Tax into a credit report is how numbers
    -- stop matching the AWS invoice.
    AND line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'Credit')
),

-- CUR files are delivered cumulatively and re-delivered within the month;
-- if the load pipeline appends versions, the same period exists more than
-- once. Keep the latest load per period. (With a replace-on-load pipeline
-- this CTE is a no-op — it guards the assumption instead of trusting it.)
latest_load AS (
  SELECT *
  FROM (
    SELECT li.*, l.loaded_at,
           ROW_NUMBER() OVER (PARTITION BY li.account_id, li.period_start
                              ORDER BY l.loaded_at DESC) AS load_rank
    FROM line_items li
    JOIN `aws_billing.load_manifest` l USING (period_start)
  )
  WHERE load_rank = 1
),

per_account AS (
  SELECT
    account_id,
    service,
    -- Credits arrive as negative line items in CUR; flip the sign so the
    -- report reads "credit received" as a positive amount.
    SUM(IF(line_type = 'Credit', -unblended_cost, 0))                     AS credit_amount,
    SUM(IF(line_type IN ('Usage', 'DiscountedUsage'), unblended_cost, 0)) AS gross_usage,
    COUNTIF(line_type = 'Credit')                                         AS credit_lines,
    -- Distinct credit programs hitting this account/service, for the
    -- drill-down view ("which promotion was this?").
    ARRAY_AGG(DISTINCT IF(line_type = 'Credit', description, NULL) IGNORE NULLS
              ORDER BY IF(line_type = 'Credit', description, NULL) LIMIT 10) AS credit_programs
  FROM latest_load
  GROUP BY account_id, service
),

with_customer AS (
  SELECT
    m.customer_id,
    m.customer_name,
    p.*
  FROM per_account p
  -- LEFT JOIN deliberately: an account missing from the hierarchy map is a
  -- data problem to surface in the report, not a row to silently drop.
  LEFT JOIN `aws_billing.account_map` m ON m.account_id = p.account_id
)

SELECT
  COALESCE(customer_name, CONCAT('UNMAPPED ACCOUNT ', account_id)) AS customer,
  account_id,
  service,
  credit_lines,
  ROUND(credit_amount, 2)                    AS credit_amount,
  ROUND(gross_usage, 2)                      AS gross_usage,
  ROUND(gross_usage - credit_amount, 2)      AS net_position,
  -- Credit coverage of usage, in basis points; SAFE_DIVIDE so zero-usage
  -- accounts (credit-only months exist) return NULL, not an error.
  CAST(SAFE_DIVIDE(credit_amount * 10000, gross_usage) AS INT64) AS coverage_bps,
  credit_programs,
  billing_period
FROM with_customer
WHERE credit_amount != 0 OR gross_usage != 0
ORDER BY customer, credit_amount DESC;
