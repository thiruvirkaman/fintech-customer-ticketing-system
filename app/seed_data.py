import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


PanState = Literal["PENDING", "SUCCESS", "FAILURE"]
BureauState = Literal["NOT_STARTED", "PENDING", "SUCCESS", "FAILURE"]
UnderwritingState = Literal["NOT_STARTED", "PENDING", "APPROVED", "REJECTED"]
OfferState = Literal["NOT_STARTED", "AVAILABLE", "ACCEPTED", "DECLINED"]
BankStatementState = Literal["NOT_STARTED", "PENDING", "PROCESSING", "FAILURE", "SUCCESS"]
VerificationState = Literal["NOT_STARTED", "PENDING", "FAILURE", "SUCCESS"]
DisbursalState = Literal["NOT_STARTED", "PENDING", "SUCCESS"]
OfferSelection = Literal["UNDECIDED", "INITIAL", "FINAL"]


class CustomerSeed(BaseModel):
    customer_id: str = Field(pattern=r"^CUST-DEMO-\d{4}$")
    full_name: str = Field(min_length=1)
    email: str
    mobile: str = Field(pattern=r"^9\d{9}$")
    pan: str = Field(pattern=r"^[A-Z]{5}\d{4}[A-Z]$")
    data_classification: Literal["SYNTHETIC"]

    @field_validator("email")
    @classmethod
    def require_example_domain(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9._+-]+@example\.com", value.casefold()):
            raise ValueError("synthetic customer email must use example.com")
        return value.casefold()


class ApplicationSeed(BaseModel):
    application_id: str = Field(pattern=r"^APP-DEMO-\d{4}$")
    customer_id: str = Field(pattern=r"^CUST-DEMO-\d{4}$")
    pan_status: PanState
    bureau_status: BureauState
    underwriting_status: UnderwritingState
    initial_offer_status: OfferState
    bank_statement_status: BankStatementState
    final_offer_status: OfferState
    offer_selection: OfferSelection
    bank_account_status: VerificationState
    mandate_status: VerificationState
    disbursal_status: DisbursalState
    failure_code: str | None = Field(default=None, pattern=r"^DEMO_[A-Z0-9_]+$")
    updated_at: datetime
    data_classification: Literal["SYNTHETIC"]


class SeedBundle(BaseModel):
    customers: list[CustomerSeed] = Field(min_length=20)
    applications: list[ApplicationSeed] = Field(min_length=20)

    @model_validator(mode="after")
    def validate_relationships_and_uniqueness(self) -> "SeedBundle":
        customer_ids = [customer.customer_id for customer in self.customers]
        application_ids = [application.application_id for application in self.applications]
        emails = [customer.email for customer in self.customers]
        pans = [customer.pan for customer in self.customers]
        for label, values in (
            ("customer_id", customer_ids),
            ("application_id", application_ids),
            ("email", emails),
            ("pan", pans),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"seed data contains duplicate {label}")
        missing_customers = {
            application.customer_id for application in self.applications if application.customer_id not in set(customer_ids)
        }
        if missing_customers:
            raise ValueError(f"applications reference unknown customers: {sorted(missing_customers)}")

        required_coverage = {
            "pan_status": {"PENDING", "SUCCESS", "FAILURE"},
            "bureau_status": {"NOT_STARTED", "PENDING", "SUCCESS", "FAILURE"},
            "underwriting_status": {"NOT_STARTED", "PENDING", "APPROVED", "REJECTED"},
            "initial_offer_status": {"NOT_STARTED", "AVAILABLE", "ACCEPTED", "DECLINED"},
            "bank_statement_status": {"NOT_STARTED", "PENDING", "PROCESSING", "FAILURE", "SUCCESS"},
            "final_offer_status": {"NOT_STARTED", "AVAILABLE", "ACCEPTED", "DECLINED"},
            "offer_selection": {"UNDECIDED", "INITIAL", "FINAL"},
            "bank_account_status": {"NOT_STARTED", "PENDING", "FAILURE", "SUCCESS"},
            "mandate_status": {"NOT_STARTED", "PENDING", "FAILURE", "SUCCESS"},
            "disbursal_status": {"NOT_STARTED", "PENDING", "SUCCESS"},
        }
        missing_states = {
            field: sorted(required - {str(getattr(application, field)) for application in self.applications})
            for field, required in required_coverage.items()
            if required - {str(getattr(application, field)) for application in self.applications}
        }
        if missing_states:
            raise ValueError(f"seed data is missing required journey-state coverage: {missing_states}")
        return self


def load_seed_bundle(data_root: Path) -> SeedBundle:
    seed_root = data_root / "seeds"
    customers = json.loads((seed_root / "customers.json").read_text(encoding="utf-8"))
    applications = json.loads((seed_root / "applications.json").read_text(encoding="utf-8"))
    return SeedBundle(customers=customers, applications=applications)


def coverage_report(bundle: SeedBundle) -> dict[str, list[str]]:
    fields = (
        "pan_status",
        "bureau_status",
        "underwriting_status",
        "initial_offer_status",
        "bank_statement_status",
        "final_offer_status",
        "offer_selection",
        "bank_account_status",
        "mandate_status",
        "disbursal_status",
    )
    report = {
        field: sorted({str(getattr(application, field)) for application in bundle.applications})
        for field in fields
    }
    report["failure_codes"] = sorted(
        {application.failure_code for application in bundle.applications if application.failure_code}
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate synthetic customer and LOS application seed data")
    parser.add_argument("--data-root", type=Path, default=Path(os.getenv("DATA_ROOT", "data")))
    args = parser.parse_args()
    bundle = load_seed_bundle(args.data_root)
    print(
        json.dumps(
            {
                "customers": len(bundle.customers),
                "applications": len(bundle.applications),
                "coverage": coverage_report(bundle),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
