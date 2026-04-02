"""CRM services."""

from xw_studio.services.crm.matching import contact_match_score, find_duplicate_candidates
from xw_studio.services.crm.service import CrmService
from xw_studio.services.crm.types import ContactRecord, DuplicateCandidate

__all__ = [
    "ContactRecord",
    "DuplicateCandidate",
    "CrmService",
    "contact_match_score",
    "find_duplicate_candidates",
]
