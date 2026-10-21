"""Small display helpers shared by the engine, reports, and UI."""

from __future__ import annotations


def fmt_num(value: float, digits: int = 2) -> str:
    rounded = round(float(value), digits)
    text = f"{rounded:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def fmt_fixed(value: float, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}"
