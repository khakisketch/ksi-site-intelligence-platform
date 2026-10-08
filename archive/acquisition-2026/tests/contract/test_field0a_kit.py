"""FIELD-0a trial-kit determinism and one-variable experiment guards."""

from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from xml.etree import ElementTree as ET

_ROOT = Path(__file__).resolve().parents[4]
# P3 Task 6: this test and its tool moved blob-identical with the archived
# mission-planning subject. The archived package roots join sys.path here so
# the historical regeneration procedure stays runnable standalone
# (archive/ is never on the product path; see task-6-report).
_ARCHIVED_SRC = _ROOT / "archive" / "acquisition-2026"
sys.path.insert(0, str(_ARCHIVED_SRC / "packages/mission-contracts/src"))
sys.path.insert(0, str(_ARCHIVED_SRC / "packages/mission-planning/src"))
_TOOL = _ARCHIVED_SRC / "tools" / "build_field0a_kit.py"
_MEMBERS = ("wpmz/template.kml", "wpmz/waylines.wpml")


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_field0a_kit", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _members(kmz: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        return {member: archive.read(member) for member in _MEMBERS}


def _normalised_profile_xml(payload: bytes) -> bytes:
    """Erase exactly the A↔B hypothesis values, preserving every other XML fact."""
    root = ET.fromstring(payload)
    for element in root.iter():
        if element.tag.split("}")[-1] in {"droneEnumValue", "payloadEnumValue"}:
            element.text = "PROFILE-HYPOTHESIS"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def test_field0a_variants_are_byte_stable_and_checksum_manifest_matches() -> None:
    tool = _load_tool()

    first = tool.build_variants()
    second = tool.build_variants()

    assert first == second
    assert tuple(first) == tool.KIT_FILE_NAMES
    assert tool.checksum_manifest(first) == tool.CHECKSUM_MANIFEST.read_text(encoding="utf-8")
    for name, payload in first.items():
        assert (tool.KIT_DIR / name).read_bytes() == payload


def test_field0a_variants_change_only_the_declared_experiment_variable() -> None:
    tool = _load_tool()
    variants = tool.build_variants()
    a, b, c = (variants[name] for name in tool.KIT_FILE_NAMES)

    # A↔B isolates the flight/payload profile.  Namespace-aware parse/serialize
    # removes only those two text values; every route, action and ordering fact
    # must remain equal.
    a_members = _members(a)
    b_members = _members(b)
    for member in _MEMBERS:
        assert _normalised_profile_xml(a_members[member]) == _normalised_profile_xml(
            b_members[member]
        )

    # A↔C changes only the uncompressed XML namespace URI.  ZIP compression
    # correctly changes CRC/compressed bytes when its member payload changes,
    # so compare the member contents rather than claiming the two ZIP streams
    # themselves can be equal after a length-changing replacement.
    c_members = _members(c)
    assert tuple(c_members) == _MEMBERS
    for member in _MEMBERS:
        assert c_members[member] == a_members[member].replace(
            tool.WPML_NS.encode(), tool.SAMPLE_NAMESPACE.encode()
        )
