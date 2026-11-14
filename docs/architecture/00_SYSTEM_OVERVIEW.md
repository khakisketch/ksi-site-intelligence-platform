# Platform architecture boundary

[ADR-KSI-039](ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md) excludes flight and autonomous acquisition from the current platform. Their retained transitional implementation lives under `archive/acquisition-2026/`.

Core owns scoped observations, derived artifacts, acceptance, durable work and immutable evidence. The Console and external adapters project those records. Independent workers execute bounded calculations under Core authority. [Repository ownership](../../REPOSITORY_STRUCTURE.md) and [domain invariants](../product/DOMAIN_INVARIANTS.md) govern source and execution boundaries.
