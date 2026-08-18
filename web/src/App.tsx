import { Headroom } from './components/Headroom';
import { Health } from './components/Health';
import { HistoryChart } from './components/HistoryChart';
import { ProviderCard } from './components/ProviderCard';
import { useUsage } from './hooks/useUsage';

function ago(seconds: number): string {
  const delta = Math.max(0, Math.floor(Date.now() / 1000 - seconds));
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  return `${Math.floor(delta / 3600)}h ago`;
}

export function App() {
  const { snapshot, forecasts, histories, error, loading, refresh } = useUsage();

  return (
    <main className="page">
      <header className="page__header">
        <h1>agent-usage</h1>
        <p className="page__lede">
          How much of each provider limit is used, when it resets, and where
          there is headroom.
        </p>
        <button type="button" onClick={refresh} className="refresh">
          Refresh
        </button>
      </header>

      {error ? (
        <p className="error">
          The API did not answer: {error}. This page reads a local service;
          start it with <code>agent-usage serve</code>.
        </p>
      ) : null}

      {loading && !snapshot ? <p className="muted">Reading…</p> : null}

      {snapshot ? (
        <>
          <p className="muted generated">
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
