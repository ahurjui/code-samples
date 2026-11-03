/**
 * `TicketsListComponent` — newest-first paginated grid of the
 * authenticated user's tickets, with date filter, column sort,
 * P/L summary strip, page-size selector, and prev/next pagination.
 *
 * Filter state (date, status, sort, page, page-size) is persisted in
 * the URL as query params so Back navigation restores the exact view.
 *
 * docs-ref: docs/modules/betting/football/tickets-ui.md#list
 */

import { CommonModule, DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

import { AuthError } from '../../../core/auth/models';
import { messageFor } from '../../../core/i18n/error-codes';
import { bucharestToday } from '../../../core/util/bucharest-date';
import { StrategySettingsService } from '../../../core/settings/strategy-settings.service';
import {
  feelingRecommendationBadgeClass,
  feelingRecommendationLabelKey,
} from '../../../core/tickets/feeling-recommendation';
import {
  TicketListItem,
  TicketTotals,
  TicketsService,
} from '../../../core/tickets/tickets.service';
import { TicketStatusBadgeComponent } from '../../../shared/ticket-status-badge/ticket-status-badge.component';
import { HlmButtonDirective } from '../../../shared/ui/button/hlm-button.directive';
import { HlmInputDirective } from '../../../shared/ui/input/hlm-input.directive';
import { HlmLabelDirective } from '../../../shared/ui/label/hlm-label.directive';
import { HlmCardImports } from '../../../shared/ui/card/index';
import { HlmTableImports } from '../../../shared/ui/table/index';
import { HlmDropdownMenuImports } from '../../../shared/ui/dropdown-menu/index';
import { PageHeaderComponent } from '../../../shared/layout/page-header.component';
import { MarketLabelPipe, OutcomeLabelPipe, StrategyLabelPipe } from '../../../shared/pipes/index';
import { DayNavComponent } from '../../../shared/ui/day-nav/day-nav.component';

const PAGE_SIZES = [10, 25, 50, 100] as const;
const STAKE_KEY = 'tickets.pl.stake';
const DEFAULT_STAKE = 10;
const DEFAULT_PAGE_SIZE = 25;
const VALID_SORT_COLS = [
  'created_at',
  'resolved_at',
  'combined_odds',
  'status',
  'legs_count',
  'warnings_count',
  'feeling_score',
  'feeling_recommendation',
  'strategy',
] as const;

type SortCol = (typeof VALID_SORT_COLS)[number];
type SortDir = 'asc' | 'desc';

@Component({
  selector: 'app-tickets-list',
  imports: [
    CommonModule,
    DatePipe,
    DecimalPipe,
    FormsModule,
    RouterLink,
    TranslateModule,
    TicketStatusBadgeComponent,
    HlmButtonDirective,
    HlmInputDirective,
    HlmLabelDirective,
    ...HlmCardImports,
    ...HlmTableImports,
    ...HlmDropdownMenuImports,
    PageHeaderComponent,
    StrategyLabelPipe,
    MarketLabelPipe,
    OutcomeLabelPipe,
    DayNavComponent,
  ],
  templateUrl: './tickets-list.component.html',
  styleUrls: ['./tickets-list.component.scss'],
})
export class TicketsListComponent implements OnInit {
  private readonly service = inject(TicketsService);
  private readonly strategyService = inject(StrategySettingsService);
  private readonly translate = inject(TranslateService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly pageSizes = PAGE_SIZES;
  protected readonly feelingRecommendationBadgeClass = feelingRecommendationBadgeClass;
  protected readonly feelingRecommendationLabelKey = feelingRecommendationLabelKey;
  readonly loading = signal(true);
  readonly rows = signal<TicketListItem[]>([]);
  readonly allStrategyNames = signal<string[]>([]);
  readonly total = signal(0);
  readonly error = signal<string | null>(null);

  readonly dateFilter = signal<string>('');
  readonly statusFilter = signal<string>('');
  readonly strategyFilter = signal<string>('');
  readonly recommendationFilter = signal<string>('');
  readonly sortBy = signal<SortCol>('created_at');
  readonly sortDir = signal<SortDir>('desc');
  readonly stake = signal<number>(this.loadStake());
  readonly pageSize = signal<number>(DEFAULT_PAGE_SIZE);
  readonly currentPage = signal<number>(1);

  readonly selectedIds = signal<Set<number>>(new Set());
  readonly allSelected = computed(() => {
    const rows = this.rows();
    return rows.length > 0 && rows.every((r) => this.selectedIds().has(r.id));
  });

  readonly totals = signal<TicketTotals | null>(null);

  readonly pl = computed(() => {
    let won = 0;
    let lost = 0;
    const s = this.stake();
    for (const row of this.rows()) {
      const m = row.return_multiplier;
      if (m == null) continue; // unresolved or pending — skip
      const pnl = s * (m - 1);
      if (pnl > 0) won += pnl;
      else if (pnl < 0) lost += -pnl;
    }
    return { won, lost, net: won - lost };
  });

  readonly allPl = computed(() => {
    const t = this.totals();
    const s = this.stake();
    if (!t) return { won: 0, lost: 0, net: 0, settled: 0, total: 0 };
    const won = s * t.won_multiplier_sum;
    const lost = s * t.lost_multiplier_sum;
    return { won, lost, net: won - lost, settled: t.settled_count, total: t.total_count };
  });

  readonly queryParams = computed(() => this.buildQueryParams());

  get totalPages(): number {
    return Math.ceil(this.total() / this.pageSize()) || 1;
  }

  async ngOnInit(): Promise<void> {
    const params = this.route.snapshot.queryParamMap;

    const dateParam = params.get('date');
    if (dateParam && /^\d{4}-\d{2}-\d{2}$/.test(dateParam)) {
      this.dateFilter.set(dateParam);
    } else {
      // docs-ref: docs/modules/betting/football/tickets-ui.md#rule-list-defaults-to-today
      this.dateFilter.set(bucharestToday());
    }

    const statusParam = params.get('status');
    if (statusParam && /^(PENDING|WON|LOST|VOID|PARTIAL|ERROR)$/.test(statusParam)) {
      this.statusFilter.set(statusParam);
    }

    const strategyParam = params.get('strategy');
    if (strategyParam) {
      this.strategyFilter.set(strategyParam);
    }

    const recommendationParam = params.get('recommendation');
    if (recommendationParam && /^(bet|lean_bet|no_bet)$/.test(recommendationParam)) {
      this.recommendationFilter.set(recommendationParam);
    }

    const sortByParam = params.get('sort_by');
    if (sortByParam && (VALID_SORT_COLS as readonly string[]).includes(sortByParam)) {
      this.sortBy.set(sortByParam as SortCol);
    }

    const sortDirParam = params.get('sort_dir');
    if (sortDirParam === 'asc' || sortDirParam === 'desc') {
      this.sortDir.set(sortDirParam);
    }

    const pageParam = params.get('page');
    if (pageParam && Number.isInteger(+pageParam) && +pageParam > 0) {
      this.currentPage.set(+pageParam);
    }

    const pageSizeParam = params.get('page_size');
    if (pageSizeParam && (PAGE_SIZES as readonly number[]).includes(+pageSizeParam)) {
      this.pageSize.set(+pageSizeParam);
    }

    // Fetch all registered strategy names for the filter dropdown.
    try {
      const settings = await this.strategyService.get();
      this.allStrategyNames.set(settings.strategies.map((s) => s.name));
    } catch {
      // Non-fatal — filter dropdown just won't show strategy options.
    }

    await this.loadPage(this.currentPage());
  }

  async applyFilters(): Promise<void> {
    this.loading.set(true);
    this.currentPage.set(1);
    this.syncUrl();
    await this.loadPage(1);
  }

  sort(col: SortCol): void {
    if (this.sortBy() === col) {
      this.sortDir.update((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      this.sortBy.set(col);
      this.sortDir.set('desc');
    }
    void this.applyFilters();
  }

  async goToPage(page: number): Promise<void> {
    if (page < 1 || page > this.totalPages) return;
    this.loading.set(true);
    this.currentPage.set(page);
    this.syncUrl();
    await this.loadPage(page);
  }

  async onPageSizeChange(size: number): Promise<void> {
    this.pageSize.set(size);
    await this.applyFilters();
  }

  onStakeChange(value: number): void {
    const safe = Math.max(1, Math.round(value));
    this.stake.set(safe);
    localStorage.setItem(STAKE_KEY, String(safe));
  }

  toggleSelectAll(): void {
    const rows = this.rows();
    if (this.allSelected()) {
      this.selectedIds.set(new Set());
    } else {
      this.selectedIds.set(new Set(rows.map((r) => r.id)));
    }
  }

  toggleRow(id: number): void {
    this.selectedIds.update((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  sortIcon(col: SortCol): string {
    if (this.sortBy() !== col) return '';
    return this.sortDir() === 'asc' ? ' ↑' : ' ↓';
  }

  buildQueryParams(): Record<string, string | number | null> {
    return {
      date: this.dateFilter() || null,
      status: this.statusFilter() || null,
      strategy: this.strategyFilter() || null,
      recommendation: this.recommendationFilter() || null,
      sort_by: this.sortBy() === 'created_at' ? null : this.sortBy(),
      sort_dir: this.sortDir() === 'desc' ? null : this.sortDir(),
      page: this.currentPage() === 1 ? null : this.currentPage(),
      page_size: this.pageSize() === DEFAULT_PAGE_SIZE ? null : this.pageSize(),
    };
  }

  private syncUrl(): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: this.buildQueryParams(),
      queryParamsHandling: 'replace',
      replaceUrl: true,
    });
  }

  private async loadPage(page: number): Promise<void> {
    this.error.set(null);
    this.selectedIds.set(new Set());
    const ps = this.pageSize();
    try {
      const result = await this.service.list(this.buildParams((page - 1) * ps, ps));
      this.rows.set(result.items);
      this.total.set(result.total);
      this.totals.set(result.totals ?? null);
    } catch (err) {
      this.error.set(this.resolveMessage(err));
    } finally {
      this.loading.set(false);
    }
  }

  private buildParams(offset: number, limit: number): Record<string, unknown> {
    const date = this.dateFilter();
    const status = this.statusFilter();
    const strategy = this.strategyFilter();
    const recommendation = this.recommendationFilter();
    return {
      limit,
      offset,
      ...(date ? { dateFrom: date, dateTo: date } : {}),
      ...(status ? { status } : {}),
      ...(strategy ? { strategy } : {}),
      ...(recommendation ? { recommendation } : {}),
      sortBy: this.sortBy(),
      sortDir: this.sortDir(),
    };
  }

  private loadStake(): number {
    const stored = localStorage.getItem(STAKE_KEY);
    const parsed = stored ? parseInt(stored, 10) : NaN;
    return isNaN(parsed) || parsed < 1 ? DEFAULT_STAKE : parsed;
  }

  private resolveMessage(err: unknown): string {
    if (err instanceof AuthError) {
      return messageFor(this.translate, err.code);
    }
    return messageFor(this.translate, 'error.auth.unexpected');
  }
}
