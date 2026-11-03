export interface Member {
  id: string;
  name: string;
  membershipType: string;
  joinedAt: string; // ISO date
  lastVisitAt: string | null; // null = never visited
  visitsLast30Days: number;
}

export type ActivityStatus = 'active' | 'cooling' | 'at-risk' | 'inactive';
