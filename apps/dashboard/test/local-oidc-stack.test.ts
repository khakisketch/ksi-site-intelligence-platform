import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

describe("standard local development entrypoint", () => {
  it("starts the local OIDC stack instead of a bearer-token Dashboard", () => {
    const packageJson = JSON.parse(readFileSync(join(process.cwd(), "package.json"), "utf8")) as {
      scripts: Record<string, string>;
    };
    const stack = readFileSync(join(process.cwd(), "scripts/run-local-oidc-stack.mjs"), "utf8");
    const userService = readFileSync(
      join(process.cwd(), "..", "..", "deploy", "systemd", "ksi-operations-console-dev.service"),
      "utf8",
    );

    expect(packageJson.scripts.dev).toBe(
      "node scripts/run-local-oidc-stack.mjs --tailscale required",
    );
    expect(packageJson.scripts["dev:local"]).toBe(
      "node scripts/run-local-oidc-stack.mjs --tailscale disabled",
    );
    expect(packageJson.scripts["dev:dashboard"]).toBe("next dev");
    expect(stack).toContain("KSI_DASHBOARD_HUMAN_AUTH_MODE: \"OIDC\"");
    expect(stack).toContain("KSI_DASHBOARD_LOCAL_IDENTITY_ENABLED: \"1\"");
    expect(stack).toContain('"--human-auth-mode",\n      "OIDC"');
    expect(stack).toContain("tools/run_local_oidc_issuer.py");
    expect(stack).toContain('["serve", `--http=${port}`, "--bg", "--yes", target]');
    expect(stack).toContain('"--allow-tailnet-origin"');
    expect(stack).toContain("KSI_DASHBOARD_ALLOWED_DEV_ORIGINS");
    expect(userService).toContain("ExecStart=/usr/bin/env npm run dev");
    expect(userService).toContain("Restart=on-failure");
    expect(userService).not.toContain("0.0.0.0");
  });
});
