"""Strict semantic-version checks for independently deployed devices."""
from __future__ import annotations

import re
from dataclasses import dataclass


_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$"
)


@dataclass(frozen=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] | None = None


def parse_semantic_version(value: str) -> SemanticVersion | None:
    match = _SEMVER_PATTERN.fullmatch(value)
    if match is None:
        return None
    major, minor, patch, prerelease, build = match.groups()
    prerelease_parts = tuple(prerelease.split(".")) if prerelease else None
    if prerelease_parts is not None and (
        any(not part for part in prerelease_parts)
        or any(
            part.isdigit() and len(part) > 1 and part.startswith("0")
            for part in prerelease_parts
        )
    ):
        return None
    if build is not None and any(not part for part in build.split(".")):
        return None
    return SemanticVersion(
        int(major),
        int(minor),
        int(patch),
        prerelease_parts,
    )


def meets_minimum_version(current: str, minimum: str) -> bool:
    current_version = parse_semantic_version(current)
    minimum_version = parse_semantic_version(minimum)
    if current_version is None or minimum_version is None:
        return False
    current_core = (
        current_version.major,
        current_version.minor,
        current_version.patch,
    )
    minimum_core = (
        minimum_version.major,
        minimum_version.minor,
        minimum_version.patch,
    )
    if current_core != minimum_core:
        return current_core > minimum_core
    if minimum_version.prerelease is None:
        return current_version.prerelease is None
    if current_version.prerelease is None:
        return True
    return _compare_prerelease(
        current_version.prerelease,
        minimum_version.prerelease,
    ) >= 0


def _compare_prerelease(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> int:
    for left_part, right_part in zip(left, right):
        if left_part == right_part:
            continue
        left_numeric = left_part.isdigit()
        right_numeric = right_part.isdigit()
        if left_numeric and right_numeric:
            return 1 if int(left_part) > int(right_part) else -1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return 1 if left_part > right_part else -1
    if len(left) == len(right):
        return 0
    return 1 if len(left) > len(right) else -1


__all__ = [
    "SemanticVersion",
    "meets_minimum_version",
    "parse_semantic_version",
]
