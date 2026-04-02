"""CRM matching tests."""
from xw_studio.services.crm.matching import contact_match_score, find_duplicate_candidates
from xw_studio.services.crm.types import ContactRecord


def test_identical_records_high_score() -> None:
    a = ContactRecord(id="1", name="ACME GmbH", email="e@acme.test")
    b = ContactRecord(id="2", name="ACME GmbH", email="e@acme.test")
    assert contact_match_score(a, b) >= 90


def test_find_duplicate_candidates() -> None:
    rows = [
        ContactRecord(id="1", name="Musik Verlag Nord", email="a@example.test"),
        ContactRecord(id="2", name="Musikverlag Nord", email="a@example.test"),
    ]
    dups = find_duplicate_candidates(rows, threshold=70)
    assert dups
