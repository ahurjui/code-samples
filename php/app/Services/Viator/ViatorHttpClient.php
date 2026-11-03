<?php

namespace App\Services\Viator;

use Illuminate\Http\Client\Response as ClientResponse;
use Illuminate\Http\Response;
use Illuminate\Support\Facades\Http;

/**
 * Thin HTTP client for Viator Partner API (same headers as existing ingestion code).
 * Used by V2 booking proxy and console booking sync.
 */
final class ViatorHttpClient
{
    public function __construct(
        private readonly string $baseUrl,
        private readonly string $apiKey,
        private readonly int $timeoutSeconds = 120,
        private readonly string $acceptLanguage = 'en-US',
    ) {
    }

    public static function fromConfig(): self
    {
        return new self(
            rtrim((string) config('services.viator.base_url'), '/'),
            (string) config('services.viator.api_key'),
            (int) config('services.viator.timeout', 120),
        );
    }

    /**
     * @param  array<string, mixed>  $query
     */
    public function get(string $path, array $query = []): Response
    {
        $url = $this->buildUrl($path, $query);
        $clientResponse = Http::withHeaders($this->headers())
            ->timeout($this->timeoutSeconds)
            ->get($url);

        return $this->toIlluminateResponse($clientResponse);
    }

    /**
     * POST with a raw JSON body (preserves client payload byte-for-byte where possible).
     *
     * @param  array<string, string>  $query
     */
    public function postRaw(string $path, string $jsonBody, array $query = []): Response
    {
        $url = $this->buildUrl($path, $query);
        $clientResponse = Http::withHeaders(array_merge($this->headers(), [
            'Content-Type' => 'application/json',
        ]))
            ->timeout($this->timeoutSeconds)
            ->withBody($jsonBody, 'application/json')
            ->post($url);

        return $this->toIlluminateResponse($clientResponse);
    }

    /**
     * @param  array<string, mixed>  $query
     */
    private function buildUrl(string $path, array $query): string
    {
        $url = $this->baseUrl . $path;
        if ($query === []) {
            return $url;
        }

        return $url . (str_contains($path, '?') ? '&' : '?') . http_build_query($query);
    }

    /**
     * @return array<string, string>
     */
    private function headers(): array
    {
        return [
            'exp-api-key' => $this->apiKey,
            'Accept' => 'application/json;version=2.0',
            'Accept-Language' => $this->acceptLanguage,
        ];
    }

    private function toIlluminateResponse(ClientResponse $r): Response
    {
        $body = $r->body();
        $status = $r->status();
        $contentType = $r->header('Content-Type') ?: 'application/json';

        return response($body, $status)->header('Content-Type', $contentType);
    }
}
