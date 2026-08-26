import "server-only";

import { readFileSync } from "node:fs";

export type DashboardHumanAuthMode = "OPAQUE" | "DUAL" | "OIDC";
export type DashboardDeploymentProfile = "LOCAL" | "EXTERNAL_VM";
type Environment = Readonly<Record<string, string | undefined>>;

export interface DashboardAuthRuntime {
  mode: DashboardHumanAuthMode;
  deploymentProfile: DashboardDeploymentProfile;
  manualOpaqueLoginEnabled: boolean;
  localOidcStackRequired: boolean;
  /**
   * `npm run dev`가 띄우는 합성 Local Identity인지 명시한다. LOCAL이라는 이유만으로
   * 임의 OIDC issuer에 개발 계정 hint를 보내지 않도록 별도 opt-in으로 둔다.
   */
  localDevelopmentIdentityEnabled: boolean;
  sessionSecret?: string;
  oidc?: {
    issuer: string;
    clientId: string;
    clientSecret: string;
  };
}

let cached: DashboardAuthRuntime | undefined;

function required(name: string, env: Environment): string {
  const value = env[name]?.trim();
  if (!value) throw new Error(`${name} 환경변수가 필요합니다.`);
  return value;
}

function readSecret(name: string, env: Environment): string {
  const path = required(name, env);
  let value: string;
  try {
    value = readFileSync(path, "utf8").trim();
  } catch (error) {
    throw new Error(`${name}이 가리키는 secret 파일을 읽을 수 없습니다.`, { cause: error });
  }
  if (value.length < 32) throw new Error(`${name} secret은 최소 32자여야 합니다.`);
  return value;
}

function httpsOrigin(name: string, env: Environment): string {
  const value = required(name, env);
  let url: URL;
  try {
    url = new URL(value);
  } catch (error) {
    throw new Error(`${name}은 유효한 URL이어야 합니다.`, { cause: error });
  }
  if (url.protocol !== "https:" || url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`${name}은 path가 없는 https origin이어야 합니다.`);
  }
  return url.origin;
}

export function parseDashboardAuthRuntime(
  env: Environment,
  readSecretFile: (name: string, env: Environment) => string = readSecret,
): DashboardAuthRuntime {
  const modeRaw = env.KSI_DASHBOARD_HUMAN_AUTH_MODE?.trim() || "OPAQUE";
  if (!(["OPAQUE", "DUAL", "OIDC"] as const).includes(modeRaw as DashboardHumanAuthMode)) {
    throw new Error("KSI_DASHBOARD_HUMAN_AUTH_MODE은 OPAQUE, DUAL, OIDC 중 하나여야 합니다.");
  }
  const profileRaw = env.KSI_DASHBOARD_DEPLOYMENT_PROFILE?.trim() || "LOCAL";
  if (!(["LOCAL", "EXTERNAL_VM"] as const).includes(profileRaw as DashboardDeploymentProfile)) {
    throw new Error("KSI_DASHBOARD_DEPLOYMENT_PROFILE은 LOCAL 또는 EXTERNAL_VM이어야 합니다.");
  }
  const mode = modeRaw as DashboardHumanAuthMode;
  const deploymentProfile = profileRaw as DashboardDeploymentProfile;
  const localDevelopmentIdentityRequested = env.KSI_DASHBOARD_LOCAL_IDENTITY_ENABLED === "1";

  if (deploymentProfile === "EXTERNAL_VM") {
    if (mode !== "OIDC") {
      throw new Error("EXTERNAL_VM profile은 OIDC 사람 인증만 허용합니다.");
    }
    httpsOrigin("KSI_DASHBOARD_PUBLIC_APP_ORIGIN", env);
    httpsOrigin("KSI_DASHBOARD_PUBLIC_API_ORIGIN", env);
  }

  const usesOidc = mode === "OIDC" || mode === "DUAL";
  if (localDevelopmentIdentityRequested && (deploymentProfile !== "LOCAL" || !usesOidc)) {
    throw new Error("KSI_DASHBOARD_LOCAL_IDENTITY_ENABLED는 LOCAL OIDC 개발 stack에서만 허용합니다.");
  }
  const sessionSecret = usesOidc
    ? readSecretFile("KSI_DASHBOARD_SESSION_SECRET_FILE", env)
    : undefined;
  const oidc = usesOidc
    ? {
        issuer: required("KSI_DASHBOARD_OIDC_ISSUER", env),
        clientId: required("KSI_DASHBOARD_OIDC_CLIENT_ID", env),
        clientSecret: readSecretFile("KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE", env),
      }
    : undefined;
  if (deploymentProfile === "EXTERNAL_VM" && oidc && !oidc.issuer.startsWith("https://")) {
    throw new Error("외부 VM OIDC issuer는 https URL이어야 합니다.");
  }

  return {
    mode,
    deploymentProfile,
    // `npm run dev`는 항상 local OIDC stack을 띄운다. OPAQUE는 장비·워커 자격과
    // 사람이 같은 길을 쓰던 과거 migration 경로이므로 필요한 조사에서만 명시적으로
    // 연다. 평상시 로컬 화면에서 Bearer 입력을 보이면 상용 UX와 다른 테스트가 된다.
    manualOpaqueLoginEnabled:
      deploymentProfile === "LOCAL" &&
      mode !== "OIDC" &&
      env.KSI_DASHBOARD_LEGACY_OPAQUE_LOGIN_ENABLED === "1",
    localOidcStackRequired:
      deploymentProfile === "LOCAL" &&
      !usesOidc &&
      env.KSI_DASHBOARD_LEGACY_OPAQUE_LOGIN_ENABLED !== "1",
    localDevelopmentIdentityEnabled:
      localDevelopmentIdentityRequested && deploymentProfile === "LOCAL" && usesOidc,
    sessionSecret,
    oidc,
  };
}

export function getDashboardAuthRuntime(): DashboardAuthRuntime {
  cached ??= parseDashboardAuthRuntime(process.env);
  return cached;
}
