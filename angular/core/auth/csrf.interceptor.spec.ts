/**
 * Interceptor behaviour: csrf cookie → X-CSRF-Token header on
 * non-GET, no-op on GET.
 */

import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { csrfInterceptor } from './csrf.interceptor';

function setCsrfCookie(value: string): void {
  document.cookie = `csrf=${value}; path=/`;
}

function clearCsrfCookie(): void {
  document.cookie = 'csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
}

describe('csrfInterceptor', () => {
  let http: HttpClient;
  let ctrl: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([csrfInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    ctrl = TestBed.inject(HttpTestingController);
    clearCsrfCookie();
  });

  afterEach(() => {
    ctrl.verify();
    clearCsrfCookie();
  });

  // spec-ref: docs/modules/core/frontend-shell.md#rule-csrf-interceptor-adds-header-on-non-get-requests
  it('adds X-CSRF-Token header on POST', () => {
    setCsrfCookie('abc123');

    http.post('/api/anything', {}).subscribe();

    const req = ctrl.expectOne('/api/anything');
    expect(req.request.headers.get('X-CSRF-Token')).toBe('abc123');
    req.flush(null);
  });

  it('does not add header on GET', () => {
    setCsrfCookie('abc123');

    http.get('/api/anything').subscribe();

    const req = ctrl.expectOne('/api/anything');
    expect(req.request.headers.has('X-CSRF-Token')).toBeFalse();
    req.flush(null);
  });

  it('passes POST through when no csrf cookie is present', () => {
    http.post('/api/anything', {}).subscribe();

    const req = ctrl.expectOne('/api/anything');
    expect(req.request.headers.has('X-CSRF-Token')).toBeFalse();
    req.flush(null);
  });
});
