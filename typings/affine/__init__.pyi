"""Checked subset of affine 2.4's constructor/coefficients used by native-window writing.

This is a local type declaration, not a runtime replacement or an import suppression.
Extend only with runtime-verified signatures when another operation is used.
"""

from typing import Self, overload

class Affine:
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float
    g: float
    h: float
    i: float

    @overload
    def __new__(cls, a: float, b: float, c: float, d: float, e: float, f: float) -> Self: ...
    @overload
    def __new__(
        cls, a: float, b: float, c: float, d: float, e: float, f: float,
        g: float, h: float, i: float,
    ) -> Self: ...
