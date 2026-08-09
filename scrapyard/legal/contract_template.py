"""
contract_template — Manages reusable contract templates, clauses, versions, and captured e-signatures within a legal ecosystem. It enables structured storage, retrieval, and search of contract building blocks.

### PART-META-JSON
{
  "name": "contract_template",
  "layer": "legal",
  "purpose": "Manages reusable contract templates with version history, clause lookup, and e-signature capture with SHA-256 integrity metadata and a verify_signature check. Uses the canonical legal-layer models: Clause owned by scrapyard.legal.clause_library and ContractVersion owned by scrapyard.legal.contract_version (defines only its own ContractTemplate and SignatureCapture tables).",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model", "scrapyard.legal.clause_library", "scrapyard.legal.contract_version"],
  "inputs": "Template names/content, clause names/text, contract/user ids, signature values; an engine bound via configure(engine).",
  "outputs": "Template/clause/version/signature dicts and ids; verify_signature returns bool tamper-evidence result.",
  "files_created": [],
  "security_notes": "Signatures are captured values (e.g. typed names or signature-pad blobs), NOT cryptographic digital signatures - there is no signer key pair and no non-repudiation. The stored value is kept in plaintext for backward compatibility; a SHA-256 hash, UTC timestamp and signer label are stored alongside, and verify_signature detects post-capture tampering of the stored value ONLY if the attacker could not also rewrite the hash column - restrict DB write access accordingly. No authorization checks: enforce who may sign or edit templates in the calling layer.",
  "ai_usage": "Call configure(engine) once, then use the module-level template/clause/version/signature functions.",
  "example": "from scrapyard.legal.contract_template import create_template, capture_signature, verify_signature",
  "import_path": "scrapyard.legal.contract_template"
}
### END-PART-META
"""

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import String, Text, DateTime, ForeignKey, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel

# Canonical-owner pattern: clause_library owns the Clause model and
# contract_version owns the ContractVersion model. This part imports them
# (and delegates to the owners' APIs) instead of defining duplicates.
from scrapyard.legal.clause_library import Clause
from scrapyard.legal import clause_library as _clause_lib
from scrapyard.legal.contract_version import ContractVersion
from scrapyard.legal import contract_version as _version_lib

# Unbound session factory - configured at runtime by configure()/_selftest
Session = sessionmaker()


def configure(engine) -> None:
    """Bind this module (and the contract_version owner) to an engine."""
    Session.configure(bind=engine)
    _version_lib._configure(engine)


class ContractTemplate(IntPKModel):
    __tablename__ = "contract_template"
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text(), nullable=False)


class SignatureCapture(IntPKModel):
    """Captured e-signature with integrity metadata.

    ``signature`` keeps the raw captured value (backward-compatible storage).
    ``signature_sha256``/``signed_at``/``signer`` provide tamper-evidence:
    the hash is computed at capture time and re-checked by verify_signature.
    """

    __tablename__ = "signature_capture"
    contract_id: Mapped[int] = mapped_column(ForeignKey("contract_template.id"), nullable=False)
    user_id: Mapped[int]
    signature: Mapped[str]
    signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    signer: Mapped[str] = mapped_column(String(255), nullable=False, default="")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------

def create_template(name: str, content: str) -> int:
    """Create a template and its initial version (via the canonical owner)."""
    with Session() as session:
        template = ContractTemplate(name=name, content=content)
        session.add(template)
        session.commit()
        template_id = template.id
    # Initial version goes through the canonical contract_version owner.
    _version_lib.create_version(contract_id=template_id, content=content)
    return template_id


def get_template_by_id(id: int) -> Optional[Dict[str, Any]]:
    with Session() as session:
        template = session.get(ContractTemplate, id)
        if template:
            return {"id": template.id, "name": template.name, "content": template.content}
        return None


def update_template(id: int, content: str) -> None:
    """Update template content and record the change as a new version."""
    with Session() as session:
        template = session.get(ContractTemplate, id)
        if template is None:
            raise ValueError(f"ContractTemplate {id} not found")
        template.content = content
        session.commit()
    _version_lib.create_version(contract_id=id, content=content)


# --------------------------------------------------------------------------
# Clauses (delegated to the canonical clause_library owner)
# --------------------------------------------------------------------------

def add_clause(name: str, text: str) -> int:
    with Session() as session:
        return _clause_lib.add_clause(session, name, text)


def get_clause_by_id(id: int) -> Optional[Dict[str, Any]]:
    with Session() as session:
        clause = _clause_lib.get_clause_by_id(session, id)
        if clause:
            return {"id": clause.id, "name": clause.name, "text": clause.text}
        return None


def search_clauses(keyword: str) -> List[Dict[str, Any]]:
    with Session() as session:
        results = _clause_lib.search_clauses(session, keyword)
        return [{"id": c.id, "name": c.name, "text": c.text} for c in results]


