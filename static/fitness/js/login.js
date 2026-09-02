// Wires the /fitness/login page: maps ?error= to a readable message and
// forwards ?next= onto the "Continue with Google" link so a visitor who
// hit a gated page lands back there after signing in.

const ERROR_MESSAGES = {
  denied: "Sign-in was cancelled.",
  state: "That sign-in link expired. Try again.",
  auth_failed: "Google could not complete the sign-in. Try again.",
  not_allowed: "That Google account is not on this app's allowlist.",
  not_configured: "Sign-in is not configured yet: no allowed accounts are set.",
  session_expired: "Your session expired. Sign in again.",
};

function init() {
  const params = new URLSearchParams(window.location.search);
  const errorCode = params.get("error");
  const errorEl = document.getElementById("login-error");
  if (errorCode && errorEl) {
    // textContent, never innerHTML - errorCode comes straight from the URL.
    errorEl.textContent = ERROR_MESSAGES[errorCode] || "Sign-in failed. Try again.";
  }

  const nextPath = params.get("next");
  const signinLink = document.getElementById("signin");
  if (nextPath && signinLink) {
    const url = new URL(signinLink.href, window.location.origin);
    url.searchParams.set("next", nextPath);
    signinLink.href = url.pathname + url.search;
  }
}

init();
