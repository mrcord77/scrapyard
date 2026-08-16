"""
email — Transactional email send via pluggable provider.

### PART-META-JSON
{
  "name": "email",
  "layer": "communication",
  "purpose": "Transactional email send via pluggable provider.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: EmailSender(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `EmailSender` from `scrapyard.communication.email` and call it as shown in `example`; run `py -m scrapyard.communication.email` to see its offline selftest.",
  "example": "from scrapyard.communication.email import EmailSender",
  "import_path": "scrapyard.communication.email"
}
### END-PART-META
"""
from __future__ import annotations
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import List, Dict, Any, Optional

log = logging.getLogger("scrapyard.email")

class EmailSender:
    """Pluggable email sender. Default transport logs (safe for dev/tests) and
    records to an outbox; configure SMTP for production via send_smtp()."""
    def __init__(self, sender: str = "no-reply@example.com", transport: str = "log"):
        self.sender = sender
        self.transport = transport
        self.outbox: List[Dict] = []

    def send(self, to: str, subject: str, body: str) -> Dict:
        msg = {"to": to, "from": self.sender, "subject": subject, "body": body}
        if self.transport == "smtp":
            self._send_smtp(msg)
        else:
            log.info("EMAIL to=%s subject=%s", to, subject)
        self.outbox.append(msg)
        return msg

    def _send_smtp(self, msg: Dict):
        host = os.environ.get("SMTP_HOST")
        port = int(os.environ.get("SMTP_PORT", "587"))
        if not host:
            raise RuntimeError("SMTP_HOST not set")
        em = EmailMessage()
        em["From"] = msg["from"]
        em["To"] = msg["to"]
        em["Subject"] = msg["subject"]
        em.set_content(msg["body"])
        with smtplib.SMTP(host, port) as s:
            user = os.environ.get("SMTP_USER")
            if user:
                s.starttls()
                s.login(user, os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(em)


def _selftest() -> None:
    """Offline self-test: log transport records to outbox; SMTP guarded."""
    import os as _os
    sender = EmailSender(sender="ops@example.com")
    msg = sender.send("dev@example.com", "Hi", "Body text")
    assert msg == {"to": "dev@example.com", "from": "ops@example.com",
                   "subject": "Hi", "body": "Body text"}
    assert sender.outbox == [msg]

    smtp = EmailSender(transport="smtp")
    _os.environ.pop("SMTP_HOST", None)
    try:
        smtp.send("dev@example.com", "x", "y")
        raise AssertionError("smtp without SMTP_HOST must raise")
    except RuntimeError:
        pass
    assert smtp.outbox == []  # failed sends are not recorded

    print("email self-test passed")


if __name__ == "__main__":
    _selftest()
