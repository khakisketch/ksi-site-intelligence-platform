# packages/mission-contracts

Mission Contract and policy contracts.

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
