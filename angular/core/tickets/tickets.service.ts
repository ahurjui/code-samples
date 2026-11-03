/**
 * `TicketsService` — HTTP facade for the read-only tickets
 * endpoints shipped in Layer 3c-c.
 *
 * docs-ref: docs/modules/betting/football/tickets-ui.md#ticketsservice-frontend
 */

import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AuthError } from '../auth/models';
import type { LegKeyFactor } from '../legs/legs.model';
import { TicketDiagnosis } from './ticket-diagnosis.service';

export type { LegKeyFactor } from '../legs/legs.model';

export interface TicketLegSummary {
  home_team: string | null;
  away_team: string | null;
  kickoff: string | null;
  market: string | null;
  outcome: string | null;
}

export interface TicketListItem {
  id: number;
  status: string;
  combined_odds: string;
  created_at: string;
  resolved_at: string | null;
  feeling_score: number | null;
  feeling_recommendation: TicketFeelingRecommendation | null;
  leg_count: number;
  warning_count: number;
  strategy_name: string | null;
  strategy_version: string | null;
  return_multiplier: number | null;
  legs_summary: TicketLegSummary[];
}

export interface TicketTotals {
  won_multiplier_sum: number;
  lost_multiplier_sum: number;
  settled_count: number;
  total_count: number;
}

export interface TicketListResponse {
  items: TicketListItem[];
  total: number;
  totals?: TicketTotals | null;
}

export interface LegResult {
  status: string;
  actual_result: string;
}

export interface TicketLeg {
  match_id?: string;
  home_team?: string;
  away_team?: string;
  league?: string;
  kickoff?: string;
  market?: string;
  outcome?: string;
  odds?: string;
  confidence_percent?: number;
  result?: LegResult;
  /** Fair probability expressed as a percentage (0–100), before bookmaker margin. */
  fair_prob_percent?: number;
  /** Calibrated probability expressed as a percentage (0–100), or null if unavailable. */
  calibrated_prob_percent?: number | null;
  /** Qualitative strength of the betting edge. */
  edge_strength?: 'weak' | 'medium' | 'strong';
  /** Data quality score (0–100): completeness and freshness of input data. Produced only by llm_book_grounded strategy. */
  data_quality_score?: number;
  /** Signal quality score (0–100): LLM-assessed quality of the analytical signal. Produced only by llm_book_grounded strategy. */
  signal_quality_score?: number;
  /** Edge trustworthiness score (0–100): LLM confidence in the edge being real. Produced only by llm_book_grounded strategy. */
  edge_trustworthiness_score?: number;
  /** Composite confidence score (0–1) combining all sub-scores. */
  confidence_score?: number;
  /** Key factors identified during analysis, ordered by sequence_index. */
  key_factors?: LegKeyFactor[];
  /** Mean fair probability across all contributing strategies (0–1). */
  consensus_prob_mean?: number | null;
  /** Standard deviation of fair probability across contributing strategies (0–1). */
  consensus_prob_stdev?: number | null;
  /** Number of strategies that contributed to this consensus entry. */
  consensus_strategy_count?: number | null;
  /** Biggest win/loss streak this season (#350). */
  home_biggest_win_streak?: number | null;
  home_biggest_loss_streak?: number | null;
  away_biggest_win_streak?: number | null;
  away_biggest_loss_streak?: number | null;
  /** Penalty conversion %, 0–100 (#350). */
  home_penalty_scored_pct?: number | null;
  home_penalty_commited_pct?: number | null;
  away_penalty_scored_pct?: number | null;
  away_penalty_commited_pct?: number | null;
  /** Standings description e.g. "Promotion - Champions League" (#350). */
  home_standing_description?: string | null;
  away_standing_description?: string | null;
  /** Goals scored/conceded per 15-min bucket (#350). */
  home_goals_per_bucket?: Record<string, { for: number; against: number }> | null;
  away_goals_per_bucket?: Record<string, { for: number; against: number }> | null;
  /** Most-played lineups by appearance count (#350). */
  home_most_played_lineups?: Array<{
    formation?: string;
    players?: string[];
    appearances?: number;
  }> | null;
  away_most_played_lineups?: Array<{
    formation?: string;
    players?: string[];
    appearances?: number;
  }> | null;
  [key: string]: unknown;
}

