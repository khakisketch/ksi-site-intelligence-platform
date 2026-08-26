// Edge-safe constants shared by proxy.ts and the Node-only Auth.js configuration.
//
// Cookie scope does not include the TCP port.  A Tailnet host can therefore run
// another Auth.js application on a different port while the browser still sends
// that application's default `authjs.*` transient cookies to this Console.
// Keep every KSI cookie in its own namespace so a stale or parallel OAuth
// attempt cannot make an otherwise valid KSI callback look like a configuration
// failure.
export const AUTH_COOKIE_NAMESPACE = "ksi_auth_v1";
export const AUTH_SESSION_COOKIE_NAME = "ksi_auth_session";
export const AUTH_CALLBACK_URL_COOKIE_NAME = `${AUTH_COOKIE_NAMESPACE}_callback_url`;
export const AUTH_CSRF_COOKIE_NAME = `${AUTH_COOKIE_NAMESPACE}_csrf_token`;
export const AUTH_PKCE_COOKIE_NAME = `${AUTH_COOKIE_NAMESPACE}_pkce_code_verifier`;
export const AUTH_STATE_COOKIE_NAME = `${AUTH_COOKIE_NAMESPACE}_state`;
export const AUTH_NONCE_COOKIE_NAME = `${AUTH_COOKIE_NAMESPACE}_nonce`;
export const AUTH_WEBAUTHN_CHALLENGE_COOKIE_NAME = `${AUTH_COOKIE_NAMESPACE}_webauthn_challenge`;

export const AUTH_SESSION_MAX_AGE_SECONDS = 60 * 60 * 8;
export const AUTH_TRANSIENT_COOKIE_MAX_AGE_SECONDS = 60 * 15;

/**
 * The Auth.js defaults are intentionally recreated here with KSI-owned names.
 * These are HttpOnly transport cookies, not application-accessible identity
 * values.  `secure` remains profile-dependent: local Tailnet development is
 * plain HTTP while EXTERNAL_VM is HTTPS-only.
 */
export function authJsCookies(secure: boolean) {
  const standard = () => ({
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
    secure,
  });

  return {
    sessionToken: {
      name: AUTH_SESSION_COOKIE_NAME,
      options: standard(),
    },
    callbackUrl: {
      name: AUTH_CALLBACK_URL_COOKIE_NAME,
      options: standard(),
    },
    csrfToken: {
      name: AUTH_CSRF_COOKIE_NAME,
      options: standard(),
    },
    pkceCodeVerifier: {
      name: AUTH_PKCE_COOKIE_NAME,
      options: { ...standard(), maxAge: AUTH_TRANSIENT_COOKIE_MAX_AGE_SECONDS },
    },
    state: {
      name: AUTH_STATE_COOKIE_NAME,
      options: { ...standard(), maxAge: AUTH_TRANSIENT_COOKIE_MAX_AGE_SECONDS },
    },
    nonce: {
      name: AUTH_NONCE_COOKIE_NAME,
      options: standard(),
    },
    webauthnChallenge: {
      name: AUTH_WEBAUTHN_CHALLENGE_COOKIE_NAME,
      options: { ...standard(), maxAge: AUTH_TRANSIENT_COOKIE_MAX_AGE_SECONDS },
    },
  };
}
