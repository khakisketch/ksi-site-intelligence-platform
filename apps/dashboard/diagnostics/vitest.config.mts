import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Separate from the regular passing unit-test selection.
export default defineConfig({
  resolve: { alias: {
    "@": fileURLToPath(new URL("../src", import.meta.url)),
    "server-only": fileURLToPath(new URL("../test/stubs/server-only.ts", import.meta.url)),
  } },
  test: {
    server: { deps: { inline: ["next-auth"] } },
    environment: "node",
    include: ["diagnostics/session-cookie-race.test.ts"],
  },
});
