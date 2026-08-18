import { useCallback, useEffect, useState } from 'react';

import type { Forecast, History, Snapshot } from '../types';

// Polls the read only API. There is no event stream: the
// collectors are rate limited by design and a snapshot that
// changes every few minutes does not need a socket.

const POLL_MS = 30_000;

/** The API root, read from the document at load time. */
export function apiBase(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="agent-usage-api"]');
  const value = meta?.content?.trim();
  return (value && value.length > 0 ? value : '/api/v1').replace(/\/$/, '');
}

export type UsageState = {
  snapshot: Snapshot | null;
  forecasts: Record<string, Forecast>;
  histories: Record<string, History>;
  error: string | null;
  loading: boolean;
  refresh: () => void;
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!response.ok) {
    throw new Error(`${path} responded ${response.status}`);
  }
  return (await response.json()) as T;
}

export function useUsage(): UsageState {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [forecasts, setForecasts] = useState<Record<string, Forecast>>({});
  const [histories, setHistories] = useState<Record<string, History>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const next = await getJson<Snapshot>(`${apiBase()}/snapshot`);
        if (cancelled) return;
        setSnapshot(next);
        setError(null);

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
        setForecasts(nextForecasts);
        setHistories(nextHistories);
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : 'request failed');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [tick]);

  return { snapshot, forecasts, histories, error, loading, refresh };
}
