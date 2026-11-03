/**
 * Minimal typed API client. Errors carry the HTTP status so callers can
 * distinguish "not found" from "server broke" without string-matching.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    signal,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { error?: string };
      if (body.error) detail = body.error;
    } catch {
      // Non-JSON error body — keep the status text.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}
