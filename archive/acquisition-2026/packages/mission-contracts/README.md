# packages/mission-contracts

Mission Contract and policy contracts.

## Neutral site frame compatibility (Task 3)

`SiteFrame` is no longer defined here: the canonical owner is
`ksi_event_contracts.site_frame.SiteFrame` and this package re-exports the same
class, so existing `ksi_mission_contracts.models.SiteFrame` imports keep working
with identical wire/schema/validation. This adds a `ksi-event-contracts`
workspace dependency to this package.

## Execution consumer

`ksi-mission-contract-consumer` is the fail-closed execution boundary for Mission
Contract v1.2. It loads a public-key-only registry, validates structure, Ed25519
signature, key status, and TTL through `load_verified_contract`, and atomically
replaces the local active contract only after a `VALID` verdict.

```bash
ksi-mission-contract-consumer \
  --keys-dir /etc/ksi/mission-verification-keys \
  --state-dir /var/lib/ksi/mission-contract \
  activate mission-contract.json

ksi-mission-contract-consumer \
  --keys-dir /etc/ksi/mission-verification-keys \
  --state-dir /var/lib/ksi/mission-contract \
  status
```

An invalid candidate exits `2` and never replaces the previous active contract.
Configuration or local I/O failure exits `3`. A valid activation/status exits `0`.
The public key directory must contain `keys.json` and `<keyId>.public.pem`; no
private key belongs on the execution consumer. The state directory must be a
real directory owned by the consumer process user with no group/other access
(`0700`); active contracts are written as `0600` files.

## Edge dispatch sync companion

`ksi-edge-dispatch-sync` is a one-shot, activation-time control-plane companion:
it pulls only `GET /v1/edge-sync/missions/next`, gives the exact bounded JSON
bytes to the existing dispatch verifier, and posts that verifier's exact
`ActivationReceiptV1` to the matching receipt route. It is not a PSDK callback,
native frame/safety-loop process, or DJI flight-control client.

```bash
ksi-edge-dispatch-sync \
  --core-base-url https://<core_origin> \
  --tls-ca-bundle <reviewed_ca_bundle> \
  --core-spki-pin sha256//<core_spki_pin> \
  --bearer-token-file <private_0600_edge_token> \
  --keys-dir <public_verification_key_directory> \
  --state-dir <private_0700_activation_state_directory> \
  --edge-device-id <device_id> \
  --runtime-version <runtime_version>
```

The command requires an HTTPS origin, supplied CA bundle, exact SPKI pin,
owner-only regular token file, private state directory, and bounded responses.
It never follows redirects or emits the token or dispatch body. `204` means no
mission. If receipt delivery fails, a verified local activation remains valid;
a supervised later invocation retries the same still-pending Core dispatch
idempotently.

This package requires Python 3.12. The stock Manifold 3 Python 3.8 environment
cannot run it, and the current `.dpk` packages only the native executable. A
live activation-enabled deployment therefore needs a separately reviewed,
non-frame-loop Python 3.12 companion with access to the exact private native
handoff directory (or an equivalently atomic, approved handoff). That deployment
and its permissions/TLS evidence are HIL gates, not established by this CLI's
software tests.
