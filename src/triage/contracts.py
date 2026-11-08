"""Published data contracts for every external interface (D1).

DisputeRequest is the ingestion contract: schema, type, range, category and cross-field
rules are all enforced here, before any agent starts. The JSON Schema in
contracts/dispute_request.v1.schema.json is generated from this model.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "dispute_request.v1"


class Escom(str, Enum):
    BESCOM = "BESCOM"
    MESCOM = "MESCOM"
    CESC = "CESC"
    HESCOM = "HESCOM"
    GESCOM = "GESCOM"
    HRECS = "HRECS"
    MSEZ = "MSEZ"


class ConnectionType(str, Enum):
    LT = "LT"
    HT = "HT"


LT_CATEGORIES = [
    "LT-1", "LT-2", "LT-3(a)", "LT-3(b)", "LT-4(a)", "LT-4(b)", "LT-4(c)",
    "LT-5", "LT-6(a)", "LT-6(b)", "LT-6(c)", "LT-7",
]
HT_CATEGORIES = [
    "HT-1", "HT-2(a)", "HT-2(b)", "HT-2(c)(i)", "HT-2(c)(ii)", "HT-3", "HT-4", "HT-5", "HT-6", "HT-7",
]
TariffCategory = Enum("TariffCategory", {c.replace("-", "_").replace("(", "_").replace(")", ""): c for c in LT_CATEGORIES + HT_CATEGORIES}, type=str)


class PremisesUse(str, Enum):
    residential = "residential"
    commercial = "commercial"
    industrial = "industrial"
    agricultural = "agricultural"
    institutional = "institutional"
    religious = "religious"
    other = "other"


class DisputeType(str, Enum):
    tariff_category = "tariff_category"
    meter_accuracy = "meter_accuracy"
    load_violation = "load_violation"
    arrears = "arrears"
    disconnection = "disconnection"
    other = "other"


class DisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    account_number: str = Field(pattern=r"^[A-Z0-9][A-Z0-9/-]{3,23}$", description="Consumer RR / account number")
    escom: Escom
    connection_type: ConnectionType
    billed_category: TariffCategory
    sanctioned_load_kw: float = Field(gt=0, le=20000)
    connected_load_kw: float | None = Field(default=None, ge=0, le=20000)
    premises_use: list[PremisesUse] = Field(min_length=1, max_length=4)
    claimed_dispute_type: DisputeType | None = None
    bill_period_start: date
    bill_period_end: date
    billed_amount_inr: float = Field(ge=0, le=100_000_000)
    description: str = Field(min_length=20, max_length=2000)

    @field_validator("premises_use")
    @classmethod
    def _unique_uses(cls, v):
        if len(set(v)) != len(v):
            raise ValueError("premises_use entries must be unique")
        return v

    @model_validator(mode="after")
    def _cross_field(self):
        errors = []
        cat = str(self.billed_category)
        if self.connection_type == "LT" and not cat.startswith("LT-"):
            errors.append("billed_category must be an LT category when connection_type is LT")
        if self.connection_type == "HT" and not cat.startswith("HT-") and cat != "LT-6(c)":
            errors.append("billed_category must be an HT category when connection_type is HT")
        if self.connection_type == "LT" and self.sanctioned_load_kw >= 150:
            errors.append("LT supply is only given for loads below 150 kW; use connection_type HT")
        if self.bill_period_end < self.bill_period_start:
            errors.append("bill_period_end must not be before bill_period_start")
        if (self.bill_period_end - self.bill_period_start).days > 366:
            errors.append("bill period must not exceed 12 months")
        if self.bill_period_end > date.today():
            errors.append("bill_period_end must not be in the future")
        if errors:
            raise ValueError("; ".join(errors))
        return self


Route = Literal["bill-stands-with-reason", "revision-recommended", "site-inspection-required", "escalated-to-officer"]

EscalationReason = Literal[
    "mixed_category", "provisions_conflict", "outside_corpus", "insufficient_evidence",
    "verification_failed", "budget_exhausted", "provider_unavailable", "input_flagged",
    "agent_failure", "unauthorised_determination",
]


class Citation(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str
    locator: str
    quote: str


class Claim(BaseModel):
    text: str
    citation_ids: list[str]
    supported: bool | None = None
    note: str | None = None


class Escalation(BaseModel):
    reason: EscalationReason
    explanation: str


class TariffPosition(BaseModel):
    run_id: str
    route: Route
    dispute_type: str | None = None
    billed_category: str | None = None
    determined_category: str | None = None
    position: str
    claims: list[Claim] = []
    citations: list[Citation] = []
    escalation: Escalation | None = None
    verification: dict = {}
    prompt_versions: dict = {}
    cost_usd: float = 0.0
    latency_ms: int = 0
    disclaimer: str = (
        "Recommendation only. This service never revises or recomputes a bill; "
        "the grievance officer makes the decision."
    )


class SubmitResponse(BaseModel):
    run_id: str
    status: str
    status_url: str
    cached: bool = False


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    satisfactory: bool
    reason: str = Field(min_length=3, max_length=500)
