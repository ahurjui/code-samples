import { describe, expect, it } from 'vitest';

import { classify, daysSince, DEFAULT_THRESHOLDS, validateThresholds } from './activityStatus';

describe('classify', () => {
  const cases: Array<[number | null, string]> = [
    [0, 'active'],
    [7, 'active'], // boundary: exactly activeMaxDays
    [8, 'cooling'],
    [13, 'cooling'], // boundary
    [14, 'at-risk'],
    [20, 'at-risk'], // boundary
    [21, 'inactive'],
    [365, 'inactive'],
    [null, 'inactive'], // never visited
  ];

  it.each(cases)('classifies %s days as %s', (days, expected) => {
    expect(classify(days)).toBe(expected);
  });

  it('respects custom thresholds', () => {
    const tight = { activeMaxDays: 2, coolingMaxDays: 4, atRiskMaxDays: 6 };
    expect(classify(3, tight)).toBe('cooling');
    expect(classify(7, tight)).toBe('inactive');
  });
});

describe('validateThresholds', () => {
  it('accepts the defaults', () => {
    expect(() => validateThresholds(DEFAULT_THRESHOLDS)).not.toThrow();
  });

  it.each([
    [{ activeMaxDays: 0, coolingMaxDays: 13, atRiskMaxDays: 20 }, 'zero value'],
    [{ activeMaxDays: 7.5, coolingMaxDays: 13, atRiskMaxDays: 20 }, 'non-integer'],
    [{ activeMaxDays: 13, coolingMaxDays: 13, atRiskMaxDays: 20 }, 'not increasing (equal)'],
    [{ activeMaxDays: 20, coolingMaxDays: 13, atRiskMaxDays: 7 }, 'descending'],
  ])('rejects %j (%s)', (thresholds) => {
    expect(() => validateThresholds(thresholds)).toThrow();
  });
});

describe('daysSince', () => {
  const now = new Date('2026-08-05T12:00:00Z');

  it('returns null for a member who never visited', () => {
    expect(daysSince(null, now)).toBeNull();
  });

  it('counts whole elapsed days', () => {
    expect(daysSince('2026-08-05T09:00:00Z', now)).toBe(0);
    expect(daysSince('2026-08-04T11:00:00Z', now)).toBe(1);
    expect(daysSince('2026-07-06T12:00:00Z', now)).toBe(30);
  });

  it('clamps future dates to today instead of going negative', () => {
    expect(daysSince('2026-08-06T00:00:00Z', now)).toBe(0);
  });
});
