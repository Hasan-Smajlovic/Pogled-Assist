"""Launch Pogled Assist."""

import os
import sys

from gaze_mouse.main import PACKAGE_SMOKE_TEST_ARG, main

if __name__ == "__main__":
    exit_code = main()
    if PACKAGE_SMOKE_TEST_ARG in sys.argv[1:]:
        # Frozen Qt imports can keep teardown alive after the smoke result is known.
        os._exit(exit_code)
    raise SystemExit(exit_code)
