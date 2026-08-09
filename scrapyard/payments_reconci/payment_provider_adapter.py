"""
payment_provider_adapter — Pluggable payment provider registry with persisted outcomes.

### PART-META-JSON
{
  "name": "payment_provider_adapter",
  "layer": "payments_reconci",
  "purpose": "Abstract charge/refund execution behind a provider registry (PaymentAdapter subclasses) and persist the outcome of every attempt.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "_configure_engine(engine); register_payment_provider(name, adapter_class); create_charge_with_provider(charge_id, provider); refund_with_provider(refund_id, provider).",
  "outputs": "bool success per attempt; PaymentCharge/PaymentRefund rows recording provider + status for reconciliation.",
  "files_created": [],
  "security_notes": "Money-touching integration seam. Providers are registered in code (no dynamic import from data) and duplicate registration is rejected, so the registry cannot be silently hijacked at runtime. Adapter exceptions are caught, logged, and recorded as status=False - a failing provider cannot crash the payment path, and every attempt leaves an audit row. Honest limits: adapters themselves own credential handling and any webhook signature verification (see billing/stripe_webhooks for the verified-ingest side); charge_id/refund_id are UNIQUE, so a retried attempt raises IntegrityError instead of double-recording - catch it and reconcile rather than blind-retrying; success=True only means the adapter returned True, not that funds settled.",
  "ai_usage": "Import from `scrapyard.payments_reconci.payment_provider_adapter`; register concrete adapters at startup and call _configure_engine before any charge/refund.",
  "example": "from scrapyard.payments_reconci.payment_provider_adapter import register_payment_provider",
  "import_path": "scrapyard.payments_reconci.payment_provider_adapter"
}
### END-PART-META
"""
from sqlalchemy import String, Boolean, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from sqlalchemy.engine import Engine
from scrapyard.database.base_model import IntPKModel
from dataclasses import dataclass
from typing import Dict, Callable, Optional
import abc
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

PAYMENT_PROVIDERS: Dict[str, Callable[..., "PaymentAdapter"]] = {}

_engine: Optional[Engine] = None


def _configure_engine(engine: Engine) -> None:
    """Bind the adapter functions to a SQLAlchemy engine."""
    global _engine
    _engine = engine


def _get_session() -> Session:
    if _engine is None:
        raise RuntimeError("Payment provider adapter engine is not configured")
    return Session(_engine)


@dataclass
class PaymentAdapter(abc.ABC):
    provider_name: str

    @abc.abstractmethod
    def create_charge(self, charge_id: str) -> bool:
        raise NotImplementedError("Subclasses should implement create_charge")

    @abc.abstractmethod
    def refund(self, refund_id: str) -> bool:
        raise NotImplementedError("Subclasses should implement refund")


def _get_provider_adapter(provider_name: str) -> Callable[..., PaymentAdapter]:
    if provider_name not in PAYMENT_PROVIDERS:
        raise ValueError(f"Unknown payment provider: {provider_name}")
    return PAYMENT_PROVIDERS[provider_name]


def register_payment_provider(provider_name: str, adapter_class: type[PaymentAdapter]) -> None:
    if provider_name in PAYMENT_PROVIDERS:
        raise ValueError(f"Provider {provider_name} already registered")
    PAYMENT_PROVIDERS[provider_name] = adapter_class


def _run_adapter(method_name: str, provider: str, item_id: str) -> bool:
    try:
        adapter_class = _get_provider_adapter(provider)
        adapter = adapter_class(provider_name=provider)
        method = getattr(adapter, method_name)
        return method(item_id)
    except Exception:
        logger.exception(
            "Payment provider %s failed for %s(id=%s)", provider, method_name, item_id
        )
        return False


def create_charge_with_provider(charge_id: str, provider: str) -> bool:
    success = _run_adapter("create_charge", provider, charge_id)
    with _get_session() as session:
        session.add(
            PaymentCharge(
                charge_id=charge_id,
                provider_name=provider,
                status=success,
            )
        )
        session.commit()
    return success


def refund_with_provider(refund_id: str, provider: str) -> bool:
    success = _run_adapter("refund", provider, refund_id)
    with _get_session() as session:
        session.add(
            PaymentRefund(
                refund_id=refund_id,
                provider_name=provider,
                status=success,
            )
        )
        session.commit()
    return success


class PaymentCharge(IntPKModel):
    __tablename__ = "payment_charges"

    charge_id: Mapped[str] = mapped_column(String(100), unique=True)
    provider_name: Mapped[str] = mapped_column(String(50))
    status: Mapped[bool] = mapped_column(Boolean, default=False)


class PaymentRefund(IntPKModel):
    __tablename__ = "payment_refunds"

    refund_id: Mapped[str] = mapped_column(String(100), unique=True)
    provider_name: Mapped[str] = mapped_column(String(50))
    status: Mapped[bool] = mapped_column(Boolean, default=False)


def _selftest() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        _configure_engine(engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        IntPKModel.metadata.create_all(engine)

        @dataclass
        class MockChargeAdapter(PaymentAdapter):
            def create_charge(self, charge_id: str) -> bool:
                return True

            def refund(self, refund_id: str) -> bool:
                raise RuntimeError("MockChargeAdapter does not support refunds")

        @dataclass
        class MockRefundAdapter(PaymentAdapter):
            def create_charge(self, charge_id: str) -> bool:
                raise RuntimeError("MockRefundAdapter does not support charges")

            def refund(self, refund_id: str) -> bool:
                return True

        try:
            register_payment_provider("mock_charge", MockChargeAdapter)
            register_payment_provider("mock_refund", MockRefundAdapter)

            # Charge creation succeeds for a valid provider/input.
            assert create_charge_with_provider("12345", "mock_charge") is True
            with SessionLocal() as session:
                charge = session.execute(
                    select(PaymentCharge).where(PaymentCharge.charge_id == "12345")
                ).scalar_one_or_none()
                assert charge is not None
                assert charge.status is True

            # Refund fails gracefully for a provider that cannot refund.
            assert refund_with_provider("67890", "mock_charge") is False
            with SessionLocal() as session:
                refund = session.execute(
                    select(PaymentRefund).where(PaymentRefund.refund_id == "67890")
                ).scalar_one_or_none()
                assert refund is not None
                assert refund.status is False

            # Provider-specific logic is abstracted: refund adapter can refund.
            assert refund_with_provider("11111", "mock_refund") is True
        finally:
            PAYMENT_PROVIDERS.pop("mock_charge", None)
            PAYMENT_PROVIDERS.pop("mock_refund", None)
            engine.dispose()


if __name__ == "__main__":
    _selftest()
