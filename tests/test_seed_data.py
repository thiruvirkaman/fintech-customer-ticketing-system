from pathlib import Path

from app.seed_data import coverage_report, load_seed_bundle


DATA_ROOT = Path("data")


def test_seed_bundle_has_linked_synthetic_records() -> None:
    bundle = load_seed_bundle(DATA_ROOT)
    assert len(bundle.customers) == 20
    assert len(bundle.applications) == 20
    assert all(customer.email.endswith("@example.com") for customer in bundle.customers)
    assert all(customer.data_classification == "SYNTHETIC" for customer in bundle.customers)
    assert all(application.data_classification == "SYNTHETIC" for application in bundle.applications)


def test_seed_bundle_covers_required_los_states() -> None:
    report = coverage_report(load_seed_bundle(DATA_ROOT))
    assert {"PENDING", "SUCCESS", "FAILURE"} <= set(report["pan_status"])
    assert {"PENDING", "SUCCESS", "FAILURE"} <= set(report["bureau_status"])
    assert {"PENDING", "APPROVED", "REJECTED"} <= set(report["underwriting_status"])
    assert {"PENDING", "PROCESSING", "FAILURE", "SUCCESS"} <= set(report["bank_statement_status"])
    assert {"INITIAL", "FINAL"} <= set(report["offer_selection"])
    assert {"PENDING", "FAILURE", "SUCCESS"} <= set(report["bank_account_status"])
    assert {"PENDING", "FAILURE", "SUCCESS"} <= set(report["mandate_status"])
    assert {"PENDING", "SUCCESS"} <= set(report["disbursal_status"])
    assert report["failure_codes"]


def test_seed_failure_codes_are_documented() -> None:
    report = coverage_report(load_seed_bundle(DATA_ROOT))
    failure_reference = (DATA_ROOT / "knowledge" / "synthetic" / "los_failure_codes.md").read_text(
        encoding="utf-8"
    )
    assert all(failure_code in failure_reference for failure_code in report["failure_codes"])
