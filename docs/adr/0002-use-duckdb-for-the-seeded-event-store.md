# ADR-0002: Use DuckDB for the seeded event store

- Status: Proposed
- Date: 2026-10-11
- Task: KAI-1
- Deciders: Vijay (to accept)

## Context

The brief allows DuckDB or PostgreSQL in Docker. The data is 20,000 users and 60 days of events, about 1 to 2 million rows, written once by the seeder and then only read. Queries are funnels, retention cohorts and grouped comparisons. Bearing's tech-decision catalogue defaults to Postgres for small analytics stores.

## Options considered

### Option A: DuckDB file, embedded in the service container
Columnar, fast group-by and window queries, no server to run, the file is built by the seeder at image build or start-up. Single writer only, which fits a read-only analytics workload.

### Option B: PostgreSQL 16 in Docker Compose
Matches the catalogue default and allows concurrent writers. Needs a second container, migrations and a connection pool; slower on wide aggregations at this size is not a concern, but operations are.

## Decision

We will use DuckDB, opened read-only by the analytics tools and read-write only by the seeder and the report store. Reasons: zero operations, fast analytical SQL, and the dataset is static.

## Consequences

- No Postgres, SQLAlchemy or Alembic in the service; the scaffold's database layer is removed.
- Reports are stored in a separate DuckDB file so the event store stays read-only.
- Revisit if events must be ingested live or several services write concurrently.
