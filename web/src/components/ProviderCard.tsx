import type { Forecast, Provider } from '../types';
import {
  formatDuration,
  hasForecast,
  isFallbackGone,
  isSpendingNow,
} from '../types';

type Props = { provider: Provider; forecast: Forecast | null };

const FRESHNESS_NOTE: Record<string, string> = {
  live: 'read just now',
  cached: 'cached, not current',
  stale: 'stale, collect again',
};

const SOURCE_NOTE: Record<string, string> = {
  api: 'provider API',
  browser_json: 'browser, page JSON',
  browser_text: 'browser, rendered text (least precise)',
};

/** Why a provider did not answer, in words a reader can act on. */
const ERROR_NOTE: Record<string, string> = {
  no_reading: 'nothing collected yet',
  no_credential: 'not signed in on this machine',
  credential_expired: 'signed in once, needs refreshing',
  unauthorized: 'credential rejected',
  no_allowance: 'answered, but this account has no metered allowance',
  rate_limited: 'asked too often',
  endpoint_unavailable: 'could not be reached',
  malformed_response: 'answered in a shape this adapter could not read',
  browser_session_missing: 'browser profile not signed in',
  browser_unavailable: 'no browser installed',
  cooling_down: 'browser read too recently',
  unsupported_platform: 'no page this tool can read',
};

export function ProviderCard({ provider, forecast }: Props) {
  // Missing is never zero: an unanswered provider gets its
  // own treatment rather than a bar at zero percent.
  if (!provider.answered) {
    const code = provider.error ?? 'no_reading';
    return (
      <article className="card card--silent">
        <header>
          <h3>{provider.provider}</h3>
          <span className="pill pill--silent">no answer</span>
        </header>
        <p className="reason">
          <code>{code}</code>{' '}
          {ERROR_NOTE[code] ?? 'reported a state this page has no words for yet'}
        </p>
      </article>
    );
  }

  const binding = provider.binding_window;
  // Missing is never zero, one level down. An answered provider
  // always carries a window today, so this is a guard rather
  // than a path the API reaches -- but defaulting the percent to
  // zero would paint a card green for a limit nobody measured.
  const tone = binding
    ? binding.used_percent >= 90
      ? 'critical'
      : binding.used_percent >= 70
        ? 'warn'
        : 'ok'
    : 'silent';
  const percent = binding ? binding.used_percent : 0;

  return (
    <article className={`card card--${tone}`}>
      <header>
        <h3>{provider.provider}</h3>
        {provider.plan ? <span className="pill">{provider.plan}</span> : null}
        <span className={`pill pill--${provider.freshness}`}>
          {FRESHNESS_NOTE[provider.freshness] ?? provider.freshness}
        </span>
      </header>

      {binding ? (
        <div className="binding">
          <div className="binding__label">
            <strong>{binding.label}</strong> binds
            <span className="binding__percent">{percent.toFixed(1)}% used</span>
          </div>
          <div className="track">
            <div className="fill" style={{ width: `${Math.min(100, percent)}%` }} />
          </div>
          <div className="binding__reset">
            resets in {formatDuration(binding.resets_in_seconds)}
          </div>
        </div>
      ) : null}

      {provider.windows.length > 1 ? (
        <table className="windows">
          <thead>
            <tr>
              <th>window</th>
              <th>used</th>
              <th>resets in</th>
            </tr>
          </thead>
          <tbody>
            {provider.windows.map((window) => (
              <tr key={window.label}>
                <td>{window.label}</td>
                <td>{window.used_percent.toFixed(1)}%</td>
                <td>{formatDuration(window.resets_in_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <dl className="facts">
        <dt>source</dt>
        <dd>{SOURCE_NOTE[provider.source] ?? provider.source}</dd>

        <dt>credits</dt>
        <dd>
          {isSpendingNow(provider.credits) ? (
            <span className="spend">spending now</span>
          ) : isFallbackGone(provider.credits) ? (
            <span className="spent">allowance used up, no fallback left</span>
          ) : provider.credits.state === 'unavailable' ? (
            <span className="muted">not reported</span>
          ) : (
            provider.credits.state
          )}
          {provider.credits.detail ? ` — ${provider.credits.detail}` : ''}
        </dd>

        <dt>forecast</dt>
        <dd>
          {hasForecast(forecast) && forecast ? (
            forecast.status === 'window_spent' ? (
              <span className="spent">already fully used</span>
            ) : (
              <>
                <strong>{formatDuration(forecast.seconds_until_exhausted?.value)}</strong>{' '}
                at {forecast.burn_rate_per_hour?.value?.toFixed(1)}%/h
                {forecast.resets_before_exhausted ? (
                  <span className="muted"> — resets first, so it will not run out</span>
                ) : null}
              </>
            )
          ) : (
            // A declined forecast is a reason, never a number.
            <span className="muted">no forecast ({forecast?.status ?? 'unknown'})</span>
          )}
        </dd>
      </dl>
    </article>
  );
}
