"""`python -m flipwise.web.dcwatch --dc-id N --port P`: `flipwise dc-serve`, unchanged, plus a
watchdog that exits when the dashboard server that started it is gone, even if the server was
killed without running its cleanup. Only the dashboard uses this launcher."""

from __future__ import annotations

import os
import sys
import threading
import time

from flipwise.cli import main


def _watch(parent_pid: int) -> None:
    while True:
        time.sleep(1.0)
        if os.getppid() != parent_pid:  # reparented: the server died
            os._exit(0)


if __name__ == "__main__":
    threading.Thread(target=_watch, args=(os.getppid(),), daemon=True).start()
    sys.exit(main(["dc-serve", *sys.argv[1:]]))
