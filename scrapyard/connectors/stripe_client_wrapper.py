"""
stripe_client_wrapper — Wraps the Stripe REST API (api.stripe.com) with real HTTP
execution via httpx, typed charge/refund responses, error mapping, dependency
injection, and an explicit offline mode for tests.

### PART-META-JSON
{
  "name": "stripe_client_wrapper",
  "layer": "connectors",
  "purpose": "Creates charges and refunds against the real Stripe API (https://api.stripe.com/v1, form-encoded, secret-key bearer auth via httpx) with typed ChargeResponse/RefundResponse results and Stripe error payloads mapped to typed exceptions. Supports dependency injection of a custom client, and an explicit offline=True mode that returns deterministic plain-dict objects (test-prefixed ids) so selftests run without network.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "httpx"
  ],
  "inputs": "Stripe secret API key (sk_live_/sk_test_), charge parameters (amount in minor units, ISO currency, customer id), charge ids for refunds; optional injected client or offline flag.",
  "outputs": "ChargeResponse and RefundResponse dataclasses; InvalidRequestError/StripeError on failure.",
  "files_created": [],
  "security_notes": "Handles live Stripe SECRET keys, which authorize real money movement: the key is sent only as a bearer header over TLS to api.stripe.com and never logged; never ship sk_live_ keys in client-side code or commit them. Amounts are integers in minor units - validate them upstream, since a misplaced factor of 100 is a real overcharge. Stripe error messages may include customer identifiers; treat exception text as sensitive in logs. Offline mode does zero network I/O, mints only obviously-fake ids (ch_offline_/re_offline_), and must never back a production code path. No PCI card data ever touches this module (customer ids only).",
  "ai_usage": "await StripeClientWrapper(api_key=sk).create_charge(2000,'usd','cus_x'); await .refund_charge(charge_id). Tests: StripeClientWrapper(api_key='sk_test_x', offline=True).",
  "example": "from scrapyard.connectors.stripe_client_wrapper import StripeClientWrapper",
  "import_path": "scrapyard.connectors.stripe_client_wrapper"
}
### END-PART-META
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any, Dict
import hashlib
import logging
import asyncio

logger = logging.getLogger(__name__)

STRIPE_API_BASE = "https://api.stripe.com/v1"
DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class ChargeResponse:
    """Typed response for charge creation."""
    id: str
    amount: int
    currency: str
    customer_id: str
    status: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class RefundResponse:
    """Typed response for refund creation."""
    id: str
    charge_id: str
    amount: int
    status: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StripeError(Exception):
    """Base exception for Stripe operations."""


class InvalidRequestError(StripeError):
    """Raised when request parameters are invalid."""


class _RealStripeClient:
    """Async client that talks to the real Stripe API via httpx."""

    def __init__(self, api_key: str, base_url: str = STRIPE_API_BASE,
                 timeout: float = DEFAULT_TIMEOUT):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def _post(self, path: str, form: Dict[str, Any]) -> Dict[str, Any]:
        import httpx
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=headers, data=form)
        except httpx.HTTPError as exc:
            raise StripeError(f"network error calling {path}: {exc}") from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            err = (body.get("error") or {})
            msg = err.get("message", f"HTTP {resp.status_code}")
            if err.get("type") == "invalid_request_error":
                raise InvalidRequestError(f"Stripe rejected request: {msg}")
            raise StripeError(f"Stripe API error ({resp.status_code}): {msg}")
        return body

    async def create_charge(self, amount: int, currency: str,
                            customer_id: str) -> Dict[str, Any]:
        return await self._post("charges", {
            "amount": amount, "currency": currency.lower(), "customer": customer_id,
        })

    async def refund_charge(self, charge_id: str) -> Dict[str, Any]:
        return await self._post("refunds", {"charge": charge_id})


class _OfflineStripeClient:
    """Explicit offline test client: deterministic plain dicts, zero network I/O.

    Ids derive only from public request parameters (never the API key) and are
    prefixed ch_offline_/re_offline_ so they can never pass as real objects.
    """

    async def create_charge(self, amount: int, currency: str,
                            customer_id: str) -> Dict[str, Any]:
        seed = hashlib.sha256(f"{amount}:{currency}:{customer_id}".encode()).hexdigest()
        return {
            "id": f"ch_offline_{seed[:16]}",
            "amount": amount,
            "currency": currency.lower(),
            "customer": customer_id,
            "status": "succeeded",
        }

    async def refund_charge(self, charge_id: str) -> Dict[str, Any]:
        seed = hashlib.sha256(charge_id.encode()).hexdigest()
        return {
            "id": f"re_offline_{seed[:16]}",
            "charge": charge_id,
            "amount": 0,
            "status": "succeeded",
        }


class StripeClientWrapper:
    """Wraps Stripe API calls to provide typed responses.

    With an api_key (and offline=False) requests go to the real Stripe API.
    An injected `client` overrides transport entirely (dependency injection);
    offline=True selects the explicit offline test client.
    """

    def __init__(self, api_key: Optional[str] = None,
                 client: Optional[Any] = None, *,
                 offline: bool = False,
                 base_url: str = STRIPE_API_BASE,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self._api_key = api_key
        self.offline = offline
        if client is not None:
            self._client = client
        elif offline:
            self._client = _OfflineStripeClient()
        elif api_key:
            self._client = _RealStripeClient(api_key, base_url, timeout)
        else:
            self._client = None

    async def create_charge(self, amount: int, currency: str,
                            customer_id: str) -> ChargeResponse:
        """Create a charge. Raises InvalidRequestError on bad params,
        StripeError when unconfigured or on API failure."""
        if amount <= 0:
            raise InvalidRequestError("Amount must be positive")
        if not currency:
            raise InvalidRequestError("Currency is required")
        if not customer_id:
            raise InvalidRequestError("Customer ID is required")
        if self._client is None:
            raise StripeError("No Stripe client configured (pass api_key or client)")

        result = await self._client.create_charge(amount, currency, customer_id)
        return ChargeResponse(
            id=result.get("id", ""),
            amount=result.get("amount", 0),
            currency=result.get("currency", ""),
            customer_id=result.get("customer", ""),
            status=result.get("status", ""),
        )

    async def refund_charge(self, charge_id: str) -> RefundResponse:
        """Refund a charge by id."""
        if not charge_id:
            raise InvalidRequestError("Charge ID is required")
        if self._client is None:
            raise StripeError("No Stripe client configured (pass api_key or client)")

        result = await self._client.refund_charge(charge_id)
        return RefundResponse(
            id=result.get("id", ""),
            charge_id=result.get("charge", ""),
            amount=result.get("amount", 0),
            status=result.get("status", ""),
        )


def _selftest() -> None:
    """Offline test suite: DI client + explicit offline mode, no network."""

    async def run_async_tests() -> None:
        # Dependency-injected transport (plain class, no unittest.mock)
        class FakeStripeClient:
            async def create_charge(self, amount, currency, customer_id):
                return {"id": "ch_test_12345", "amount": amount,
                        "currency": currency.lower(), "customer": customer_id,
                        "status": "succeeded"}

            async def refund_charge(self, charge_id):
                return {"id": "re_test_67890", "charge": charge_id,
                        "amount": 2000, "status": "succeeded"}

        wrapper = StripeClientWrapper(api_key="sk_test_dummy",
                                      client=FakeStripeClient())
        charge = await wrapper.create_charge(2000, "USD", "cus_test_123")
        assert isinstance(charge, ChargeResponse)
        assert (charge.id, charge.amount, charge.currency,
                charge.customer_id, charge.status) == (
            "ch_test_12345", 2000, "usd", "cus_test_123", "succeeded")
        assert isinstance(charge.created_at, datetime)

        refund = await wrapper.refund_charge("ch_test_12345")
        assert isinstance(refund, RefundResponse)
        assert (refund.id, refund.charge_id, refund.amount, refund.status) == (
            "re_test_67890", "ch_test_12345", 2000, "succeeded")

        # Explicit offline mode: deterministic fake ids, clearly marked
        off = StripeClientWrapper(api_key="sk_test_dummy", offline=True)
        c1 = await off.create_charge(500, "eur", "cus_off")
        c2 = await off.create_charge(500, "eur", "cus_off")
        assert c1.id == c2.id and c1.id.startswith("ch_offline_")
        assert c1.currency == "eur" and c1.status == "succeeded"
        r1 = await off.refund_charge(c1.id)
        assert r1.id.startswith("re_offline_") and r1.charge_id == c1.id

        # Real-mode wiring selects the real client (no request made here)
        real = StripeClientWrapper(api_key="sk_test_dummy")
        assert isinstance(real._client, _RealStripeClient)
        assert real._client.base_url == STRIPE_API_BASE

        # Validation errors
        for bad_call in [
            off.create_charge(-100, "usd", "cus_123"),
            off.create_charge(100, "", "cus_123"),
            off.create_charge(100, "usd", ""),
            off.refund_charge(""),
        ]:
            try:
                await bad_call
                raise AssertionError("Expected InvalidRequestError")
            except InvalidRequestError:
                pass

        # Unconfigured wrapper is an honest error
        empty = StripeClientWrapper()
        try:
            await empty.create_charge(100, "usd", "cus_123")
            raise AssertionError("Expected StripeError")
        except StripeError as e:
            assert "configured" in str(e).lower()
        try:
            await empty.refund_charge("ch_123")
            raise AssertionError("Expected StripeError")
        except StripeError:
            pass

    asyncio.run(run_async_tests())
    print("stripe_client_wrapper selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
