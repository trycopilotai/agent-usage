import { useCallback, useEffect, useState } from 'react';

import type { Forecast, History, Snapshot } from '../types';

// Polls the read only API. There is no event stream: the
// collectors are rate limited by design and a snapshot that
// changes every few minutes does not need a socket.
//
// The snapshot is polled on its own; per provider detail is
// refetched only when the snapshot is actually newer. The
// collector samples on a much slower interval than this page
// polls, so refetching detail every cycle spends requests on
// answers that cannot have changed.

const POLL_MS = 30_000;

/** The API root, read from the document at load time. */
export function apiBase(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="agent-usage-api"]');
  const value = meta?.content?.trim();
  return (value && value.length > 0 ? value : '/api/v1').replace(/\/$/, '');
}

/** Why a request failed, in a form the page can speak about. */
export type FailureKind = 'auth' | 'timeout' | 'http' | 'network' | 'shape';

export class ApiError extends Error {
  readonly kind: FailureKind;

  constructor(kind: FailureKind, message: string) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
  }
}

export type UsageState = {
  snapshot: Snapshot | null;
  forecasts: Record<string, Forecast>;
  histories: Record<string, History>;
  error: ApiError | null;
  /** Providers whose detail could not be read this cycle. */
  incomplete: string[];
  loading: boolean;
  refresh: () => void;
};

async function getJson<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { headers: { Accept: 'application/json' } });
  } catch {
    // A cross origin redirect to a sign in page fails here
    // rather than arriving as a status, so a network error is
    // not proof the service is down.
    throw new ApiError('network', `${path} could not be reached`);
  }

  if (response.status === 401 || response.status === 403) {
    throw new ApiError('auth', `${path} refused the request`);
  }
  if (response.status === 504) {
    throw new ApiError('timeout', `${path} took too long upstream`);
  }
  if (!response.ok) {
    throw new ApiError('http', `${path} responded ${response.status}`);
  }

  // An expired session can answer 200 with a sign in page, so
  // the body is checked rather than trusted.
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('json')) {
    throw new ApiError('auth', `${path} answered with a page, not data`);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError('shape', `${path} answered with unreadable data`);
  }
}

export function useUsage(): UsageState {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [forecasts, setForecasts] = useState<Record<string, Forecast>>({});
  const [histories, setHistories] = useState<Record<string, History>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [incomplete, setIncomplete] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    // Detail belongs to one snapshot. Refetching it for a
    // snapshot already on screen asks the collector for
    // readings it cannot yet have.
    let detailGeneratedAt: number | null = null;

    async function load() {
      let next: Snapshot;
      try {
        next = await getJson<Snapshot>(`${apiBase()}/snapshot`);
      } catch (caught) {
        if (!cancelled) {
          setError(
            caught instanceof ApiError
              ? caught
              : new ApiError('network', 'request failed'),
          );
          setLoading(false);
        }
        return;
      }
      if (cancelled) return;
      setSnapshot(next);
      setError(null);

      const unchanged = detailGeneratedAt === next.generated_at;
      if (unchanged) {
        setLoading(false);
        return;
      }

      // Per provider detail, fetched for every provider the
      // snapshot names so a failed one still shows why.
      const names = next.providers.map((provider) => provider.provider);
      const [forecastList, historyList] = await Promise.all([
        Promise.all(
          names.map((name) =>
            getJson<Forecast>(`${apiBase()}/forecast/${name}`).catch(() => null),
          ),
        ),
        Promise.all(
          names.map((name) =>
            getJson<History>(`${apiBase()}/history/${name}`).catch(() => null),
          ),
        ),
      ]);
      if (cancelled) return;

      const nextForecasts: Record<string, Forecast> = {};
      forecastList.forEach((value, index) => {
        if (value) nextForecasts[names[index]] = value;
      });
      const nextHistories: Record<string, History> = {};
      historyList.forEach((value, index) => {
        if (value) nextHistories[names[index]] = value;
      });

      // A detail request that failed is named rather than left
      // as a chart that quietly is not there.
      const missing = names.filter(
        (_name, index) => forecastList[index] === null || historyList[index] === null,
      );

      setForecasts(nextForecasts);
      setHistories(nextHistories);
      setIncomplete(missing);
      detailGeneratedAt = next.generated_at;
      setLoading(false);
    }

    load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [tick]);

  return { snapshot, forecasts, histories, error, incomplete, loading, refresh };
}
