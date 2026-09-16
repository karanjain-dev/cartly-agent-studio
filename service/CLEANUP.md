# Retired architecture cleanup

Production now uses one shared PostgreSQL dataset. API, website and terminal resolve the same dataset ID; startup does not create a redundant base copy.

| Record | Before | After cleanup |
| --- | ---: | ---: |
| worlds | 27 | 1 |
| users | 1478 | 74 |
| orders | 4582 | 266 |
| order_items | 4717 | 271 |
| refunds | 1081 | 40 |
| returns | 326 | 12 |
| sessions | 29 | 4 |

Counts above are the cleanup snapshot; normal use can add sessions and actions afterward.

## Verification

- A full logical production backup was restored into a separate local PostgreSQL schema; every dataset audit chain passed.
- The cleanup transaction checked that the entire retained dataset and all budget/reservation records remained unchanged.
- Live post-cleanup checks confirmed one dataset, 74 customers, 266 orders, valid audit history and an enabled immutable-audit trigger.
- 62 service tests and the website proxy checks passed; production frontend build passed.
- The API and website now accept the same session against the shared dataset.
- Database access for maintenance used a temporary explicitly approved SSH key.

## Removed

- 26 retired database copies and their old sessions/messages/proposals/audits, retained only in the private backup.
- Website D1 database bindings, SQLite schema/migrations, example endpoints and Drizzle dependencies.
- The obsolete ignored local deployment source copy.

## Retained

- Current shared records, including the 20 added customers and 100 added orders.
- All API spending and reservation records.
- Frozen eval data, scenarios, transcripts and historical results; these are test assets, not live customer duplicates.
- Existing SQL migration history and relational constraints. Dataset IDs remain useful for isolated tests; the production database contains only one dataset.

Private backups and detailed cleanup manifests live in the ignored `.cartly-service/backups/` directory and are never pushed to GitHub.
