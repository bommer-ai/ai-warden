import os
from pathlib import Path

# Always enabled — zero config required.
# Set AIWARDEN_ENABLED=false to explicitly disable.
ENABLED  = os.getenv("AIWARDEN_ENABLED", "true").lower() != "false"
DEBUG    = os.getenv("AIWARDEN_DEBUG", "false").lower() == "true"

# Events written to this file as JSONL (one event per line).
# Default: ~/.aiwarden/events.jsonl
LOG_FILE = os.getenv(
    "AIWARDEN_LOG_FILE",
    str(Path.home() / ".aiwarden" / "events.jsonl")
)


def configure(enabled: bool = True, debug: bool = False, log_file: str = None):
    global ENABLED, DEBUG, LOG_FILE
    ENABLED = enabled
    DEBUG   = debug
    if log_file:
        LOG_FILE = log_file
