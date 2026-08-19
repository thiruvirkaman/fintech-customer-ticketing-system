import argparse
import json
import os
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from app.database import create_database_engine
from app.db_models import ApplicationRecord, CustomerRecord
from app.seed_data import load_seed_bundle


def seed_database(database_url: str, data_root: Path) -> dict[str, int]:
    """Upsert the validated synthetic seed bundle in one database transaction."""
    bundle = load_seed_bundle(data_root)
    engine = create_database_engine(database_url)
    customer_rows = [customer.model_dump(mode="json") for customer in bundle.customers]
    application_rows = [application.model_dump(mode="python") for application in bundle.applications]

    customer_insert = insert(CustomerRecord).values(customer_rows)
    application_insert = insert(ApplicationRecord).values(application_rows)
    customer_update_columns = {
        column: getattr(customer_insert.excluded, column)
        for column in ("full_name", "email", "mobile", "pan", "data_classification")
    }
    application_update_columns = {
        column: getattr(application_insert.excluded, column)
        for column in (
            "customer_id",
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
            "failure_code",
            "updated_at",
            "data_classification",
        )
    }
    with engine.begin() as connection:
        connection.execute(
            customer_insert.on_conflict_do_update(
                index_elements=[CustomerRecord.customer_id],
                set_=customer_update_columns,
            )
        )
        connection.execute(
            application_insert.on_conflict_do_update(
                index_elements=[ApplicationRecord.application_id],
                set_=application_update_columns,
            )
        )
    engine.dispose()
    return {"customers": len(customer_rows), "applications": len(application_rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Transactionally seed synthetic LOS data into PostgreSQL")
    parser.add_argument("--data-root", type=Path, default=Path(os.getenv("DATA_ROOT", "data")))
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to seed PostgreSQL")
    print(json.dumps(seed_database(database_url, args.data_root)))


if __name__ == "__main__":
    main()
