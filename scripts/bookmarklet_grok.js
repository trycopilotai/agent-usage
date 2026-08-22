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

  // The allowance is keyed by model, not by account. Reading
  // one model and calling the answer "grok" would report the
  // wrong pool: measured on one signed in account these came
  // back 400, 140 and 20 queries per two hours. So each is
  // carried as its own window, named after the model it
  // governs.
  //
  // A model this account cannot reach answers "Model not
  // found", and is skipped rather than failing the whole
  // reading, which is what lets this list cover more than one
  // plan.
  const MODELS = ["grok-4", "grok-3", "grok-4-heavy"];

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

  const windows = [];
  let signedOut = false;
  let lastBody = null;

  for (const model of MODELS) {
    let body;
    try {
      const response = await fetch("/rest/rate-limits", {
        method: "POST",
        headers: { "content-type": "application/json" },
        credentials: "include",
        // modelName, not requestKind. The endpoint keys the
        // allowance by model, and answers a request without
        // one with "Model not found" -- which is what every
        // requestKind got.
        body: JSON.stringify({ modelName: model }),
      });
      body = await response.json();
    } catch (error) {
      stop("could not read the allowance for " + model + ": " + error);
      return;
    }
    lastBody = body;

    // Signed out, this endpoint says so rather than returning
    // a usable allowance. Handing that in as a reading would
    // report an anonymous handful of queries as though it were
    // the account's, so it is carried over as what it is.
    if (body && body.code === 16) {
      signedOut = true;
      break;
    }
    // A model this plan does not include. Not a failure.
    if (body && body.code === 5) {
      continue;
    }

    const measured = measurement(model, body);
    if (measured !== null) {
      windows.push(measured);
    }
  }

  let reading;
  if (signedOut) {
    reading = {
      provider: "grok",
      answered: false,
      error: "browser_session_missing",
    };
  } else if (windows.length > 0) {
    reading = { provider: "grok", answered: true, windows: windows };
  } else {
    // Missing is never zero. No window means no reading, not a
    // provider sitting at nothing used.
    stop("no allowance parsed: " + JSON.stringify(lastBody).slice(0, 200));
    return;
  }

  location.href =
    DASHBOARD.replace(/\/$/, "") +
    "/#reading=" +
    encodeURIComponent(JSON.stringify(reading));

  function measurement(model, payload) {
    const total = Number(payload && payload.totalQueries);
    const remaining = Number(payload && payload.remainingQueries);
    const seconds = Number(payload && payload.windowSizeSeconds);
    if (!isFinite(total) || total <= 0 || !isFinite(remaining)) return null;

    const hours = seconds / 3600;
    const duration =
      isFinite(hours) && hours >= 1
        ? hours + "-hour"
        : Math.round(seconds / 60) + "-minute";

    return {
      // Named the way every other per-capability pool is: the
      // thing it governs, then the window it governs it over.
      label: model + " " + duration,
      // Percent consumed, never remaining. The provider
      // reports what is left, so it is converted here rather
      // than leaving every reader to guess which one it is.
      used_percent: ((total - remaining) / total) * 100,
      remaining: remaining,
      limit: total,
      // Feature, not account. There is no account-wide grok
      // pool: every window here belongs to one model, so none
      // of them governs the provider overall.
      scope: "feature",
    };
  }
})();
