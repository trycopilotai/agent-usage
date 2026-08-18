import type { Provider } from '../types';
import { headroomOrder } from '../types';

/** Where to send work now, and who was excluded and why. */
export function Headroom({ providers }: { providers: Provider[] }) {
  const ranked = headroomOrder(providers);
  const silent = providers.filter((provider) => !provider.answered);
  const capped = providers.filter(
    (provider) => provider.answered && provider.credits.state === 'exhausted',
  );

  return (
    <section className="headroom">
      <h2>Where there is headroom</h2>
      {ranked.length === 0 ? (
        <p className="muted">
          No provider reported a limit, so there is nothing to rank.
        </p>
      ) : (
        <ol>
          {ranked.map((provider) => (
            <li key={provider.provider}>
              <strong>{provider.provider}</strong>{' '}
              {(provider.binding_window as { used_percent: number }).used_percent.toFixed(
                1,
              )}
              % used
              {provider.credits.state === 'exhausted' ? (
                <span className="muted"> — no paid fallback left</span>
              ) : null}
            </li>
          ))}
        </ol>
      )}
      {silent.length > 0 ? (
        <p className="muted">
          Not ranked because they did not answer:{' '}
          {silent.map((provider) => provider.provider).join(', ')}. That is
          unknown headroom, not full headroom.
        </p>
      ) : null}
      {capped.length > 0 ? (
        <p className="muted">
          Paid allowance used up:{' '}
          {capped.map((provider) => provider.provider).join(', ')}.
        </p>
      ) : null}
    </section>
  );
}
