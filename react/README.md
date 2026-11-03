# React — code samples

Two parts:

## `production-excerpt/` — from a live project

A reusable dropdown from the React front end of a travel-booking marketplace I co-founded,
in production since 2020. It shows the compound-component pattern (`Dropdown.Trigger` / `Dropdown.Content`),
outside-click handling with cleanup, and PropTypes validation — written in the React 16 era,
included unmodified as a genuine production artifact.

## `modern-sample/` — current-style React + TypeScript

A small self-contained feature (a member-activity table with traffic-light status) written
as a sample to show how I build React today. It typechecks under `tsc --strict` and its
tests pass (18 tests, Vitest).

| File | What it shows |
|---|---|
| `api/client.ts` | Typed fetch wrapper with structured errors and abort support |
| `members/types.ts` | Domain types kept separate from components |
| `members/activityStatus.ts` | Pure, configurable classification logic — data-driven thresholds, validated because they're user-editable |
| `members/activityStatus.test.ts` | Table-driven unit tests incl. boundary values and clock-skew edge case |
| `members/useMembers.ts` | Custom data-fetching hook: loading/error state, refresh, stale-response protection via AbortController |
| `members/MemberTable.tsx` | Feature component: search, loading/error/empty states, memoized derived rows, accessible roles |
| `members/StatusBadge.tsx` | Small presentational component |

The split reflects how I work: components stay thin, business rules live in pure,
unit-tested modules, and API access is isolated behind a typed client.
