"""Local, isolated application testing over the production HTTP routes."""

import os
from pathlib import Path


def default_test_root() -> Path:
    """Allow an explicit physical test disk without resolving or bypassing links."""
    return Path(os.environ.get("COMPANION_TEST_ROOT") or ".agent-tests")
