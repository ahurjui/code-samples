/**
 * Unit tests for `TicketsListComponent`.
 *
 * Covers URL-state hydration on init, syncUrl calls on state changes,
 * total-based pagination, and page-size persistence.
 */

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import { provideRouter } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { TicketsListComponent } from './tickets-list.component';
import { TicketsService } from '../../../core/tickets/tickets.service';
import { StrategySettingsService } from '../../../core/settings/strategy-settings.service';
import { bucharestToday } from '../../../core/util/bucharest-date';

describe('TicketsListComponent', () => {
  let component: TicketsListComponent;
  let fixture: ComponentFixture<TicketsListComponent>;
  let service: jasmine.SpyObj<TicketsService>;
  let strategySvc: jasmine.SpyObj<StrategySettingsService>;

  beforeEach(async () => {
    // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#1-url-backed-list-state-on-tickets-mirror-matches
    service = jasmine.createSpyObj('TicketsService', ['list']);
    service.list.and.returnValue(Promise.resolve({ items: [], total: 0 }));
    strategySvc = jasmine.createSpyObj('StrategySettingsService', ['get']);
    strategySvc.get.and.returnValue(Promise.resolve({ strategies: [], selections: [] }));

    await TestBed.configureTestingModule({
      imports: [TicketsListComponent, TranslateModule.forRoot(), NoopAnimationsModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: TicketsService, useValue: service },
        { provide: StrategySettingsService, useValue: strategySvc },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { queryParamMap: convertToParamMap({}) },
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(TicketsListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
  });

  it('should call list on init', async () => {
    // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#1-url-backed-list-state-on-tickets-mirror-matches
    expect(service.list).toHaveBeenCalledTimes(1);
  });

  describe('allPl computed signal', () => {
    // spec-ref: docs/modules/betting/football/tickets-ui.md#filtered-totals
    it('returns zeros when totals is null', () => {
      component.totals.set(null);
      const result = component.allPl();
      expect(result.won).toBe(0);
      expect(result.lost).toBe(0);
      expect(result.net).toBe(0);
      expect(result.settled).toBe(0);
      expect(result.total).toBe(0);
    });

    it('multiplies totals multiplier sums by the stake', () => {
      component.totals.set({
        won_multiplier_sum: 2.0,
        lost_multiplier_sum: 0.5,
        settled_count: 3,
        total_count: 4,
      });
      component.stake.set(10);
      const result = component.allPl();
      expect(result.won).toBeCloseTo(20.0, 2);
      expect(result.lost).toBeCloseTo(5.0, 2);
      expect(result.net).toBeCloseTo(15.0, 2);
      expect(result.settled).toBe(3);
      expect(result.total).toBe(4);
    });

    it('updates immediately when stake changes', () => {
      component.totals.set({
        won_multiplier_sum: 1.0,
        lost_multiplier_sum: 1.0,
        settled_count: 2,
        total_count: 2,
      });
      component.stake.set(20);
      expect(component.allPl().won).toBeCloseTo(20.0, 2);
      component.stake.set(5);
      expect(component.allPl().won).toBeCloseTo(5.0, 2);
    });
  });

  it('should default to page 1 and page size 25', () => {
    expect(component.currentPage()).toBe(1);
    expect(component.pageSize()).toBe(25);
  });

  it('should show empty state when no tickets', async () => {
    await fixture.whenStable();
    fixture.detectChanges();
    expect(component.rows().length).toBe(0);
  });

  describe('query param hydration', () => {
    it('should hydrate dateFilter from ?date query param', async () => {
      // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#1-url-backed-list-state-on-tickets-mirror-matches
      TestBed.resetTestingModule();
      const svc = jasmine.createSpyObj('TicketsService', ['list']);
      svc.list.and.returnValue(Promise.resolve({ items: [], total: 0 }));
      await TestBed.configureTestingModule({
        imports: [TicketsListComponent, TranslateModule.forRoot(), NoopAnimationsModule],
        providers: [
          provideHttpClient(),
          provideHttpClientTesting(),
          provideRouter([]),
          { provide: TicketsService, useValue: svc },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: { queryParamMap: convertToParamMap({ date: '2026-04-26' }) },
            },
          },
        ],
      }).compileComponents();
      const f = TestBed.createComponent(TicketsListComponent);
      const c = f.componentInstance;
      f.detectChanges();
      await f.whenStable();
      expect(c.dateFilter()).toBe('2026-04-26');
    });

    it('should hydrate statusFilter from ?status query param', async () => {
      // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#1-url-backed-list-state-on-tickets-mirror-matches
      TestBed.resetTestingModule();
      const svc = jasmine.createSpyObj('TicketsService', ['list']);
      svc.list.and.returnValue(Promise.resolve({ items: [], total: 0 }));
      await TestBed.configureTestingModule({
        imports: [TicketsListComponent, TranslateModule.forRoot(), NoopAnimationsModule],
        providers: [
          provideHttpClient(),
          provideHttpClientTesting(),
          provideRouter([]),
          { provide: TicketsService, useValue: svc },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: { queryParamMap: convertToParamMap({ status: 'WON' }) },
            },
          },
        ],
      }).compileComponents();
      const f = TestBed.createComponent(TicketsListComponent);
      const c = f.componentInstance;
      f.detectChanges();
      await f.whenStable();
      expect(c.statusFilter()).toBe('WON');
    });

    it('should hydrate page and page_size from query params', async () => {
      // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#1-url-backed-list-state-on-tickets-mirror-matches
      TestBed.resetTestingModule();
      const svc = jasmine.createSpyObj('TicketsService', ['list']);
      svc.list.and.returnValue(Promise.resolve({ items: [], total: 0 }));
      await TestBed.configureTestingModule({
        imports: [TicketsListComponent, TranslateModule.forRoot(), NoopAnimationsModule],
        providers: [
          provideHttpClient(),
          provideHttpClientTesting(),
          provideRouter([]),
          { provide: TicketsService, useValue: svc },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: { queryParamMap: convertToParamMap({ page: '3', page_size: '50' }) },
            },
          },
        ],
      }).compileComponents();
      const f = TestBed.createComponent(TicketsListComponent);
      const c = f.componentInstance;
      f.detectChanges();
      await f.whenStable();
      expect(c.currentPage()).toBe(3);
      expect(c.pageSize()).toBe(50);
    });

    it('should hydrate sort_by and sort_dir from query params', async () => {
      // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#1-url-backed-list-state-on-tickets-mirror-matches
      TestBed.resetTestingModule();
      const svc = jasmine.createSpyObj('TicketsService', ['list']);
      svc.list.and.returnValue(Promise.resolve({ items: [], total: 0 }));
      await TestBed.configureTestingModule({
        imports: [TicketsListComponent, TranslateModule.forRoot(), NoopAnimationsModule],
        providers: [
          provideHttpClient(),
          provideHttpClientTesting(),
          provideRouter([]),
          { provide: TicketsService, useValue: svc },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: {
                queryParamMap: convertToParamMap({ sort_by: 'combined_odds', sort_dir: 'asc' }),
              },
            },
          },
        ],
      }).compileComponents();
      const f = TestBed.createComponent(TicketsListComponent);
      const c = f.componentInstance;
      f.detectChanges();
      await f.whenStable();
      expect(c.sortBy()).toBe('combined_odds');
      expect(c.sortDir()).toBe('asc');
    });

    it('should default dateFilter to today (Bucharest) when no date query param is present', () => {
      // spec-ref: docs/modules/betting/football/tickets-ui.md#rule-list-defaults-to-today
      // Arrange: component initialized by beforeEach with an empty query param map.
      // Act + Assert
      expect(component.dateFilter()).toBe(bucharestToday());
    });

    it('should call list with dateFrom and dateTo set to today when no date query param', () => {
      // spec-ref: docs/modules/betting/football/tickets-ui.md#rule-list-defaults-to-today
      // Arrange: component initialized by beforeEach with an empty query param map.
      const today = bucharestToday();
      // Act + Assert
      expect(service.list).toHaveBeenCalledWith(
        jasmine.objectContaining({ dateFrom: today, dateTo: today }),
      );
    });

    it('should write date to URL when applyFilters is called', async () => {
      // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#1-url-backed-list-state-on-tickets-mirror-matches
      await fixture.whenStable();
      const router = TestBed.inject(Router);
      const navSpy = spyOn(router, 'navigate').and.returnValue(Promise.resolve(true));
      component.dateFilter.set('2026-04-26');
      await component.applyFilters();
      expect(navSpy).toHaveBeenCalledWith(
        [],
        jasmine.objectContaining({
          queryParams: jasmine.objectContaining({ date: '2026-04-26' }),
        }),
      );
    });

    it('should write page to URL when goToPage is called', async () => {
      // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#1-url-backed-list-state-on-tickets-mirror-matches
      await fixture.whenStable();
      component.total.set(100);
      const router = TestBed.inject(Router);
      const navSpy = spyOn(router, 'navigate').and.returnValue(Promise.resolve(true));
      await component.goToPage(2);
      expect(navSpy).toHaveBeenCalledWith(
        [],
        jasmine.objectContaining({
          queryParams: jasmine.objectContaining({ page: 2 }),
        }),
      );
    });

    it('should omit defaults (page=1, page_size=25) from URL', async () => {
      // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#1-url-backed-list-state-on-tickets-mirror-matches
      await fixture.whenStable();
      const params = component.buildQueryParams();
      expect(params['page']).toBeNull();
      expect(params['page_size']).toBeNull();
    });

    it('should write page_size to URL when non-default', async () => {
      // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#5-persist-pagesize-in-url--both-lists
      await fixture.whenStable();
      component.pageSize.set(50);
      const params = component.buildQueryParams();
      expect(params['page_size']).toBe(50);
    });
  });

  describe('total-based pagination', () => {
    it('should compute totalPages correctly', () => {
      // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#4-frontend-ticketsservice-shape-change
      component.total.set(47);
      component.pageSize.set(25);
      expect(component.totalPages).toBe(2);
    });

    it('should clamp goToPage to totalPages', async () => {
      // spec-ref: docs/superpowers/specs/2026-04-29-issue-171-tickets-list-state-pagination-design.md#4-frontend-ticketsservice-shape-change
      await fixture.whenStable();
      component.total.set(10);
      service.list.calls.reset();
      await component.goToPage(999);
      expect(service.list).not.toHaveBeenCalled();
    });
  });

  describe('Issue #394 — recommendation filter + sort', () => {
    it('sends recommendation=bet in the request payload when the filter is set', async () => {
      // Issue #394 — recommendation filter narrows request payload
      await fixture.whenStable();
      service.list.calls.reset();
      component.recommendationFilter.set('bet');
      await component.applyFilters();
      expect(service.list).toHaveBeenCalledWith(
        jasmine.objectContaining({ recommendation: 'bet' }),
      );
    });

    it('sets sortBy to feeling_recommendation when sort() is called with that column', async () => {
      // Issue #394 — Recommendation column header click sets sort field
      await fixture.whenStable();
      service.list.calls.reset();
      component.sort('feeling_recommendation');
      await fixture.whenStable();
      expect(component.sortBy()).toBe('feeling_recommendation');
      expect(service.list).toHaveBeenCalledWith(
        jasmine.objectContaining({ sortBy: 'feeling_recommendation' }),
      );
    });

    it('sets sortBy to strategy when sort() is called with that column', async () => {
      // Issue #394 — Strategy column header click sets sort field
      await fixture.whenStable();
      service.list.calls.reset();
      component.sort('strategy');
      await fixture.whenStable();
      expect(component.sortBy()).toBe('strategy');
      expect(service.list).toHaveBeenCalledWith(jasmine.objectContaining({ sortBy: 'strategy' }));
    });
  });
});

