from aiwarden.pipeline.engine import Pipeline
from aiwarden.pipeline.pre.pii_redact import PIIRedactPreProcessor

# Singleton — import and extend in your application:
#
#   from aiwarden.pipeline import pipeline
#   from aiwarden.pipeline.base import PreProcessor, Block
#
#   class BudgetCheckProcessor(PreProcessor):
#       def process(self, request):
#           if over_budget(request.get("metadata", {}).get("org_id")):
#               return request, Block("monthly budget exceeded")
#           return request, None
#
#   pipeline.add_pre(BudgetCheckProcessor())

pipeline = Pipeline()
pipeline.add_pre(PIIRedactPreProcessor())   # on by default
