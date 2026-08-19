import json
from collections.abc import Callable

from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.contracts import EvidenceItem
from app.db_models import ApplicationRecord, CustomerRecord


class CustomerFacts(BaseModel):
    customer_id: str
    full_name: str


class ApplicationFacts(BaseModel):
    application_id: str
    customer_id: str
    pan_status: str
    bureau_status: str
    underwriting_status: str
    initial_offer_status: str
    bank_statement_status: str
    final_offer_status: str
    offer_selection: str
    bank_account_status: str
    mandate_status: str
    disbursal_status: str
    failure_code: str | None

    def as_evidence(self) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=f"LOS-DB-{self.application_id}",
            source_type="LOS_DB",
            source=f"Synthetic application {self.application_id}",
            content=json.dumps(self.model_dump(), sort_keys=True),
        )


class LosDataTools:
    """Allowlisted, parameterized, read-only LOS lookups.

    Customer prompts never become SQL. The orchestrator may invoke only the
    named methods registered here, all of which use SQLAlchemy parameters.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._tools: dict[str, Callable[..., BaseModel | None]] = {
            "find_customer_by_email": self.find_customer_by_email,
            "find_customer_by_identifiers": self.find_customer_by_identifiers,
            "get_application": self.get_application,
            "get_application_status": self.get_application_status,
            "get_latest_application": self.get_latest_application,
        }

    @property
    def allowed_tool_names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def invoke(self, tool_name: str, **arguments: str) -> BaseModel | None:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ValueError(f"LOS DB tool is not allowlisted: {tool_name}")
        return tool(**arguments)

    def find_customer_by_email(self, email: str) -> CustomerFacts | None:
        normalized_email = email.casefold().strip()
        with self._session_factory() as session:
            customer = session.scalar(
                select(CustomerRecord).where(CustomerRecord.email == normalized_email)
            )
            if customer is None:
                return None
            return CustomerFacts(customer_id=customer.customer_id, full_name=customer.full_name)

    def find_customer_by_identifiers(
        self,
        customer_id: str | None = None,
        pan: str | None = None,
        mobile: str | None = None,
    ) -> CustomerFacts | None:
        filters = []
        if customer_id:
            filters.append(CustomerRecord.customer_id == customer_id.strip())
        if pan:
            filters.append(CustomerRecord.pan == pan.upper().strip())
        if mobile:
            filters.append(CustomerRecord.mobile == mobile.strip())
        if not filters:
            raise ValueError("at least one supported customer identifier is required")
        with self._session_factory() as session:
            customer = session.scalar(select(CustomerRecord).where(and_(*filters)).limit(1))
            if customer is None:
                return None
            return CustomerFacts(customer_id=customer.customer_id, full_name=customer.full_name)

    def get_application(self, application_id: str) -> ApplicationFacts | None:
        with self._session_factory() as session:
            application = session.get(ApplicationRecord, application_id.strip())
            return self._facts(application)

    def get_application_status(self, application_id: str) -> ApplicationFacts | None:
        return self.get_application(application_id)

    def get_latest_application(self, customer_id: str) -> ApplicationFacts | None:
        with self._session_factory() as session:
            application = session.scalar(
                select(ApplicationRecord)
                .where(ApplicationRecord.customer_id == customer_id.strip())
                .order_by(ApplicationRecord.updated_at.desc(), ApplicationRecord.application_id.desc())
                .limit(1)
            )
            return self._facts(application)

    @staticmethod
    def _facts(application: ApplicationRecord | None) -> ApplicationFacts | None:
        if application is None:
            return None
        return ApplicationFacts(
            application_id=application.application_id,
            customer_id=application.customer_id,
            pan_status=application.pan_status,
            bureau_status=application.bureau_status,
            underwriting_status=application.underwriting_status,
            initial_offer_status=application.initial_offer_status,
            bank_statement_status=application.bank_statement_status,
            final_offer_status=application.final_offer_status,
            offer_selection=application.offer_selection,
            bank_account_status=application.bank_account_status,
            mandate_status=application.mandate_status,
            disbursal_status=application.disbursal_status,
            failure_code=application.failure_code,
        )
