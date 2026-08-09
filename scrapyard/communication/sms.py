"""
sms — SMS send via pluggable provider.

### PART-META-JSON
{
  "name": "sms",
  "layer": "communication",
  "purpose": "SMS send via pluggable provider.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: SMSSender(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Makes outbound network calls; set timeouts, validate URLs/hosts, and never send secrets to untrusted endpoints.",
  "ai_usage": "Import `SMSSender` from `scrapyard.communication.sms` and call it as shown in `example`; run `py -m scrapyard.communication.sms` to see its offline selftest.",
  "example": "from scrapyard.communication.sms import SMSSender",
  "import_path": "scrapyard.communication.sms"
}
### END-PART-META
"""
from __future__ import annotations
import logging, os
STATUS = "core"
log=logging.getLogger("scrapyard.sms")
class SMSSender:
    """Pluggable SMS sender; logs in dev, records to outbox, uses Twilio when
    TWILIO_* env vars are set."""
    def __init__(self): self.outbox=[]
    def send(self, to: str, body: str) -> dict:
        msg={"to":to,"body":body}
        if os.environ.get("TWILIO_ACCOUNT_SID"):
            self._send_twilio(msg)
        else:
            log.info("SMS to=%s", to)
        self.outbox.append(msg); return msg
    def _send_twilio(self, msg):
        import urllib.request, urllib.parse, os
        sid=os.environ["TWILIO_ACCOUNT_SID"]; tok=os.environ["TWILIO_AUTH_TOKEN"]
        frm=os.environ.get("TWILIO_FROM","")
        data=urllib.parse.urlencode({"To":msg["to"],"From":frm,"Body":msg["body"]}).encode()
        req=urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data)
        import base64
        req.add_header("Authorization","Basic "+base64.b64encode(f"{sid}:{tok}".encode()).decode())
        urllib.request.urlopen(req)


def _selftest() -> None:
    """Offline self-test: dev transport logs and records to outbox."""
    import os as _os
    _os.environ.pop("TWILIO_ACCOUNT_SID", None)
    s = SMSSender()
    msg = s.send("+15551234567", "hello")
    assert msg == {"to": "+15551234567", "body": "hello"}
    assert s.outbox == [msg]
    s.send("+15557654321", "second")
    assert len(s.outbox) == 2
    print("sms self-test passed")


if __name__ == "__main__":
    _selftest()