describe('TicketsListComponent — recommendation column', () => {
  function buildRow(rec: string | null) {
    return {
      id: 1,
      status: 'PENDING',
      combined_odds: '2.25',
      created_at: '2026-01-01T00:00:00Z',
      resolved_at: null,
      feeling_score: 70,
      feeling_recommendation: rec,
      leg_count: 2,
      warning_count: 0,
      strategy_name: null,
      strategy_version: null,
    };
  }

  async function setupWithRow(rec: string | null) {
    TestBed.resetTestingModule();
    const svc = jasmine.createSpyObj('TicketsService', ['list']);
    svc.list.and.returnValue(Promise.resolve({ items: [buildRow(rec)], total: 1 }));
    const strategySvc = jasmine.createSpyObj('StrategySettingsService', ['get']);
    strategySvc.get.and.returnValue(Promise.resolve({ strategies: [], selections: [] }));

    await TestBed.configureTestingModule({
      imports: [TicketsListComponent, TranslateModule.forRoot(), NoopAnimationsModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: TicketsService, useValue: svc },
        { provide: StrategySettingsService, useValue: strategySvc },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: convertToParamMap({}) } },
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(TicketsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return fixture;
  }

  it('renders em-dash when feeling_recommendation is null', async () => {
    // spec-ref: docs/superpowers/specs/2026-05-04-issue-243-recommendation-column-design.md#ui
    const fixture = await setupWithRow(null);
    const badge = fixture.nativeElement.querySelector('[data-testid="rec-badge"]');
    expect(badge).toBeNull();
    const emDashes = Array.from<Element>(
      fixture.nativeElement.querySelectorAll('.text-muted-foreground'),
    ).filter((el) => (el as HTMLElement).textContent?.trim() === '—');
    expect(emDashes.length).toBeGreaterThan(0);
  });

  it('renders a green badge for bet', async () => {
    // spec-ref: docs/superpowers/specs/2026-05-04-issue-243-recommendation-column-design.md#ui
    const fixture = await setupWithRow('bet');
    const badge: HTMLElement | null = fixture.nativeElement.querySelector(
      '[data-testid="rec-badge"]',
    );
    expect(badge).not.toBeNull();
    expect(badge!.className).toContain('bg-green-100');
    expect(badge!.className).toContain('text-green-800');
  });

  it('renders an amber badge for lean_bet', async () => {
    // spec-ref: docs/superpowers/specs/2026-05-04-issue-243-recommendation-column-design.md#ui
    const fixture = await setupWithRow('lean_bet');
    const badge: HTMLElement | null = fixture.nativeElement.querySelector(
      '[data-testid="rec-badge"]',
    );
    expect(badge).not.toBeNull();
    expect(badge!.className).toContain('bg-amber-100');
    expect(badge!.className).toContain('text-amber-800');
  });

  it('renders a red badge for no_bet', async () => {
    // spec-ref: docs/superpowers/specs/2026-05-04-issue-243-recommendation-column-design.md#ui
    const fixture = await setupWithRow('no_bet');
    const badge: HTMLElement | null = fixture.nativeElement.querySelector(
      '[data-testid="rec-badge"]',
    );
    expect(badge).not.toBeNull();
    expect(badge!.className).toContain('bg-red-100');
    expect(badge!.className).toContain('text-red-800');
  });
});

describe('TicketsListComponent — day-nav integration', () => {
  let component: TicketsListComponent;
  let fixture: ComponentFixture<TicketsListComponent>;
  let service: jasmine.SpyObj<TicketsService>;
  let strategySvc: jasmine.SpyObj<StrategySettingsService>;

  beforeEach(async () => {
    // spec-ref: docs/modules/betting/football/tickets-ui.md#rule-day-nav
    service = jasmine.createSpyObj('TicketsService', ['list']);
    service.list.and.returnValue(Promise.resolve({ items: [], total: 0 }));
    strategySvc = jasmine.createSpyObj('StrategySettingsService', ['get']);
    strategySvc.get.and.returnValue(Promise.resolve({ strategies: [], selections: [] }));

    await TestBed.configureTestingModule({
      imports: [TicketsListComponent, TranslateModule.forRoot(), NoopAnimationsModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: TicketsService, useValue: service },
        { provide: StrategySettingsService, useValue: strategySvc },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: convertToParamMap({}) } },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(TicketsListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
  });

  it('renders the day-nav component in the date filter row', () => {
    // spec-ref: docs/modules/betting/football/tickets-ui.md#rule-day-nav
    const nav = fixture.nativeElement.querySelector('app-day-nav');
    expect(nav).toBeTruthy();
  });

  it('prev button shifts dateFilter back one day and re-queries', async () => {
    // spec-ref: docs/modules/betting/football/tickets-ui.md#rule-day-nav
    service.list.calls.reset();
    service.list.and.returnValue(Promise.resolve({ items: [], total: 0 }));

    component.dateFilter.set('2026-05-15');
    fixture.detectChanges();

    const navEl = fixture.nativeElement.querySelector('app-day-nav');
    const prevBtn = navEl.querySelectorAll('button')[0] as HTMLButtonElement;
    prevBtn.click();
    await fixture.whenStable();

    expect(component.dateFilter()).toBe('2026-05-14');
    expect(service.list).toHaveBeenCalledTimes(1);
  });

  it('next button shifts dateFilter forward one day and re-queries', async () => {
    // spec-ref: docs/modules/betting/football/tickets-ui.md#rule-day-nav
    service.list.calls.reset();
    service.list.and.returnValue(Promise.resolve({ items: [], total: 0 }));

    // Set to a past date so next is enabled
    component.dateFilter.set('2026-05-14');
    fixture.detectChanges();

    const navEl = fixture.nativeElement.querySelector('app-day-nav');
    const nextBtn = navEl.querySelectorAll('button')[1] as HTMLButtonElement;
    nextBtn.click();
    await fixture.whenStable();

    expect(component.dateFilter()).toBe('2026-05-15');
    expect(service.list).toHaveBeenCalledTimes(1);
  });
});
