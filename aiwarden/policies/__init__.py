from aiwarden.policies.base import Block, Policy, PolicyViolationError
from aiwarden.policies.engine import PolicyEngine

# Singleton — used by patchers. Policies loaded lazily on first LLM call.
engine = PolicyEngine()


def register_policy(policy: Policy) -> None:
    """
    Programmatically add a custom policy — call in your agent code before first LLM call.

    Example:
        from aiwarden.policies import register_policy
        from aiwarden.policies.base import Policy, Block

        class CompanyBudgetPolicy(Policy):
            name          = "company-budget"
            default_hooks = ["pre"]

            def pre(self, request):
                if over_budget(request.get("metadata", {}).get("team")):
                    return request, Block("budget exceeded")
                return request, None

        register_policy(CompanyBudgetPolicy())
    """
    engine.register(policy)
