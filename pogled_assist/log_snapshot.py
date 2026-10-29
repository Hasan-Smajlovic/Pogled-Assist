"""Primitive log snapshots with a shared byte and nesting budget."""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass

NUMERIC_SUMMARY_FIELDS = frozenset({"counts", "cumulative_counts", "eye_state_seconds"})


@dataclass(frozen=True, slots=True)
class NumericSnapshot:
    """A flat numeric map kept compact until the output worker serializes it."""

    payload: bytes


def expand_numeric_snapshot(value):
    """JSON encoder hook; expansion belongs to the output worker, never admission."""
    if type(value) is NumericSnapshot:
        return json.loads(value.payload)
    raise TypeError("Unsupported log snapshot")


class BoundedSnapshot:
    def __init__(self, budget: int, *, summary: bool = False) -> None:
        self.remaining = budget
        self.truncated = False
        self.summary = summary

    def copy(self, item: object, depth: int = 0):
        if self.remaining < 128 or depth > 4:
            self.truncated = True
            return "<truncated>"
        if type(item) in (tuple, list):
            return self._sequence(item, depth)
        if type(item) is dict:
            return self._mapping(item, depth)
        result = self._scalar(item)
        self.remaining -= sys.getsizeof(result)
        return result

    def _scalar(self, item: object):
        if type(item) is int and item.bit_length() > 128:
            self.truncated = True
            return "<large integer>"
        if type(item) is float:
            return item if math.isfinite(item) else None
        if item is None or type(item) in (bool, int):
            return item
        if type(item) is str:
            result = item[: min(2048, max(0, (self.remaining - 128) // 4))]
            self.truncated |= len(result) < len(item)
            return result
        return "<non-primitive>"

    def _sequence(self, item: tuple | list, depth: int) -> tuple:
        self.truncated |= len(item) > 32
        self.remaining -= 128 + 8 * min(32, len(item))
        return tuple(self.copy(part, depth + 1) for part in item[:32])

    def _mapping(self, item: dict, depth: int) -> dict:
        self.remaining -= 256 + 64 * min(32, len(item))
        result = {}
        for index, (key, part) in enumerate(item.items()):
            if index >= 32 or self.remaining < 128:
                self.truncated = True
                break
            if isinstance(key, str):
                # Copy keys first so a large value cannot erase its field name.
                field = self.copy(key, depth + 1)
                if self.summary and depth == 0 and key in NUMERIC_SUMMARY_FIELDS:
                    result[field] = self._numeric_mapping(part, depth + 1)
                else:
                    result[field] = self.copy(part, depth + 1)
        return result

    def _numeric_mapping(self, item, depth):
        # Summary keys are internal reason/state names, not arbitrary event data.
        # Bound validation/encoding work as well as the retained byte buffer.
        if type(item) is dict and len(item) <= 128:
            values = {}
            for key, value in item.items():
                if type(key) is not str or len(key) > 128:
                    break
                if (type(value) is int and value.bit_length() <= 128) or (
                    type(value) is float and math.isfinite(value)
                ):
                    values[key] = value
                else:
                    break
            else:
                packed = NumericSnapshot(
                    json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode("ascii")
                )
                size = sys.getsizeof(packed) + sys.getsizeof(packed.payload)
                if size <= self.remaining - 128:
                    self.remaining -= size
                    return packed
        # Exceptional inputs still use the ordinary bounded primitive copier;
        # partial counters must be declared incomplete just like other loss.
        self.truncated = True
        return self.copy(item, depth)
