"""Guided command owners. Each workflow defines its own permitted transitions."""

from .artifact_critique import workflow as artifact_critique
from .backlog_intake import workflow as backlog_intake
from .company_context import workflow as company_context
from .decision_coaching import workflow as decision_coaching
from .discovery_findings import workflow as discovery_findings
from .discovery_plan import workflow as discovery_plan
from .evidence_capture import workflow as evidence_capture
from .initiative_definition import workflow as initiative_definition
from .launch_review import workflow as launch_review
from .meeting_summary import workflow as meeting_summary
from .outcome_review import workflow as outcome_review
from .pm_context import workflow as pm_context
from .private_workflow import workflow as private_workflow
from .product_context import workflow as product_context
from .roadmap import workflow as roadmap
from .stakeholder_capture import workflow as stakeholder_capture
from .stakeholder_coaching import workflow as stakeholder_coaching
from .stakeholder_lookup import workflow as stakeholder_lookup


WORKFLOWS = {w.COMMAND: w.STEPS for w in (
    artifact_critique,
    backlog_intake,
    company_context,
    decision_coaching,
    discovery_findings,
    discovery_plan,
    evidence_capture,
    initiative_definition,
    launch_review,
    meeting_summary,
    outcome_review,
    pm_context,
    private_workflow,
    product_context,
    roadmap,
    stakeholder_capture,
    stakeholder_coaching,
    stakeholder_lookup,
)}
