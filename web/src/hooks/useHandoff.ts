import { useEffect, useState } from 'react';

import { apiBase } from './useUsage';

/*
 * Take delivery of a reading a bookmarklet carried here.
 *
 * Some providers keep subscription usage behind a session an
 * API token cannot hold, and behind bot protection an
 * automated browser cannot pass. The operator's own browser
 * can read it; the problem is getting what it saw to this
 * origin, which cannot fetch the provider itself.
 *
 * The bookmarklet puts the reading in the URL fragment. A
 * fragment is never sent to a server -- it exists only in the
 * browser -- so nothing about this crosses an origin or needs
 * a token of its own. This page is already behind whatever
 * authentication it sits behind, and it posts the reading
 * onward with the session the reader already has.
 *
 * The fragment is cleared as soon as it is read, so a reload
 * does not hand the same reading in twice and the numbers do
 * not linger in the address bar.
 */

const FRAGMENT_KEY = 'reading=';

export type HandoffState =
  | { status: 'none' }
  | { status: 'sending' }
  | { status: 'stored'; provider: string }
  | { status: 'refused'; reason: string };

/** The reading carried in the fragment, if there is one. */
export function readingFromFragment(hash: string): unknown | null {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash;
  if (!raw.startsWith(FRAGMENT_KEY)) return null;
  const encoded = raw.slice(FRAGMENT_KEY.length);
  if (!encoded) return null;
  try {
    return JSON.parse(decodeURIComponent(encoded));
  } catch {
    return null;
  }
}

export function useHandoff(onStored: () => void): HandoffState {
  const [state, setState] = useState<HandoffState>({ status: 'none' });

  useEffect(() => {
    const reading = readingFromFragment(window.location.hash);
    if (reading === null) return;

    // Cleared before the request rather than after, so a
    // failure that the reader retries by reloading does not
    // silently resend a reading they have already seen
    // refused.
    history.replaceState(null, '', window.location.pathname + window.location.search);
    setState({ status: 'sending' });

    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(`${apiBase()}/ingest`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(reading),
        });
        if (cancelled) return;
        if (response.ok) {
          const body = await response.json().catch(() => ({}));
          setState({
            status: 'stored',
            provider: String(body.stored ?? 'the provider'),
          });
          onStored();
          return;
        }
        const body = await response.json().catch(() => ({}));
        setState({
          status: 'refused',
          reason: String(body.error ?? body.message ?? response.status),
        });
      } catch {
        if (!cancelled) {
          setState({ status: 'refused', reason: 'the service could not be reached' });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // Runs once, on the load that carried the fragment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return state;
}

/** What to tell the reader, in their situation. */
export function handoffMessage(state: HandoffState): string | null {
  if (state.status === 'sending') return 'Handing over the reading from your browser…';
  if (state.status === 'stored') return `Stored the reading for ${state.provider}.`;
  if (state.status === 'refused') return `That reading was refused: ${state.reason}.`;
  return null;
}
