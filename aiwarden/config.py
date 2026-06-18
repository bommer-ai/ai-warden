import os
from pathlib import Path

# Always enabled — zero config required.
# Set AIWARDEN_ENABLED=false to explicitly disable.
ENABLED = os.getenv("AIWARDEN_ENABLED", "true").lower() != "false"
DEBUG   = os.getenv("AIWARDEN_DEBUG", "false").lower() == "true"

# Events written to this file as JSONL (one event per line).
LOG_FILE = os.getenv(
    "AIWARDEN_LOG_FILE",
    str(Path.home() / ".aiwarden" / "events.jsonl")
)

# Caller tracking adds stack-walk overhead (~0.1ms per call).
# Disable in high-throughput batch scenarios.
CALLER_TRACKING = os.getenv("AIWARDEN_CALLER_TRACKING", "true").lower() != "false"


def configure(
    enabled: bool = True,
    debug: bool = False,
    log_file: str = None,
    caller_tracking: bool = True,
):
    global ENABLED, DEBUG, LOG_FILE, CALLER_TRACKING
    ENABLED = enabled
    DEBUG = debug
    CALLER_TRACKING = caller_tracking
    if log_file:
        LOG_FILE = log_file
