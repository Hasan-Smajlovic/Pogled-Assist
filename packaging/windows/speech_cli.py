"""Entry point shared by the two bundled Edge speech executables."""

import sys
from pathlib import Path

from edge_playback import _main as playback_main
from edge_tts.util import main as tts_main

if __name__ == "__main__":
    executable = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
    if Path(executable).stem == "edge-playback":
        playback_main()
    else:
        tts_main()
