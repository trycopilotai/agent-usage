/*
 * Hand this page's usage to agent-usage.
 *
 * Runs on grok.com, in the browser you are already signed in
 * to. That is the whole point: the endpoint below refuses an
 * API token ("Action cannot be performed by OAuth2 token
 * users"), and the automated browser this tool would otherwise
 * drive is blocked by bot protection at the sign in domain. A
 * page can always read its own origin, so the one place this
 * measurement is reachable is here.
 *
 * The fetch is same origin, so the session cookie rides along
 * and CORS never enters into it. Only the POST is cross origin,
 * and that goes to a route the operator opened on purpose.
 *
 * Built into a javascript: URL by scripts/make_bookmarklet.py,
 * which injects ENDPOINT and TOKEN. Do not paste a token in
 * here by hand and commit it.
 */
(async function () {
  const ENDPOINT = "__ENDPOINT__";
  const TOKEN = "__TOKEN__";

  const say = (message) => {
    // eslint-disable-next-line no-console
    console.log("[agent-usage] " + message);
  };

  if (!location.hostname.endsWith("grok.com")) {
    say("run this on grok.com, not " + location.hostname);
    return;
  }

  let body;
  try {
    const response = await fetch("/rest/rate-limits", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ requestKind: "DEFAULT", modelName: "grok-4" }),
    });
    body = await response.json();
  } catch (error) {
    say("could not read the allowance: " + error);
    return;
  }

  // Signed out, this endpoint says so rather than returning a
  // usable allowance. Handing that in as a reading would report
  // an anonymous handful of queries as though it were the
  // account's, so it is reported as what it is.
  if (body && body.code === 16) {
    await hand({ provider: "grok", answered: false, error: "browser_session_missing" });
    say("not signed in; reported the session as missing");
    return;
  }

  const total = Number(body && body.totalQueries);
  const remaining = Number(body && body.remainingQueries);
  const seconds = Number(body && body.windowSizeSeconds);
  if (!isFinite(total) || total <= 0 || !isFinite(remaining)) {
    say("the allowance did not parse: " + JSON.stringify(body).slice(0, 200));
    return;
  }

  const hours = seconds / 3600;
  const label = hours >= 1 ? hours + "-hour" : Math.round(seconds / 60) + "-minute";

  await hand({
    provider: "grok",
    answered: true,
    windows: [
      {
        label: label,
        // Percent consumed, never remaining. The provider
        // reports what is left, so it is converted here rather
        // than leaving every reader to guess which one it is.
        used_percent: ((total - remaining) / total) * 100,
        remaining: remaining,
        limit: total,
        scope: "account",
      },
    ],
  });

  async function hand(document) {
    try {
      const response = await fetch(ENDPOINT, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: "Bearer " + TOKEN,
        },
        body: JSON.stringify(document),
      });
      if (response.ok) {
        say("stored: " + JSON.stringify(document.windows || document.error));
      } else {
        const detail = await response.text();
        say("refused (" + response.status + "): " + detail.trim());
      }
    } catch (error) {
      say("could not reach agent-usage: " + error);
    }
  }
})();
