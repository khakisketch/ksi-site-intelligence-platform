# Codex Global Configuration Audit

Date: 2026-08-19
Status: complete, read-only

Requirement IDs:
- DEVEX-CODEX-CONFIG-AUDIT-2026-08-19 (operational audit; no product requirement ID)

Owner module:
- Local Codex user configuration (`/home/ksi/.codex/config.toml`) and applicable configuration layers.

Acceptance criteria:
- Identify the effective local configuration layers and any managed policy that can affect model selection.
- Determine whether local configuration can explain the absence of `gpt-5.6-sol` from `/model`.
- Report safe, evidence-backed improvements without changing global settings.

Contracts affected:
- None. This audit changes neither product contracts nor runtime behavior.

Reference assets:
- Official OpenAI Docs: Codex Config Basics and Configuration Reference.
- This repository's `AGENTS.md` and authority documents.

Adoption decisions:
- `REFERENCE_ONLY`: official Codex documentation informs the audit; no runtime code or configuration is adopted or changed.

Files to change:
- This audit artifact only. No source, contracts, or global configuration files will be edited.

Tests:
- Read-only inspection of active configuration layers, client version, and model-related configuration fields.

HIL or real-device assumptions:
- None.

License/data implications:
- No customer, production, credential, or model-request data is read or changed. Configuration values that could contain secrets are redacted during inspection.

Rollback:
- Remove this audit artifact if it is no longer desired. No configuration changes have been made.

Domain invariants:
- None directly affected: this is a developer-tooling audit and does not change product runtime behavior.

## Evidence summary

- `codex-cli 0.148.0` is installed consistently; `codex --strict-config --help` accepts every active user-config key.
- The effective configuration is the user layer only. There is no project `.codex/config.toml`, no user or system `requirements.toml`, and no `/etc/codex/config.toml`.
- No `CODEX_PROFILE`, model-config path, OpenAI base-URL override, or API-key environment override is present. The only custom catalog is owned by the inactive `ollama-launch` profile.
- `codex doctor --summary` reports a configured authentication method, reachable active provider endpoints, restricted filesystem/network sandboxing, `OnRequest` approvals, and no warning or failure.
- `model = "gpt-5.6-terra"` sets the default model only. The active config has neither `model_catalog_json` nor `model_provider`, so it does not locally pin a catalog or switch away from the built-in OpenAI provider.
- `tui.model_availability_nux."gpt-5.6-sol" = 3` is documented as internal tooltip state, not an availability allow-list.
- Therefore, the absent Sol entry is not explained by the inspectable local configuration. It remains a service-side account/workspace model-catalog entitlement or rollout condition.

## Findings and recommendations

1. **No local cause for missing Sol — do not add `gpt-5.6-sol` or `gpt-5.6` to config.** A default-model override cannot grant catalog access and would cause new sessions to fail until service-side access exists. Re-test only after the account catalog changes.
2. **Tune globally pinned `xhigh` reasoning unless every task merits it.** Both normal and Plan mode use `xhigh`. This is valid, but it increases latency and quota use for ordinary work and conflicts with the repository guidance to reserve `xhigh` for failed gates or high-risk ambiguity. Prefer `high` globally and choose `xhigh` per difficult task.
3. **Make the current safe execution behavior explicit.** The effective policy is `OnRequest` with restricted filesystem/network access, but neither `approval_policy` nor `sandbox_mode` is pinned in user config. Pinning `on-request` and `workspace-write` improves upgrade-to-upgrade predictability; use a separate explicit profile for exceptional full-access work.
4. **Review memory retention deliberately.** Memories are enabled and generated, while external-context threads are excluded. This is privacy-aware, but local-only coding threads still become memory inputs. For sensitive customer, credential, or incident work, disable memory generation for the relevant profile; otherwise raise `min_rate_limit_remaining_percent` from `20` to the documented default `25` to preserve more quota headroom.
5. **Keep hooks disabled or secure them before enabling.** Hooks are currently disabled, so the existing hook state is inert. `/home/ksi/.codex/hooks.json` is group-writable (`0664`); audit it and restrict it to `0600` before enabling lifecycle hooks.
6. **Clean up only if intentional.** The enabled GitHub plugin is the sole active plugin. `approvals_reviewer = "user"` sends eligible approval prompts to the user, but does not itself define every plugin tool's approval mode. The disabled Google Calendar, Gmail, and Canva plugin installations are not active but can be removed if unused. The `/home/ksi` trust entry should be retained only if Codex is intentionally run with that directory as a trusted project; project-specific trust entries are clearer.

## No-change confirmations

- Global `config.toml`, credential file, and history file have owner-only `0600` permissions.
- The inactive Ollama profile does not influence the current OpenAI-backed session.
- No MCP server is configured.
- Update checks are not disabled, and the client reports update configuration as consistent.
