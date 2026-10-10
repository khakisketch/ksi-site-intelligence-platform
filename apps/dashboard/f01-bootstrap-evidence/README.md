# F-01 bootstrap evidence routing

`verification/` holds the local synthetic D3 acceptance run for F-01 mapped Site bootstrap
(source `159698b` core + `bb1c4bf` dashboard). Read `verification/receipt.md` first; it defines
what each stage actually establishes and what was not exercised.

- The run used an isolated loopback OIDC stack (issuer 9071, Core 8071, dashboard 3235) with a
  protected v2 registry file outside the repository; the pre-existing systemd dev stack was not
  touched. All Sites/WorkAreas/users are synthetic.
- `verification/MANIFEST.sha256` hashes everything here. The 70 MB HAR stays in the scratch
  directory recorded in the receipt (`f01-flow.har.sha256` here).
- These captures are **functional acceptance evidence for the registration flow**, not a design
  review and not customer/field/deployment acceptance. The desktop-only wizard boundary is
  documented in the receipt.
