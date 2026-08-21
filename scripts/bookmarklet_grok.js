/*
 * Carry this page's usage to the agent-usage dashboard.
 *
 * Runs on grok.com, in the browser you are already signed in
 * to. That is the whole point: the endpoint below refuses an
 * API token ("Action cannot be performed by OAuth2 token
 * users"), and the automated browser this tool would otherwise
 * drive is blocked by bot protection at the sign in domain. A
 * page can always read its own origin, so the one place this
 * measurement is reachable is here.
 *
 * The reading travels in the URL fragment. A fragment is never
 * sent to a server, so nothing here crosses an origin and this
 * script holds no secret: the dashboard is behind its own sign
 * in, and it hands the reading on with the session you already
 * have there.
 *
 * Built into a javascript: URL by scripts/make_bookmarklet.py,
 * which injects DASHBOARD.
 */
(async function () {
  const DASHBOARD = "__DASHBOARD__";

  const stop = (message) => {
    // Nowhere to render on a page we do not own, and an alert
    // would block the tab. The console is the honest channel.
    // eslint-disable-next-line no-console
    console.log("[agent-usage] " + message);
  };

  if (!location.hostname.endsWith("grok.com")) {
    stop("run this on grok.com, not " + location.hostname);
    return;
  }

  let body;
  try {
    const response = await fetch("/rest/rate-limits", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ requestKind: "DEFAULT" }),
    });
    body = await response.json();
  } catch (error) {
    stop("could not read the allowance: " + error);
    return;
  }

  // Signed out, this endpoint says so rather than returning a
  // usable allowance. Handing that in as a reading would
  // report an anonymous handful of queries as though it were
  // the account's, so it is carried over as what it is.
  const reading =
    body && body.code === 16
      ? { provider: "grok", answered: false, error: "browser_session_missing" }
      : measurement(body);

  if (reading === null) {
    stop("the allowance did not parse: " + JSON.stringify(body).slice(0, 200));
    return;
  }

  location.href =
    DASHBOARD.replace(/\/$/, "") +
    "/#reading=" +
    encodeURIComponent(JSON.stringify(reading));

  function measurement(payload) {
    const total = Number(payload && payload.totalQueries);
    const remaining = Number(payload && payload.remainingQueries);
    const seconds = Number(payload && payload.windowSizeSeconds);
    if (!isFinite(total) || total <= 0 || !isFinite(remaining)) return null;

    const hours = seconds / 3600;
    const label =
      isFinite(hours) && hours >= 1
        ? hours + "-hour"
        : Math.round(seconds / 60) + "-minute";

    return {
      provider: "grok",
      answered: true,
      windows: [
        {
          label: label,
          // Percent consumed, never remaining. The provider
          // reports what is left, so it is converted here
          // rather than leaving every reader to guess which
          // one it is.
          used_percent: ((total - remaining) / total) * 100,
          remaining: remaining,
          limit: total,
          scope: "account",
        },
      ],
    };
  }
})();
