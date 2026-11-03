/**
 * `AuthService` — single source of truth for identity across the app.
 *
 * Signals hold the current user; components `computed` or `effect` off
 * them. Methods wrap the HTTP calls to `/api/auth/*` and translate
 * backend `{detail: {code: "error.xxx"}}` payloads into typed
 * `AuthError`s the forms can switch on.
 *
 * Contract documented in
 * `docs/modules/core/frontend-shell.md#authservice`.
 */

import { isPlatformBrowser } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable, PLATFORM_ID, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { clearUser as sentryClearUser, setUser as sentrySetUser } from '../observability';

import { AuthError, User } from './models';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly platformId = inject(PLATFORM_ID);

  private readonly _user = signal<User | null>(null);
  readonly user = this._user.asReadonly();
  readonly isAuthenticated = computed(() => this._user() !== null);

  /** Update the user signal and mirror the change onto the
   *  Sentry scope so any client-side error surfaces with the
   *  authenticated user attached. No-op on Sentry when the SDK
   *  isn't initialised.
   *  docs-ref: docs/modules/core/error-tracking.md#flow-browser */
  private setUser(user: User | null): void {
    this._user.set(user);
    if (user === null) {
      sentryClearUser();
    } else {
      sentrySetUser({ id: user.id, email: user.email });
    }
  }

  /**
   * Called once at app bootstrap: seeds the CSRF cookie then
   * attempts to load the current user. A missing session leaves
   * `isAuthenticated` false without raising.
   *
   * **Browser-only.** On SSR this is a no-op — any HTTP we make
   * there gets captured by Angular's `provideClientHydration`
   * transfer cache and replayed on the client without its
   * `Set-Cookie` headers, which means the csrf cookie never lands
   * in the real browser. Letting the browser always fetch fresh
   * avoids the issue.
   */
  async initialize(): Promise<void> {
    if (!isPlatformBrowser(this.platformId)) {
      return;
    }
    await this.seedCsrf();
    try {
      const me = await firstValueFrom(this.http.get<User>('/api/auth/me'));
      this.setUser(me);
    } catch {
      this.setUser(null);
    }
  }

  async register(email: string, password: string): Promise<User> {
    const me = await this.httpAuth('POST', '/api/auth/register', {
      email,
      password,
    });
    this.setUser(me);
    return me;
  }

  async login(email: string, password: string): Promise<User> {
    const me = await this.httpAuth('POST', '/api/auth/login', {
      email,
      password,
    });
    this.setUser(me);
    return me;
  }

  async refresh(): Promise<User> {
    const me = await this.httpAuth('POST', '/api/auth/refresh');
    this.setUser(me);
    return me;
  }

  async logout(): Promise<void> {
    try {
      await firstValueFrom(this.http.post('/api/auth/logout', {}));
    } catch {
      // ignore — intent to log out matters more than server ack
    }
    this.setUser(null);
  }

  /**
   * Hit `GET /api/auth/csrf` so the `csrf` cookie is seeded.
   * The CSRF interceptor picks it up from there on later POSTs.
   * Swallow errors: a missing backend at boot shouldn't crash
   * the app.
   */
  private async seedCsrf(): Promise<void> {
    try {
      await firstValueFrom(this.http.get('/api/auth/csrf', { responseType: 'text' }));
    } catch {
      // no-op
    }
  }

  private async httpAuth(method: 'POST', url: string, body?: unknown): Promise<User> {
    try {
      return await firstValueFrom(this.http.request<User>(method, url, { body }));
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
