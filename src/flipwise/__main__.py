"""`python -m flipwise` runs the CLI; `flipwise live --services local` uses it to start children."""

import sys

from flipwise.cli import main

sys.exit(main())
