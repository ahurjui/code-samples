<?php

namespace App\Http\Controllers\V2;

use App\Http\Controllers\Controller;
use App\Http\Requests\V2\ViatorPartnerJsonPostRequest;
use App\Services\Viator\ViatorHttpClient;
use Illuminate\Http\Response;

/**
 * Authenticated V2 proxy for Viator Partner **Availability** endpoints.
 *
 * The browser never holds the Viator key; only this server sends `exp-api-key`.
 * HTTP status and body are returned exactly as Viator returns them.
 *
 * @see https://docs.viator.com/partner-api/technical/#tag/Availability
 */
class ViatorAvailabilityController extends Controller
{
    /**
     * @param  ViatorHttpClient  $viatorHttp  Shared client (base URL, exp-api-key, 120s timeout).
     */
    public function __construct(
        private readonly ViatorHttpClient $viatorHttp,
    ) {
    }

    /**
     * Proxies Viator `POST /availability/check`.
     * Call when the user has product, date, and passenger mix, and again immediately before book (per Viator).
     *
     * @return Response Same status and body as the upstream Viator response.
     */
    public function check(ViatorPartnerJsonPostRequest $request): Response
    {
        // Raw body keeps the front end’s JSON identical to what Viator expects (no re-encoding drift).
        $body = $request->getContent() ?: '{}';

        return $this->viatorHttp->postRaw('/availability/check', $body);
    }
}
