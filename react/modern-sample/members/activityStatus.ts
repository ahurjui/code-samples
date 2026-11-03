import type { ActivityStatus } from './types';

/**
 * Day thresholds for each status band. Kept as data (not code) so an admin
 * screen can edit them; validated because they come from user input.
 */
export interface StatusThresholds {
  activeMaxDays: number; // last visit within N days => active
  coolingMaxDays: number; // within N days => cooling
  atRiskMaxDays: number; // within N days => at-risk; beyond => inactive
}

export const DEFAULT_THRESHOLDS: StatusThresholds = {
  activeMaxDays: 7,
  coolingMaxDays: 13,
  atRiskMaxDays: 20,
};

/** Throws if thresholds are not strictly increasing positive integers. */
export function validateThresholds(t: StatusThresholds): void {
  const values = [t.activeMaxDays, t.coolingMaxDays, t.atRiskMaxDays];
  if (values.some((v) => !Number.isInteger(v) || v <= 0)) {
    throw new Error('thresholds must be positive integers');
  }
  if (!(t.activeMaxDays < t.coolingMaxDays && t.coolingMaxDays < t.atRiskMaxDays)) {
    throw new Error('thresholds must be strictly increasing');
  }
}

/**
 * Whole days elapsed since the last visit, or null for "never visited".
 * `now` is a parameter so the function stays deterministic and testable.
 */
export function daysSince(lastVisitAt: string | null, now: Date): number | null {
  if (lastVisitAt === null) return null;
  const last = new Date(lastVisitAt);
  const ms = now.getTime() - last.getTime();
  if (ms < 0) return 0; // clock skew: a future visit date counts as today
  return Math.floor(ms / 86_400_000);
}

export function classify(
  daysSinceLastVisit: number | null,
  thresholds: StatusThresholds = DEFAULT_THRESHOLDS,
): ActivityStatus {
  validateThresholds(thresholds);
  if (daysSinceLastVisit === null) return 'inactive';
  if (daysSinceLastVisit <= thresholds.activeMaxDays) return 'active';
  if (daysSinceLastVisit <= thresholds.coolingMaxDays) return 'cooling';
  if (daysSinceLastVisit <= thresholds.atRiskMaxDays) return 'at-risk';
  return 'inactive';
}
