import type { DashboardAuthRuntime } from "./runtime";

export type OidcLoginIntent = "default" | "role-test";

const DEFAULT_DEVELOPMENT_PRINCIPAL_ID = "local-admin";

/**
 * Only the explicitly marked Local Identity fixture receives these parameters.
 * An external IdP must never receive a synthetic principal id or a development
 * account-picker prompt merely because the Dashboard happens to run locally.
 */
export function oidcAuthorizationParams(
  runtime: DashboardAuthRuntime,
  intent: OidcLoginIntent,
): Record<string, string> {
  if (!runtime.localDevelopmentIdentityEnabled) return {};
  if (intent === "role-test") return { prompt: "select_account" };
  return { login_hint: DEFAULT_DEVELOPMENT_PRINCIPAL_ID };
}

export function oidcLoginIntent(value: FormDataEntryValue | null): OidcLoginIntent {
  return value === "role-test" ? "role-test" : "default";
}
