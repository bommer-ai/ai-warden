from aiwarden.policies.builtin.budget import BudgetPolicy
from aiwarden.policies.builtin.pii import PIIPolicy
from aiwarden.policies.builtin.tools import ToolsPolicy
from aiwarden.policies.custom import CustomPolicy

BUILTIN_POLICY_TYPES: dict = {
    "pii":    PIIPolicy,
    "tools":  ToolsPolicy,
    "budget": BudgetPolicy,
    "custom": CustomPolicy,
}
