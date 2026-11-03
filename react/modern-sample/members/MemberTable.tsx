import { useMemo, useState } from 'react';

import { classify, daysSince } from './activityStatus';
import { StatusBadge } from './StatusBadge';
import type { Member } from './types';
import { useMembers } from './useMembers';

interface Row extends Member {
  daysSinceLastVisit: number | null;
  status: ReturnType<typeof classify>;
}

/**
 * Member activity table: search, loading/error/empty states, and a
 * per-member status badge. Derived rows are memoized; classification is
 * pure and lives in activityStatus.ts where it is unit-tested.
 */
export function MemberTable({ now = new Date() }: { now?: Date }) {
  const { members, loading, error, refresh } = useMembers();
  const [query, setQuery] = useState('');

  const rows: Row[] = useMemo(() => {
    const q = query.trim().toLowerCase();
    return members
      .filter((m) => q === '' || m.name.toLowerCase().includes(q))
      .map((m) => {
        const days = daysSince(m.lastVisitAt, now);
        return { ...m, daysSinceLastVisit: days, status: classify(days) };
      });
  }, [members, query, now]);

  if (loading) return <p role="status">Loading members…</p>;
  if (error) {
    return (
      <div role="alert">
        <p>{error}</p>
        <button onClick={refresh}>Try again</button>
      </div>
    );
  }
  if (members.length === 0) return <p>No members yet.</p>;

  return (
    <section>
      <input
        type="search"
        placeholder="Search members…"
        aria-label="Search members"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {rows.length === 0 ? (
        <p>No members match “{query}”.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Membership</th>
              <th>Last visit</th>
              <th>30-day visits</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.name}</td>
                <td>{row.membershipType}</td>
                <td>
                  {row.daysSinceLastVisit === null
                    ? 'Never'
                    : `${row.daysSinceLastVisit} day(s) ago`}
                </td>
                <td>{row.visitsLast30Days}</td>
                <td>
                  <StatusBadge status={row.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
