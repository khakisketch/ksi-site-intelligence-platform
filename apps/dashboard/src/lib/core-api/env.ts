import "server-only";

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set — copy .env.local.example to .env.local (see scripts/run_core_dev.py output for a dev token)`,
    );
  }
  return value;
}

export function coreApiBaseUrl(): string {
  return requireEnv("CORE_API_BASE_URL").replace(/\/+$/, "");
}
