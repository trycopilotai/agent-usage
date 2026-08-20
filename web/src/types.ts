// The shapes the agent-usage API actually serves.
//
// Mirrors agent_usage/contract.py. Every field here appears
// in a real response; nothing is aspirational. The three
// rules the Python contract enforces survive into the UI:
// a provider that did not answer is not a zero, a stale
// reading is never drawn as live, and a declined forecast is
// never rendered as a number.

export type CreditState =
  | 'unavailable'
  | 'off'
  | 'available'
  | 'active'
  | 'exhausted';

export type Source = 'api' | 'browser_json' | 'browser_text';

export type Freshness = 'live' | 'cached' | 'stale';

/** What a window limits.
 *
 * `account` governs the work the account can do at all.
 * `feature` meters one capability inside it. Only account
 * windows bind, so a spent feature pool never becomes the
 * answer to "how much is left". Optional because a response
 * from an older collector will not carry it; absent reads as
 * `account`, which is what those responses meant. */
export type WindowScope = 'account' | 'feature';

export type UsageWindow = {
  label: string;
  /** Percent consumed, never remaining. */
  used_percent: number;
  resets_in_seconds?: number | null;
  remaining?: number | null;
  limit?: number | null;
  scope?: WindowScope;
};

export type Credits = {
  state: CreditState;
  detail: string;
};

export type Provider = {
  provider: string;
  collected_at: number;
  source: Source;
  freshness: Freshness;
  plan: string;
  adapter_version: number;
  windows: UsageWindow[];
  credits: Credits;
  /** False means the provider did not report. Not zero. */
  answered: boolean;
  /** Closed vocabulary. Present only when answered is false. */
  error?: string | null;
  /** The limit that governs the account, not the fullest pool. */
  binding_window?: UsageWindow | null;
};

export type Snapshot = {
  schema: string;
  generated_at: number;
  providers: Provider[];
  answered: number;
  requested: number;
};

/** A forecast is one of these. Only two are answers. */
export type ForecastStatus =
  | 'projected'
  | 'window_spent'
  | 'insufficient_samples'
  | 'span_too_short'
  | 'not_rising'
  | 'window_reset'
  | 'no_binding_window'
  | string;

export type Estimate = {
  status: string;
  value?: number;
};

export type Forecast = {
  provider: string;
  status: ForecastStatus;
  window?: string;
  used_percent?: number;
  burn_rate_per_hour?: Estimate;
  seconds_until_exhausted?: Estimate;
  resets_in_seconds?: number;
  resets_before_exhausted?: boolean;
};

export type HistoryPoint = {
  collected_at: number;
  used_percent: number;
};

export type History = {
  provider: string;
  points: HistoryPoint[];
};

/** Statuses that carry a number rather than a reason. */
export const FORECAST_ANSWERS = new Set(['projected', 'window_spent']);

export function hasForecast(forecast: Forecast | null): boolean {
  return forecast !== null && FORECAST_ANSWERS.has(forecast.status);
}

/** Credit that is costing money right now. Not the cap. */
export function isSpendingNow(credits: Credits): boolean {
  return credits.state === 'active';
}

/** Credit drawn on and now used up, so there is no fallback. */
export function isFallbackGone(credits: Credits): boolean {
  return credits.state === 'exhausted';
}

/** Feature pools with nothing left.
 *
 * The account limit can show headroom while a capability is
 * unusable. Ranking on the account figure is right, and
 * saying nothing about the spent capability is not. */
export function spentFeatures(provider: Provider): UsageWindow[] {
  return provider.windows.filter(
    (window) => window.scope === 'feature' && window.used_percent >= 100,
  );
}

export function headroomOrder(providers: Provider[]): Provider[] {
  // Only providers that answered can be ranked. A provider
  // that did not report has unknown headroom, not full
  // headroom, so it is never recommended.
  return providers
    .filter((p) => p.answered && p.binding_window)
    .sort(
      (a, b) =>
        (a.binding_window as UsageWindow).used_percent -
        (b.binding_window as UsageWindow).used_percent,
    );
}

export function formatDuration(seconds?: number | null): string {
  if (seconds === undefined || seconds === null) return 'unknown';
  if (seconds <= 0) return 'now';
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}
