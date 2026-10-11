"""Primitive log snapshots with a shared byte and nesting budget."""

from __future__ import annotations

import math
import sys


class BoundedSnapshot:
    def __init__(self, budget: int) -> None:
        self.remaining = budget
        self.truncated = False

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
                result[field] = self.copy(part, depth + 1)
        return result
