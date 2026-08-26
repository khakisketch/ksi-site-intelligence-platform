import { readFileSync } from "node:fs";

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} 환경변수가 필요합니다.`);
  return value;
}

function httpsOrigin(name) {
  const value = required(name);
  const url = new URL(value);
  if (url.protocol !== "https:" || url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`${name}은 path가 없는 https origin이어야 합니다.`);
  }
}

function secretFile(name) {
  const path = required(name);
  const secret = readFileSync(path, "utf8").trim();
  if (secret.length < 32) throw new Error(`${name} secret은 최소 32자여야 합니다.`);
}

function validateExternalVm() {
  if (process.env.KSI_DASHBOARD_HUMAN_AUTH_MODE?.trim() !== "OIDC") {
    throw new Error("EXTERNAL_VM profile은 OIDC 사람 인증만 허용합니다.");
  }
  httpsOrigin("KSI_DASHBOARD_PUBLIC_APP_ORIGIN");
  httpsOrigin("KSI_DASHBOARD_PUBLIC_API_ORIGIN");
  const issuer = new URL(required("KSI_DASHBOARD_OIDC_ISSUER"));
  if (issuer.protocol !== "https:") {
    throw new Error("외부 VM OIDC issuer는 https URL이어야 합니다.");
  }
  required("KSI_DASHBOARD_OIDC_CLIENT_ID");
  secretFile("KSI_DASHBOARD_SESSION_SECRET_FILE");
  secretFile("KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE");
}

const profile = process.env.KSI_DASHBOARD_DEPLOYMENT_PROFILE?.trim() || "LOCAL";
if (profile === "EXTERNAL_VM") validateExternalVm();
else if (profile !== "LOCAL") {
  throw new Error("KSI_DASHBOARD_DEPLOYMENT_PROFILE은 LOCAL 또는 EXTERNAL_VM이어야 합니다.");
}

await import("../server.js");
