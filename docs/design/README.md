# Implementation design contracts

Despite the historical directory name, these files are not visual-design assets. They document
cross-module semantic and atomicity contracts used during implementation review:

- `CAPABILITY_SEMANTIC_CONTRACT.md`
- `MISSION_ISSUANCE_ATOMICITY_CONTRACT.md`
- `WORKER_LEASE_IDENTITY_CONTRACT.md`

Product requirements remain in `../product/`, language-neutral runtime schemas in `../../contracts/`,
and accepted architecture decisions in `../architecture/`. Moving these files to a clearer architecture
subdirectory is an R3 documentation candidate because existing links must first be inventoried.
