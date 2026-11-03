import { useCallback, useEffect, useState } from 'react';

import { ApiError, getJson } from '../api/client';
import type { Member } from './types';

interface MembersState {
  members: Member[];
  loading: boolean;
  error: string | null;
}

/**
 * Loads the member list, exposing loading/error state and a manual refresh.
 * In-flight requests are aborted on unmount or refresh, so a slow response
 * can never overwrite a newer one.
 */
export function useMembers(): MembersState & { refresh: () => void } {
  const [state, setState] = useState<MembersState>({
    members: [],
    loading: true,
    error: null,
  });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));

    getJson<{ members: Member[] }>('/api/members', controller.signal)
      .then((payload) => {
        setState({ members: payload.members, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return; // stale request, ignore
        const message =
          err instanceof ApiError
            ? `Could not load members (${err.status}): ${err.message}`
            : 'Could not load members: network error';
        setState({ members: [], loading: false, error: message });
      });

    return () => controller.abort();
  }, [reloadToken]);

  const refresh = useCallback(() => setReloadToken((n) => n + 1), []);

  return { ...state, refresh };
}