# --------------------------------------------------------------------------
# Versions (delegated to the canonical contract_version owner)
# --------------------------------------------------------------------------

def create_version(contract_id: int, content: str) -> int:
    return _version_lib.create_version(contract_id, content)


def get_version_by_id(id: int) -> Optional[Dict[str, Any]]:
    data = _version_lib.get_version_by_id(id)
    return data or None


def list_versions(contract_id: int) -> List[Dict[str, Any]]:
    return _version_lib.list_versions(contract_id)


# --------------------------------------------------------------------------
# Signatures
# --------------------------------------------------------------------------

def capture_signature(contract_id: int, user_id: int, signature: str,
                      signer: Optional[str] = None) -> int:
    """Store a captured signature with SHA-256 hash, timestamp and signer."""
    with Session() as session:
        sig = SignatureCapture(
            contract_id=contract_id,
            user_id=user_id,
            signature=signature,
            signature_sha256=_sha256(signature),
            signed_at=datetime.now(timezone.utc),
            signer=signer if signer is not None else f"user:{user_id}",
        )
        session.add(sig)
        session.commit()
        return sig.id


def list_signatures_by_contract_id(contract_id: int) -> List[Dict[str, Any]]:
    with Session() as session:
        stmt = select(SignatureCapture).where(SignatureCapture.contract_id == contract_id)
        sigs = session.execute(stmt).scalars().all()
        return [
            {
                "id": s.id,
                "contract_id": s.contract_id,
                "user_id": s.user_id,
                "signature": s.signature,
                "signature_sha256": s.signature_sha256,
                "signed_at": s.signed_at,
                "signer": s.signer,
            }
            for s in sigs
        ]


def verify_signature(signature_id: int, expected_value: Optional[str] = None) -> bool:
    """Verify integrity of a stored signature.

    Recomputes SHA-256 over the stored plaintext value and compares it to the
    stored hash (tamper-evidence). If *expected_value* is given, it must also
    hash to the stored digest.

    Raises:
        ValueError: If the signature record does not exist.
    """
    with Session() as session:
        sig = session.get(SignatureCapture, signature_id)
        if sig is None:
            raise ValueError(f"Signature {signature_id} not found")
        if not sig.signature_sha256:
            # Legacy row captured before integrity metadata existed.
            return False
        if _sha256(sig.signature) != sig.signature_sha256:
            return False
        if expected_value is not None and _sha256(expected_value) != sig.signature_sha256:
            return False
        return True


def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        configure(engine)
        IntPKModel.metadata.create_all(engine)

        try:
            # Templates (initial version recorded via canonical owner)
            tid = create_template("Test Template", "Sample content for testing.")
            retrieved = get_template_by_id(tid)
            assert retrieved is not None and retrieved["id"] == tid

            update_template(tid, "Updated sample content")
            updated = get_template_by_id(tid)
            assert updated["content"] == "Updated sample content"

            # Clauses through the canonical clause_library owner
            cid = add_clause("Test Clause 1", "This is the first test clause.")
            assert get_clause_by_id(cid)["id"] == cid
            assert len(search_clauses("test")) > 0
            assert isinstance(get_clause_by_id(cid)["text"], str)

            # Versions: create_template + update_template each recorded one
            create_version(tid, "Third version of the sample content.")
            versions = list_versions(tid)
            assert len(versions) == 3, f"Expected 3 versions, got {len(versions)}"
            assert versions[0]["content"] == "Sample content for testing."
            assert get_version_by_id(versions[-1]["id"]) is not None

            # Signature capture with integrity metadata
            sig_id = capture_signature(tid, 1001, "Sample digital signature", signer="Alice Example")
            sigs = list_signatures_by_contract_id(tid)
            assert len(sigs) == 1
            assert sigs[0]["signature"] == "Sample digital signature"  # backward-compatible plaintext
            assert sigs[0]["signature_sha256"] == _sha256("Sample digital signature")
            assert sigs[0]["signer"] == "Alice Example"
            assert sigs[0]["signed_at"] is not None

            # verify_signature: intact, matching expected value
            assert verify_signature(sig_id) is True
            assert verify_signature(sig_id, "Sample digital signature") is True
            assert verify_signature(sig_id, "Forged value") is False

            # Tampering with the stored plaintext is detected
            with Session() as session:
                row = session.get(SignatureCapture, sig_id)
                row.signature = "Tampered signature"
                session.commit()
            assert verify_signature(sig_id) is False

            # Missing record raises
            try:
                verify_signature(99999)
                raise AssertionError("expected ValueError for missing signature")
            except ValueError:
                pass
        finally:
            from sqlalchemy.orm import close_all_sessions
            close_all_sessions()
            engine.dispose()

    print("Self-test completed successfully!")


if __name__ == "__main__":
    _selftest()
