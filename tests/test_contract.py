import pytest
from pydantic import ValidationError

from triage.contracts import DisputeRequest

VALID = {
    "account_number": "BLR-1234567", "escom": "BESCOM", "connection_type": "LT", "billed_category": "LT-1",
    "sanctioned_load_kw": 2, "connected_load_kw": 1.8, "premises_use": ["residential", "commercial"],
    "bill_period_start": "2026-08-01", "bill_period_end": "2026-08-31", "billed_amount_inr": 1840,
    "description": "I run a small tailoring shop from one room of my house. Which category applies?",
}


def errors_for(**changes):
    with pytest.raises(ValidationError) as e:
        DisputeRequest.model_validate({**VALID, **changes})
    return e.value.errors()


def test_valid_request():
    r = DisputeRequest.model_validate(VALID)
    assert r.billed_category == "LT-1"


def test_schema_unknown_field_rejected():
    assert errors_for(refund_to="me")[0]["type"] == "extra_forbidden"


def test_type_and_range():
    assert errors_for(sanctioned_load_kw="two")[0]["loc"] == ("sanctioned_load_kw",)
    assert errors_for(sanctioned_load_kw=-1)[0]["type"] == "greater_than"
    assert errors_for(description="short")[0]["type"] == "string_too_short"


def test_categorical():
    assert errors_for(billed_category="LT-9")[0]["loc"] == ("billed_category",)
    assert errors_for(escom="MSEDCL")[0]["loc"] == ("escom",)


@pytest.mark.parametrize("changes,fragment", [
    ({"connection_type": "LT", "billed_category": "HT-2(a)"}, "LT category"),
    ({"sanctioned_load_kw": 200}, "below 150 kW"),
    ({"bill_period_end": "2026-07-01"}, "must not be before"),
    ({"bill_period_start": "2024-01-01"}, "12 months"),
    ({"bill_period_end": "2099-01-01", "bill_period_start": "2098-12-01"}, "future"),
])
def test_cross_field(changes, fragment):
    errs = errors_for(**changes)
    assert any(fragment in e["msg"] for e in errs)
