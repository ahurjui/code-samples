import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AuthError } from '../auth/models';
import { TicketsService } from './tickets.service';

describe('TicketsService', () => {
  let service: TicketsService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [TicketsService, provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(TicketsService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  // spec-ref: docs/modules/betting/football/tickets-ui.md#list
  it('list GETs /api/betting/football/tickets with limit + offset', async () => {
    const promise = service.list({ limit: 25, offset: 50 });
    const req = http.expectOne(
      (r) =>
        r.url === '/api/betting/football/tickets' &&
        r.params.get('limit') === '25' &&
        r.params.get('offset') === '50',
    );
    expect(req.request.method).toBe('GET');
    req.flush({ items: [], total: 0, totals: null });
    expect(await promise).toEqual({ items: [], total: 0, totals: null });
  });

  // spec-ref: docs/modules/betting/football/tickets-ui.md#filtered-totals
  it('list deserialises totals block from response', async () => {
    const promise = service.list({ limit: 25, offset: 0 });
    const req = http.expectOne((r) => r.url === '/api/betting/football/tickets');
    req.flush({
      items: [],
      total: 3,
      totals: {
        won_multiplier_sum: 1.5,
        lost_multiplier_sum: 0.75,
        settled_count: 2,
        total_count: 3,
      },
    });
    const result = await promise;
    expect(result.totals).toEqual({
      won_multiplier_sum: 1.5,
      lost_multiplier_sum: 0.75,
      settled_count: 2,
      total_count: 3,
    });
  });

  // spec-ref: docs/modules/betting/football/tickets-ui.md#detail
  it('get GETs /api/betting/football/tickets/:id', async () => {
    const promise = service.get(42);
    const req = http.expectOne('/api/betting/football/tickets/42');
    expect(req.request.method).toBe('GET');
    req.flush({
      id: 42,
      status: 'PENDING',
      combined_odds: '2.25',
      created_at: 'x',
      resolved_at: null,
      legs: [],
      warnings: [],
      feeling: null,
    });
    expect((await promise).id).toBe(42);
  });

  // spec-ref: docs/modules/betting/football/tickets-ui.md#rule-detail-404-carries-errorticketsnot_found
  it('get surfaces backend 404 code as AuthError', async () => {
    const promise = service.get(999);
    const req = http.expectOne('/api/betting/football/tickets/999');
    req.flush(
      { detail: { code: 'error.tickets.not_found' } },
      { status: 404, statusText: 'Not Found' },
    );
    await expectAsync(promise).toBeRejectedWith(
      jasmine.objectContaining<AuthError>({
        code: 'error.tickets.not_found',
        httpStatus: 404,
      }),
    );
  });
});
