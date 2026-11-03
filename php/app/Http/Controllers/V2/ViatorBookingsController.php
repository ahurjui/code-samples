<?php

namespace App\Http\Controllers\V2;

use App\Http\Controllers\Controller;
use App\Http\Requests\V2\ViatorPartnerJsonPostRequest;
use App\Services\Viator\ViatorHttpClient;
use Illuminate\Http\Request;
use Illuminate\Http\Response;

/**
 * Authenticated V2 proxy for Viator Partner **Bookings** endpoints.
 *
 * Covers hold, book, status, and cancel. Does not expose `GET /bookings/modified-since` (ingestion only;
 * see `SyncViatorBookingsModifiedSinceCommand`).
 * Some paths (e.g. single-item hold/book) may return 403 for non-merchant keys — we forward Viator’s response.
 *
 * @see https://docs.viator.com/partner-api/technical/#tag/Bookings
 */
class ViatorBookingsController extends Controller
{
    /**
     * @param  ViatorHttpClient  $viatorHttp  Shared client for Partner API calls.
     */
    public function __construct(
        private readonly ViatorHttpClient $viatorHttp,
    ) {
    }

    /**
     * Viator `POST /bookings/cart/hold` — multi-item cart hold (typical for Full + Booking affiliates).
     */
    public function cartHold(ViatorPartnerJsonPostRequest $request): Response
    {
        $body = $request->getContent() ?: '{}';

        return $this->viatorHttp->postRaw('/bookings/cart/hold', $body);
    }

    /**
     * Viator `POST /bookings/cart/book` — confirm after hold; include `bookingRef` from hold when applicable.
     */
    public function cartBook(ViatorPartnerJsonPostRequest $request): Response
    {
        $body = $request->getContent() ?: '{}';

        return $this->viatorHttp->postRaw('/bookings/cart/book', $body);
    }

    /**
     * Viator `POST /bookings/hold` — single-product hold (often merchant-only on Viator’s access matrix).
     */
    public function hold(ViatorPartnerJsonPostRequest $request): Response
    {
        $body = $request->getContent() ?: '{}';

        return $this->viatorHttp->postRaw('/bookings/hold', $body);
    }

    /**
     * Viator `POST /bookings/book` — single-product book (often merchant-only).
     */
    public function book(ViatorPartnerJsonPostRequest $request): Response
    {
        $body = $request->getContent() ?: '{}';

        return $this->viatorHttp->postRaw('/bookings/book', $body);
    }

    /**
     * Viator `POST /bookings/status` — pending manual confirmation, or recovery after a failed book call.
     */
    public function status(ViatorPartnerJsonPostRequest $request): Response
    {
        $body = $request->getContent() ?: '{}';

        return $this->viatorHttp->postRaw('/bookings/status', $body);
    }

    /**
     * Viator `GET /bookings/cancel-reasons` — optional query string (scalars only; see `stringQuery()`).
     */
    public function cancelReasons(Request $request): Response
    {
        return $this->viatorHttp->get('/bookings/cancel-reasons', $this->stringQuery($request));
    }

    /**
     * Viator `GET /bookings/{bookingRef}/cancel-quote` — refund/cancel quote before committing cancel.
     *
     * @param  string  $viatorBookingRef  Viator booking reference (route: alnum, dots, hyphens).
     */
    public function cancelQuote(Request $request, string $viatorBookingRef): Response
    {
        // Encode for safe use inside the path segment when refs contain special characters.
        $ref = $this->encodePathSegment($viatorBookingRef);

        return $this->viatorHttp->get("/bookings/{$ref}/cancel-quote", $this->stringQuery($request));
    }

    /**
     * Viator `POST /bookings/{bookingRef}/cancel` — body per Viator (reason codes, etc.).
     *
     * @param  string  $viatorBookingRef  Viator booking reference.
     */
    public function cancel(ViatorPartnerJsonPostRequest $request, string $viatorBookingRef): Response
    {
        $ref = $this->encodePathSegment($viatorBookingRef);
        $body = $request->getContent() ?: '{}';

        return $this->viatorHttp->postRaw("/bookings/{$ref}/cancel", $body);
    }

    /**
     * Build a flat query array for Viator: only scalar values (arrays would need different encoding rules).
     *
     * @return array<string, string>
     */
    private function stringQuery(Request $request): array
    {
        $out = [];
        foreach ($request->query() as $key => $value) {
            if (is_array($value)) {
                continue;
            }
            if ($value === null) {
                continue;
            }
            $out[(string) $key] = (string) $value;
        }

        return $out;
    }

    /**
     * Path-segment encoding for booking refs in the middle of a URL (RFC 3986).
     */
    private function encodePathSegment(string $viatorBookingRef): string
    {
        return rawurlencode($viatorBookingRef);
    }
}
