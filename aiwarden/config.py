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

# Default agent name — used when _agent is not passed in create() call.
AGENT_NAME = os.getenv("AIWARDEN_AGENT_NAME", "default")

# Configurable run_id field name — users can pass their own identifier.
# e.g. if they already have _request_id or _trace_id in their calls.
RUN_ID_FIELD = os.getenv("AIWARDEN_RUN_ID_FIELD", "_run_id")


def configure(
    enabled: bool = True,
    debug: bool = False,
    log_file: str = None,
    caller_tracking: bool = True,
    agent_name: str = None,
):
    global ENABLED, DEBUG, LOG_FILE, CALLER_TRACKING, AGENT_NAME
    ENABLED = enabled
    DEBUG = debug
    CALLER_TRACKING = caller_tracking
    if log_file:
        LOG_FILE = log_file
    if agent_name:
        AGENT_NAME = agent_name
