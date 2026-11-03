/**
 * Route guards driven by `AuthService.isAuthenticated`.
 *
 * - `authGuard` — blocks unauthenticated access, redirects to `/login`.
 * - `anonGuard` — prevents logged-in users from reaching `/login` or
 *   `/register`; redirects them to `/`.
 *
 * docs-ref: docs/modules/core/frontend-shell.md#rule-auth-guard-redirects-unauthenticated-to-login
 * docs-ref: docs/modules/core/frontend-shell.md#rule-login-page-redirects-authenticated-user-to-home
 */

import { inject } from '@angular/core';
import { CanActivateFn, Router, RouterStateSnapshot } from '@angular/router';

import { AuthService } from './auth.service';

export const authGuard: CanActivateFn = (_route, state: RouterStateSnapshot) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (auth.isAuthenticated()) {
    return true;
  }
  return router.parseUrl(`/login?returnUrl=${encodeURIComponent(state.url)}`);
};

export const anonGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return auth.isAuthenticated() ? router.parseUrl('/') : true;
};
