from __future__ import annotations

import pytest

from pogled_assist.suggestions.model import load_model


@pytest.fixture(scope="session", autouse=True)
def preload_ui_dictionary():
    # lru_cache can execute simultaneous cold misses. Load the real model once
    # before short-lived windows start prediction workers under coverage.
    load_model()
