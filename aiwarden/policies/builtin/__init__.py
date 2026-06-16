from aiwarden.policies.builtin.budget import BudgetPolicy
from aiwarden.policies.builtin.pii import PIIPolicy
from aiwarden.policies.builtin.tools import ToolsPolicy

BUILTIN_POLICY_TYPES: dict = {
    "pii":    PIIPolicy,
    "tools":  ToolsPolicy,
    "budget": BudgetPolicy,
}