export interface TicketWarning {
  code?: string;
  i18n_key?: string;
  severity?: string;
  message?: string;
  [key: string]: unknown;
}

export type TicketFeelingRecommendation = 'bet' | 'lean_bet' | 'no_bet';

export interface TicketFeelingKeyFactor {
  factor: string;
  impact: 'positive' | 'negative' | 'mixed';
  detail?: string | null;
}

export interface TicketFeeling {
  score?: number;
  confidence?: 'low' | 'medium' | 'high';
  summary?: string;
  key_factors?: TicketFeelingKeyFactor[];
  recommendation?: TicketFeelingRecommendation;
  rationale?: string;
  [key: string]: unknown;
}

export interface TicketDetail {
  id: number;
  status: string;
  combined_odds: string;
  created_at: string;
  resolved_at: string | null;
  legs: TicketLeg[];
  warnings: TicketWarning[];
  feeling: TicketFeeling | null;
  diagnosis: TicketDiagnosis | null;
  /** Strategy that generated this ticket. Used to gate quality-score columns (only llm_book_grounded populates them). */
  strategy_name: string | null;
  /** Version snapshot of the strategy at composition time (e.g. "1.0.0"). */
  strategy_version: string | null;
}

export interface ListParams {
  limit?: number;
  offset?: number;
  dateFrom?: string;
  dateTo?: string;
  sortBy?: string;
  sortDir?: 'asc' | 'desc';
  status?: string;
  strategy?: string;
  /** Filter to tickets with feeling_json.recommendation matching one of "bet" | "lean_bet" | "no_bet". */
  recommendation?: string;
}

@Injectable({ providedIn: 'root' })
export class TicketsService {
  private readonly http = inject(HttpClient);

  async list(params: ListParams = {}): Promise<TicketListResponse> {
    let httpParams = new HttpParams();
    if (params.limit != null) {
      httpParams = httpParams.set('limit', String(params.limit));
    }
    if (params.offset != null) {
      httpParams = httpParams.set('offset', String(params.offset));
    }
    if (params.dateFrom != null) {
      httpParams = httpParams.set('date_from', params.dateFrom);
    }
    if (params.dateTo != null) {
      httpParams = httpParams.set('date_to', params.dateTo);
    }
    if (params.sortBy != null) {
      httpParams = httpParams.set('sort_by', params.sortBy);
    }
    if (params.sortDir != null) {
      httpParams = httpParams.set('sort_dir', params.sortDir);
    }
    if (params.status != null) {
      httpParams = httpParams.set('status', params.status);
    }
    if (params.strategy != null) {
      httpParams = httpParams.set('strategy', params.strategy);
    }
    if (params.recommendation != null) {
      httpParams = httpParams.set('recommendation', params.recommendation);
    }
    try {
      return await firstValueFrom(
        this.http.get<TicketListResponse>('/api/betting/football/tickets', {
          params: httpParams,
        }),
      );
    } catch (err) {
      throw toAuthError(err);
    }
  }

  async get(ticketId: number): Promise<TicketDetail> {
    try {
      return await firstValueFrom(
        this.http.get<TicketDetail>(`/api/betting/football/tickets/${ticketId}`),
      );
    } catch (err) {
      throw toAuthError(err);
    }
  }
}

function toAuthError(err: unknown): AuthError {
  if (err instanceof HttpErrorResponse) {
    const code = err.error?.detail?.code ?? 'error.auth.unexpected';
    return new AuthError(code, err.status, err.message);
  }
  return new AuthError('error.auth.unexpected', 0, String(err));
}
