import type { ActivityStatus } from './types';

const LABELS: Record<ActivityStatus, string> = {
  active: 'Active',
  cooling: 'Cooling off',
  'at-risk': 'At risk',
  inactive: 'Inactive',
};

/** Colored pill for a member's activity status; color comes from CSS. */
export function StatusBadge({ status }: { status: ActivityStatus }) {
  return <span className={`status-badge status-badge--${status}`}>{LABELS[status]}</span>;
}
