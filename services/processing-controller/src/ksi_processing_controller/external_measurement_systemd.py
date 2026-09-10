"""Fixed V2 receipt format over the unchanged exact systemd lifecycle."""

from typing import ClassVar

from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1
from ksi_processing_controller.external_inspector_systemd import SystemdTransientSliceController
from ksi_processing_controller.external_measurement_attempts import (
    MeasurementRuntimeParentReceiptV2,
)


class MeasurementSystemdTransientSliceController(SystemdTransientSliceController):
    """Only pure receipt type/description vary; no lifecycle method is overridden."""

    _receipt_type: ClassVar[type[RuntimeParentReceiptV1]] = MeasurementRuntimeParentReceiptV2
    _description_prefix: ClassVar[str] = "ksi-external-measurement-attempt.v2:"
