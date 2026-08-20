import type { Forecast, Provider } from '../types';
import {
  formatDuration,
  hasForecast,
  isFallbackGone,
  isSpendingNow,
  spentFeatures,
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

/** One rule for every bar and for the card behind them.
 *
 * The card's colour and a row's colour are the same judgement
 * about the same number, so they are made in one place. Two
 * thresholds that drift apart would paint a green bar inside a
 * red card. */
function toneFor(percent: number): 'ok' | 'warn' | 'critical' {
  if (percent >= 90) return 'critical';
  if (percent >= 70) return 'warn';
  return 'ok';
}

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
  const tone = binding ? toneFor(binding.used_percent) : 'silent';
  const spent = spentFeatures(provider);

  return (
    <article className={`card card--${tone}`}>
      <header>
        <h3>{provider.provider}</h3>
        {provider.plan ? <span className="pill">{provider.plan}</span> : null}
        <span className={`pill pill--${provider.freshness}`}>
          {FRESHNESS_NOTE[provider.freshness] ?? provider.freshness}
        </span>
      </header>

      {/* Every pool gets a bar. A provider can meter several
          limits at once, and showing only the one that binds
          hides the others entirely -- an account has been seen
          with its account wide pool idle and a feature pool at
          a hundred, where the single bar shown was the idle
          one. */}
      <ul className="pools">
        {provider.windows.map((window) => {
          const binds = Boolean(binding) && window.label === binding?.label;
          return (
            <li key={window.label} className={binds ? 'pool pool--binds' : 'pool'}>
              <div className="pool__head">
                <span className="pool__label">
                  {window.label}
                  {binds ? <span className="pool__binds">binds</span> : null}
                </span>
                <span className="pool__percent">{window.used_percent.toFixed(1)}%</span>
              </div>
              <div className="track">
                <div
                  className={`fill fill--${toneFor(window.used_percent)}`}
                  style={{ width: `${Math.min(100, Math.max(0, window.used_percent))}%` }}
                />
              </div>
              <div className="pool__reset">
                resets in {formatDuration(window.resets_in_seconds)}
              </div>
            </li>
          );
        })}
        {/* Credits sit with the limits rather than in the
            facts below, because the provider's own usage page
            shows them as one more thing you can run out of,
            beside the pools. */}
        <li className="pool pool--credits">
          <div className="pool__head">
            <span className="pool__label">credits</span>
            <span className="pool__percent">
              {isSpendingNow(provider.credits) ? (
                <span className="spend">spending now</span>
              ) : isFallbackGone(provider.credits) ? (
                <span className="spent">used up</span>
              ) : provider.credits.state === 'unavailable' ? (
                <span className="muted">not reported</span>
              ) : (
                provider.credits.state
              )}
            </span>
          </div>
          {provider.credits.detail ? (
            <div className="pool__reset">{provider.credits.detail}</div>
          ) : null}
        </li>
      </ul>

      {/* Binding on the account pool means this card can show
          headroom while a capability cannot run at all. Saying
          which one is what keeps that from being silent. */}
      {spent.length > 0 ? (
        <p className="warning" role="status">
          Fully spent: {spent.map((window) => window.label).join(', ')}. The
          governing limit above still has room, but that capability cannot run
          until it resets.
        </p>
      ) : null}

      <dl className="facts">
        <dt>source</dt>
        <dd>{SOURCE_NOTE[provider.source] ?? provider.source}</dd>

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
