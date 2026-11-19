# Spatial workspace restoration and review contract

Use the [current Console contract](CONSOLE_CURRENT_SPEC.md). Material version, observation, evidence, result and selected purpose remain independent. Restore only an exact authorized selection. Missing, expired or wrong-purpose evidence must remain explicit.

## 9. Acceptance scenarios for the delivered workspace

These SWX cases refine UI acceptance, not replace product acceptance or existing tests:

1. **Ordinary entry:** a later registered but older capture does not displace the latest view-available
   observation; chronological ambiguity and date-only/unknown values are labelled honestly.
2. **Correction:** D1 result remains unchanged after D2 registration/validation; a new comparison
   explicitly selecting D2 has distinct bound inputs and the appropriate calculation identity.
3. **Explicit resume:** open a saved comparison or result after newer uploads; exact original inputs,
   area and context return. An unavailable input is explained, never replaced silently.
4. **Explore → Compare → Results → Back:** same selected area, two exact versions, supported spatial
   extent and layer context; viewport changes never alter the run polygon.
5. **Compare:** equal map emphasis at actual desktop/phone viewports, consistent scales/legend and
   valid/excluded regions; unsupported common display mapping is not faked.
6. **No data vs cannot display.** In single-observation Explore, a reader can still see the inspected
   file outline when the preparation history is temporarily unavailable. Draw a work-area boundary
   only on a matching native coordinate plane. Label the outline as geometry and offer a history
   retry. Display pixels only after the authorized output has passed the receipt checks.
7. **Rights lifecycle:** actor/org/Site/WorkArea limits, byte access/cache, revocation/expiry and
   requester ownership enforced. Mobile reading creates no hidden mutation.
8. **Same result externally:** authorized external consumer and Web resolve the exact immutable
   result/inputs/conditions/evidence. Dynamic current-use differences are explained. This passes A,
   not automatically reproduction verification B.
9. **Understandable entry:** a first viewer can identify Site, selected capture, available layer,
   visible area and the next useful action without reading processing jargon. The first viewport
   contains authorized spatial content or a specific recovery action. With an empty preparation
   history, an authorized requester can open the displayed file in Materials and select a bounded
   window on its inspected grid or enter exact row and column values. Only explicit submission
   creates a request. Its status link opens that exact request in the same site and work area.

For the public Floreat dog beach observations, register the published capture dates and retain the
original files. Cambridge Coastcare identifies this sector as Flight-3 on 17 August 2021 and
Flight-4 on 24 August 2022. Both DSMs are distributed under CC BY 4.0.
[DataWA 2021 Flight-3 DSM](https://catalogue.data.wa.gov.au/dataset/floreat-f3-raster-dsm-geotiff-aug-2021)
and [DataWA 2022 Flight-4 DSM](https://catalogue.data.wa.gov.au/dataset/floreat-f4-raster-dsm-geotiff-aug-2022).

Use date-only observations with unknown vertical reference for viewing and blocked-calculation cases. Use an independently
identified supported synthetic case for numeric workflows. Keep each result bound to its source.
Customer and field acceptance require their own evidence. Corrections use a new record.

The unresolved shared inspection-history incident requires authorized operator recovery before relying on its journal. An old local receipt does not grant current preparation, live inspection, rights, retention or production acceptance.
