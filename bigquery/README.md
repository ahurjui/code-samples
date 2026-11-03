# BigQuery — reporting sample

My production BigQuery work is on a proprietary enterprise billing platform
(large-scale usage/cost pipelines and a templated reporting engine) that I
can't share code from. This sample was written to show the same skills on a
fictional billing domain — the same one as my Go sample in this collection.

| File | What it shows |
|---|---|
| `aws_credits_report.yaml` | A full enterprise-scale report definition over the public AWS CUR schema — the config-driven pattern I build professionally: sources/joins with engine-enforced partition filters and dedup, parameter catalog, a ~30-column catalog across identity/program/amounts/coverage/data-quality/audit groups, multiple UI views with grouping presets, drill-downs, scheduled exports, and row-level access control |
| `aws_credits_report.sql` | A credit-allocation report over the public AWS Cost & Usage Report (CUR) schema: credit vs. usage line-item semantics, sign handling for negative credit lines, NUMERIC money discipline, load-redelivery dedup, unmapped-account surfacing instead of silent row drops, coverage in basis points |
| `usage_margin_report.sql` | A production-shaped report query: partition pruning on both bounds, redelivery-safe dedup via `QUALIFY ROW_NUMBER()`, integer-cents money math, `SAFE_DIVIDE` guards, window function for revenue share |
| `report_template.yaml` | The config-driven pattern I use professionally: reports defined as validated YAML specs that an engine renders into BigQuery SQL — partition filters and dedup enforced by the engine, so no report can accidentally full-scan the table or double-count redelivered data |

The two habits this sample is really about: queries that are safe against the
data's failure modes (duplicates, zero denominators, late redelivery), and
cost discipline — every query prunes partitions, because on billing-scale
tables an unpruned query is real money.
