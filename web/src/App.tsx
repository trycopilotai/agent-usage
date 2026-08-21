import { Headroom } from './components/Headroom';
import { Health } from './components/Health';
import { HistoryChart } from './components/HistoryChart';
import { ProviderCard } from './components/ProviderCard';
import { handoffMessage, useHandoff } from './hooks/useHandoff';
import { useUsage } from './hooks/useUsage';

function ago(seconds: number): string {
  const delta = Math.max(0, Math.floor(Date.now() / 1000 - seconds));
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  return `${Math.floor(delta / 3600)}h ago`;
}

/** What the reader can do about a failure, in their situation. */
function errorAdvice(kind: string): string {
  if (kind === 'auth') {
    return 'The session has expired. Reload the page to sign in again.';
  }
  if (kind === 'timeout') {
    return 'The service took too long to answer. It is running; try again shortly.';
  }
  // Only a page served from this machine can be fixed by
  // starting a local service. Telling a hosted reader to run a
  // command sends them after a service they do not operate.
  const host = window.location.hostname;
  if (host === 'localhost' || host === '127.0.0.1' || host === '::1') {
    return 'This page reads a local service; start it with `agent-usage serve`.';
  }
  return 'The service that collects usage did not answer. This is not something to fix from this page.';
}

export function App() {
  const { snapshot, forecasts, histories, error, incomplete, loading, refresh } =
    useUsage();
  // A reading a bookmarklet carried here in the fragment. It
  // refreshes on success so the card it belongs to updates
  // without the reader wondering whether it took.
  const handoff = useHandoff(refresh);
  const handoffNote = handoffMessage(handoff);

  return (
    <main className="page">
      <header className="page__header">
        <h1>agent-usage</h1>
        <p className="page__lede">
          How much of each provider limit is used, when it resets, and where
          there is headroom.
        </p>
        <button
          type="button"
          onClick={refresh}
          className="refresh"
          aria-label="Refresh usage now"
        >
          Refresh
        </button>
      </header>

      {handoffNote ? (
        <p
          className={handoff.status === 'refused' ? 'error' : 'handoff'}
          role="status"
        >
          {handoffNote}
        </p>
      ) : null}

      {error ? (
        <p className="error" role="alert">
          {errorAdvice(error.kind)} <span className="muted">({error.message})</span>
        </p>
      ) : null}

      {incomplete.length > 0 ? (
        <p className="warning" role="status">
          Forecast or history is missing for {incomplete.join(', ')}. The usage
          figures below are still current.
        </p>
      ) : null}

      {loading && !snapshot ? <p className="muted">Reading…</p> : null}

      {snapshot ? (
        <>
          <p className="muted generated" role="status" aria-live="polite">
            Snapshot generated {ago(snapshot.generated_at)}. Every number below
            was reported by the provider it belongs to.
          </p>

          <Headroom providers={snapshot.providers} />

          <section>
            <h2>Providers</h2>
            <div className="cards">
              {snapshot.providers.map((provider) => (
                <div className="cardslot" key={provider.provider}>
                  <ProviderCard
                    provider={provider}
                    forecast={forecasts[provider.provider] ?? null}
                  />
                  {provider.answered ? (
                    <HistoryChart
                      label={provider.provider}
                      points={histories[provider.provider]?.points ?? []}
                    />
                  ) : null}
                </div>
              ))}
            </div>
          </section>

          <Health providers={snapshot.providers} />
        </>
      ) : null}

      <footer className="page__footer">
        <p className="muted">
          A provider that did not answer is shown as not answering, never as
          zero usage. A forecast that cannot be measured reports why instead of
          a number.
        </p>
      </footer>
    </main>
  );
}
