# PHP / Laravel — code samples

Excerpts from a production travel-booking marketplace I co-founded in 2020, where I built the backend
(Laravel, PHP 8.3, MySQL, Redis, Docker). The platform integrates the Viator (TripAdvisor
Experiences) Partner API, Stripe and Revolut payments, and serves a versioned JSON API to a
React front end.

These are real production files, unmodified. All credentials are environment-driven
(`config/services.php` + `.env`); nothing sensitive is included. The files are excerpts, so
they won't run standalone — they're here to show code style, structure, and testing approach.

| File | What it shows |
|---|---|
| `app/Services/Viator/ViatorHttpClient.php` | Small, config-driven HTTP client for a third-party API; constructor injection, immutable config |
| `app/Services/Viator/UserViatorBookingMirrorService.php` | Service-layer class mirroring external bookings into local persistence: DB transaction with row locking, ownership guard, upsert semantics |
| `app/Http/Controllers/V2/ViatorBookingsController.php` | Full booking proxy (hold/book/status/cancel): PHP 8 constructor promotion, typed signatures, path-segment encoding, scalar-only query sanitization |
| `app/Http/Controllers/V2/ViatorAvailabilityController.php` | Secure server-side proxy pattern — the third-party API key never reaches the browser |
| `app/Http/Requests/SearchListingsRequest.php` | Form Request validation: conditional requirements, nested array rules, date-range logic |
| `app/Http/Requests/V2/ViatorPartnerJsonPostRequest.php` | Deliberate pass-through request for the proxy endpoints — the raw JSON body is forwarded byte-for-byte to Viator, which owns the contract (see the proxy controllers) |
| `app/Console/Commands/UpdateListingTranslationsAiTitleAndAiDescriptionCommand.php` | Scheduled console command using the OpenAI API to generate listing content, with fallback logic |
| `tests/Feature/V2/V2ListingsBehaviorTest.php` | Feature tests: validation contract, pagination, localization |
