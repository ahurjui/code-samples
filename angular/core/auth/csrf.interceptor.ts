/**
 * CSRF interceptor — double-submit cookie pattern.
 *
 * Reads the JS-readable `csrf` cookie and echoes it in
 * `X-CSRF-Token` on every state-changing request. Safe methods
 * (GET / HEAD / OPTIONS) pass through untouched.
 *
 * **Credentials**: fetch's default (`same-origin`) is what we
 * want — cookies flow on same-origin requests, Set-Cookie is
 * stored normally. Setting `withCredentials: true` would flip
 * fetch to `credentials: 'include'`, and combined with
 * webpack-dev-server's injected `Access-Control-Allow-Origin: *`
 * header Chrome treats every response as a CORS mismatch and
 * drops Set-Cookie. Don't do it.
 *
 * SSR runs never make state-changing calls in Layer 3a, so the
 * `document.cookie` access only ever fires in the browser.
 *
 * docs-ref: docs/modules/core/frontend-shell.md#rule-csrf-interceptor-adds-header-on-non-get-requests
 */

import { HttpInterceptorFn } from '@angular/common/http';
import { inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';

const CSRF_COOKIE_NAME = 'csrf';
const CSRF_HEADER_NAME = 'X-CSRF-Token';
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

export const csrfInterceptor: HttpInterceptorFn = (req, next) => {
  if (SAFE_METHODS.has(req.method.toUpperCase())) {
    return next(req);
  }

  const platformId = inject(PLATFORM_ID);
  if (!isPlatformBrowser(platformId)) {
    return next(req);
  }

  const token = readCookie(CSRF_COOKIE_NAME);
  if (!token) {
    return next(req);
  }

  return next(req.clone({ setHeaders: { [CSRF_HEADER_NAME]: token } }));
};

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
  return match ? decodeURIComponent(match[1]) : null;
}
