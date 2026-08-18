import type { Provider } from '../types';

/** What answered, what did not, and how each was obtained. */
export function Health({ providers }: { providers: Provider[] }) {
  const answered = providers.filter((provider) => provider.answered);
  const scraped = answered.filter((provider) => provider.source !== 'api');
  const notLive = answered.filter((provider) => provider.freshness !== 'live');

  return (
    <section className="health">
      <h2>Collection health</h2>
      <p>
        <strong>
          {answered.length} of {providers.length}
        </strong>{' '}
        providers answered.
      </p>
      {scraped.length > 0 ? (
        <p className="muted">
          Read through a browser rather than an API:{' '}
          {scraped.map((provider) => provider.provider).join(', ')}. A scraped
          reading is less precise than one the provider served.
        </p>
      ) : null}
      {notLive.length > 0 ? (
        <p className="muted">
          Not current:{' '}
          {notLive
            .map((provider) => `${provider.provider} (${provider.freshness})`)
            .join(', ')}
          . Run collect for a fresh reading.
        </p>
      ) : null}
      <table className="health__table">
        <thead>
          <tr>
            <th>provider</th>
            <th>answered</th>
            <th>source</th>
            <th>freshness</th>
            <th>adapter</th>
          </tr>
        </thead>
        <tbody>
          {providers.map((provider) => (
            <tr key={provider.provider}>
              <td>{provider.provider}</td>
              <td>
                {provider.answered ? (
                  'yes'
                ) : (
                  <code className="muted">{provider.error ?? 'no_reading'}</code>
                )}
              </td>
              <td>{provider.answered ? provider.source : '—'}</td>
              <td>{provider.answered ? provider.freshness : '—'}</td>
              <td>{provider.answered ? `v${provider.adapter_version}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
