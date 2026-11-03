# Angular — code samples

Excerpts from a sports-analytics web application I built (Angular 20 with SSR, standalone
components, TypeScript, Tailwind CSS) on top of a FastAPI backend. Structure follows a
`core/` (services, guards, interceptors) / `pages/` (routed features) / `shared/` (reusable
UI) split.

These are real files from the application, unmodified. No credentials are involved — the frontend
talks to the API via same-origin cookie auth. The files are excerpts and won't build
standalone; they're here to show component architecture, typed services, and unit testing.

| File | What it shows |
|---|---|
| `core/auth/auth.service.ts` | Authentication service: typed API calls, session state, token refresh handling |
| `core/auth/auth.guard.ts` | Route guard protecting authenticated pages |
| `core/auth/csrf.interceptor.ts` (+ spec) | HTTP interceptor attaching CSRF protection to mutating requests, with unit tests |
| `core/tickets/tickets.service.ts` (+ spec) | Domain data service: typed models, pagination, filtering, with unit tests |
| `pages/tickets/list/` | Routed feature component: loading/error/empty states, filtering, template + styles + spec |
| `shared/ticket-status-badge/` | Small reusable presentational component |
