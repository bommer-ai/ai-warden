import re
from dataclasses import dataclass, field
from fnmatch import fnmatch


# ── Rule dataclass ─────────────────────────────────────────────────────────────

@dataclass
class PolicyRule:
    name: str
    action: str                        # "refusal" | "interrupt" | "warn"
    message: str = ""
    match_tool: str | list = "*"       # exact name, glob ("bash*"), or list
    match_args: dict = field(default_factory=dict)   # {arg_name: {op: value}}
    any_arg: dict = field(default_factory=dict)      # {op: value} — checked across ALL args
    when_metadata: dict = field(default_factory=dict)  # {key: value} — context filter


# ── Matching logic ─────────────────────────────────────────────────────────────

def matches(rule: PolicyRule, tool_name: str, tool_input: dict, metadata: dict) -> bool:
    """Return True if this rule applies to the given tool call."""
    if not _match_tool(rule.match_tool, tool_name):
        return False

    for field_name, matchers in rule.match_args.items():
        value = str(tool_input.get(field_name, ""))
        if not _match_field(value, matchers):
            return False

    if rule.any_arg:
        if not any(_match_field(str(v), rule.any_arg) for v in tool_input.values()):
            return False

    for key, expected in rule.when_metadata.items():
        if str(metadata.get(key, "")) != str(expected):
            return False

    return True


def _match_tool(pattern, tool_name: str) -> bool:
    if isinstance(pattern, list):
        return any(_match_tool(p, tool_name) for p in pattern)
    return pattern == "*" or fnmatch(tool_name, pattern)


def _match_field(value: str, matchers: dict) -> bool:
    for op, pattern in matchers.items():
        if op == "contains":
            if str(pattern) not in value:
                return False
        elif op == "startswith":
            patterns = pattern if isinstance(pattern, list) else [pattern]
            if not any(value.startswith(p) for p in patterns):
                return False
        elif op == "not_startswith":
            patterns = pattern if isinstance(pattern, list) else [pattern]
            if any(value.startswith(p) for p in patterns):
                return False
        elif op == "equals":
            if value != str(pattern):
                return False
        elif op == "in":
            if value not in [str(p) for p in pattern]:
                return False
        elif op == "regex":
            if not re.search(str(pattern), value):
                return False
    return True


# ── Built-in templates ─────────────────────────────────────────────────────────
# Enable/disable in policies.yaml under the "builtin:" key of a tools policy.
# filesystem-safety and no-privilege-escalation are ON by default.

BUILTIN_TEMPLATES: dict[str, list[PolicyRule]] = {

    "filesystem-safety": [
        PolicyRule(
            name="no-recursive-delete",
            action="refusal",
            message="Recursive deletion is not allowed.",
            match_tool=["bash", "shell", "run_command", "execute_command"],
            match_args={"command": {"regex": r"rm\s+.*-[rRfF]*[rR]|-[rRfF]*[rR]\s+"}},
        ),
        PolicyRule(
            name="no-system-path-write",
            action="refusal",
            message="Writing to system paths is not allowed.",
            match_tool=["write_file", "create_file", "file_write"],
            match_args={"path": {"startswith": ["/etc/", "/sys/", "/boot/", "/bin/", "/usr/bin/", "/sbin/"]}},
        ),
        PolicyRule(
            name="no-system-path-write-bash",
            action="refusal",
            message="Writing to system paths is not allowed.",
            match_tool=["bash", "shell", "run_command"],
            match_args={"command": {"regex": r">\s*/etc/|>\s*/sys/|>\s*/boot/"}},
        ),
    ],

    "no-privilege-escalation": [
        PolicyRule(
            name="no-sudo",
            action="refusal",
            message="Privilege escalation via sudo is not allowed.",
            match_tool=["bash", "shell", "run_command", "execute_command"],
            match_args={"command": {"regex": r"(^|\s)sudo\s"}},
        ),
        PolicyRule(
            name="no-su",
            action="refusal",
            message="Switching users is not allowed.",
            match_tool=["bash", "shell", "run_command"],
            match_args={"command": {"regex": r"(^|\s)su\s"}},
        ),
        PolicyRule(
            name="no-chmod-777",
            action="refusal",
            message="Setting world-writable permissions is not allowed.",
            match_tool=["bash", "shell", "run_command"],
            match_args={"command": {"regex": r"chmod\s+.*777|chmod\s+.*\+s"}},
        ),
    ],

    "no-credential-access": [
        PolicyRule(
            name="no-env-file-read",
            action="refusal",
            message="Reading credential files is not allowed.",
            match_tool=["read_file", "file_read", "bash", "shell"],
            match_args={"path": {"regex": r"(\.env$|\.env\.|\.aws/credentials|\.ssh/|\.netrc|\.pgpass)"}},
        ),
        PolicyRule(
            name="no-credential-env-dump",
            action="refusal",
            message="Dumping environment variables is not allowed.",
            match_tool=["bash", "shell", "run_command"],
            match_args={"command": {"regex": r"(printenv|env\b|export\s+-p)"}},
        ),
    ],

    "safe-git": [
        PolicyRule(
            name="no-force-push",
            action="interrupt",
            message="Force push is not allowed — requires human approval.",
            match_tool=["bash", "shell", "run_command"],
            match_args={"command": {"regex": r"git\s+push\s+.*--force|git\s+push\s+.*-f\b"}},
        ),
        PolicyRule(
            name="no-hard-reset",
            action="interrupt",
            message="Hard reset is not allowed — requires human approval.",
            match_tool=["bash", "shell", "run_command"],
            match_args={"command": {"contains": "reset --hard"}},
        ),
        PolicyRule(
            name="no-branch-delete-force",
            action="refusal",
            message="Force branch deletion is not allowed.",
            match_tool=["bash", "shell", "run_command"],
            match_args={"command": {"regex": r"git\s+branch\s+(-D\b|--delete\s+--force)"}},
        ),
    ],

    "no-auto-install": [
        PolicyRule(
            name="no-pip-install",
            action="refusal",
            message="Package installation requires approval. Run manually if intended.",
            match_tool=["bash", "shell", "run_command"],
            match_args={"command": {"regex": r"\bpip3?\s+install\b"}},
        ),
        PolicyRule(
            name="no-npm-install",
            action="refusal",
            message="Package installation requires approval. Run manually if intended.",
            match_tool=["bash", "shell", "run_command"],
            match_args={"command": {"regex": r"\b(npm\s+install|yarn\s+add|pnpm\s+add)\b"}},
        ),
    ],

    "network-safety": [
        PolicyRule(
            name="outbound-request-detected",
            action="warn",
            message="Outbound network request detected.",
            match_tool=["bash", "shell", "run_command"],
            match_args={"command": {"regex": r"\b(curl|wget|http|https)\b"}},
        ),
    ],
}


# ── Rule parser (YAML → PolicyRule) ────────────────────────────────────────────

def _parse_rule(r: dict) -> PolicyRule:
    match = r.get("match") or {}
    when  = r.get("when") or {}

    # Everything inside match: except "tool" and "any_arg" is an arg matcher
    match_args = {k: v for k, v in match.items() if k not in ("tool", "any_arg")}

    return PolicyRule(
        name          = r.get("name") or "unnamed",
        action        = r.get("action") or "warn",
        message       = r.get("message") or "",
        match_tool    = match.get("tool", "*"),
        match_args    = match_args,
        any_arg       = match.get("any_arg") or {},
        when_metadata = (when.get("metadata") or {}),
    )
