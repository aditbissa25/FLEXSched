"""Allows ``python -m flexsched ...``."""

import sys

from .cli import main

sys.exit(main())
