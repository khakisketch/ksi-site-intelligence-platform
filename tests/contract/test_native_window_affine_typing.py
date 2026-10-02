"""Verify the locally declared affine subset against the prepared runtime dependency."""

from importlib import import_module


def test_affine_declared_constructor_and_coefficients_match_runtime() -> None:
    affine = import_module("affine").Affine
    coefficients = (2.0, 0.0, 100.0, 0.0, -2.0, 200.0)
    transform = affine(*coefficients)
    assert tuple(transform) == (*coefficients, 0.0, 0.0, 1.0)
    assert tuple(getattr(transform, name) for name in "abcdefghi") == tuple(transform)
    extended = affine(*coefficients, 0.0, 0.0, 1.0)
    assert extended == transform
