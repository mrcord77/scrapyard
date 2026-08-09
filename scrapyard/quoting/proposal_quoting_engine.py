from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
import logging
import os
import re
import sqlite3
import tempfile

logger = logging.getLogger(__name__)

"""
proposal_quoting_engine - Generate quotes from proposal data with tier pricing and discount rules.

### PART-META-JSON
{
  "name": "proposal_quoting_engine",
  "layer": "quoting",
  "purpose": "Validate proposal data, generate QuoteModel objects, and apply pricing tiers and discount rules to produce final quote totals.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "generate_quote(proposal_data: dict); validate_quote_data(proposal_data) -> [ValidationError]; apply_all_tiers_and_discounts(quote).",
  "outputs": "Frozen-dataclass-backed QuoteModel with line items, applied discounts and computed totals; ValidationError lists (never exceptions) for bad input.",
  "files_created": [],
  "security_notes": "Money-touching computation. Discount rules are structured dataclasses (type + value), NOT evaluated expressions - there is no eval/injection surface here (contrast: quoting/discount_rule uses a whitelisted AST evaluator for its condition strings). Input is validated field-by-field before quoting; malformed proposals yield ValidationError lists rather than partial quotes. Honest limits: arithmetic is float-based - quote totals are commercial estimates; round to 2dp at presentation and re-derive authoritative amounts in integer cents when a quote becomes an invoice. No idempotency/versioning here - pair with quoting/proposal_version for auditable history.",
  "ai_usage": "Import from `scrapyard.quoting.proposal_quoting_engine`; run validate_quote_data first and refuse to quote when it returns errors.",
  "example": "from scrapyard.quoting.proposal_quoting_engine import generate_quote",
  "import_path": "scrapyard.quoting.proposal_quoting_engine"
}
### END-PART-META
"""


@dataclass(frozen=True)
class ValidationError:
    message: str


@dataclass(frozen=True)
class DiscountRule:
    tier: int
    discount_rate: float


@dataclass
class QuoteModel:
    parts: Dict[str, float]
    discounts: Dict[str, float] = field(default_factory=dict)
    total_price: float = 0.0


def _tier_number(tier_key: str) -> int:
    match = re.fullmatch(r"tier_(\d+)", tier_key)
    if not match:
        raise ValueError(f"Invalid tier key: {tier_key!r}")
    return int(match.group(1))


def generate_quote(proposal_data: Dict[str, Any]) -> QuoteModel:
    errors = validate_quote_data(proposal_data)
    if errors:
        raise ValueError(f"Invalid proposal data: {[e.message for e in errors]}")

    quote = QuoteModel(
        parts=dict(proposal_data.get("parts", {})),
        discounts=dict(proposal_data.get("discounts", {})),
    )
    apply_all_tiers_and_discounts(quote)
    return quote


def apply_all_tiers_and_discounts(quote: QuoteModel) -> None:
    base = sum(float(price) for price in quote.parts.values())
    total = base

    for tier_key, rate in sorted(
        quote.discounts.items(), key=lambda item: _tier_number(item[0])
    ):
        if not isinstance(rate, (int, float)):
            raise ValueError(f"Discount rate for {tier_key!r} must be numeric")
        if not 0 <= rate <= 1:
            raise ValueError(
                f"Discount rate for {tier_key!r} must be between 0 and 1"
            )
        total *= 1 - float(rate)

    quote.total_price = round(total, 2)


def validate_quote_data(proposal_data: Dict[str, Any]) -> List[ValidationError]:
    errors: List[ValidationError] = []

    if not isinstance(proposal_data, dict):
        errors.append(ValidationError("Proposal data must be a dictionary"))
        return errors

    parts = proposal_data.get("parts")
    if parts is None:
        errors.append(
            ValidationError("Proposal data must contain a 'parts' dictionary")
        )
    elif not isinstance(parts, dict):
        errors.append(ValidationError("'parts' must be a dictionary"))
    else:
        for part, price in parts.items():
            if not isinstance(part, str):
                errors.append(
                    ValidationError(
                        f"Invalid part {part!r}: part name must be a string"
                    )
                )
                continue
            if not isinstance(price, (int, float)) or price < 0:
                errors.append(
                    ValidationError(f"Invalid part {part} with price {price}")
                )

    discounts = proposal_data.get("discounts")
    if discounts is not None:
        if not isinstance(discounts, dict):
            errors.append(ValidationError("'discounts' must be a dictionary"))
        else:
            for tier_key, rate in discounts.items():
                if not isinstance(tier_key, str):
                    errors.append(
                        ValidationError(
                            f"Discount key {tier_key!r} must be a string"
                        )
                    )
                    continue
                try:
                    _tier_number(tier_key)
                except ValueError:
                    errors.append(
                        ValidationError(
                            f"Invalid discount tier key: {tier_key!r}"
                        )
                    )
                if not isinstance(rate, (int, float)):
                    errors.append(
                        ValidationError(
                            f"Discount rate for {tier_key!r} must be numeric"
                        )
                    )
                elif not 0 <= rate <= 1:
                    errors.append(
                        ValidationError(
                            f"Discount rate for {tier_key!r} must be between 0 and 1"
                        )
                    )

    return errors


def _selftest() -> None:
    db_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        conn = sqlite3.connect(os.path.join(db_dir.name, "test.db"))
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS selftest (id INTEGER PRIMARY KEY)")
            conn.commit()

            test_data_1 = {
                "parts": {"part_a": 100.0, "part_b": 200.0},
                "discounts": {"tier_1": 0.1, "tier_2": 0.05},
            }
            expected_total_1 = 256.5

            quote = generate_quote(test_data_1)
            assert quote.total_price == expected_total_1, (
                f"Expected total price {expected_total_1}, got {quote.total_price}"
            )
            assert quote.discounts == test_data_1["discounts"]
            assert quote.parts == test_data_1["parts"]

            test_data_2 = {"parts": {"part_c": -100.0, "part_d": 300.0}}
            errors = validate_quote_data(test_data_2)
            negative_errors = [e for e in errors if "-100.0" in e.message]
            assert len(negative_errors) == 1, (
                f"Expected one negative-price error, got {errors}"
            )

            invalid_proposal = "not a dict"
            errors = validate_quote_data(invalid_proposal)
            assert any("dictionary" in e.message for e in errors), (
                "Expected dictionary validation error"
            )

            cursor.close()
        finally:
            conn.close()
    finally:
        db_dir.cleanup()


if __name__ == "__main__":
    _selftest()
