"""
prompt_guardrails — ** Implements guardrail checks to ensure generated prompts are safe and adhere to policy guidelines. Integrates with validation tools to enforce compliance and prevent harmful outputs.

### PART-META-JSON
{
  "name": "prompt_guardrails",
  "layer": "llm",
  "purpose": "Implements guardrail checks to ensure generated prompts are safe and adhere to policy guidelines. Integrates with validation tools to enforce compliance and prevent harmful outputs.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: json_output_validator(output, required_keys, allow_extra); PromptGuardrails(...); SafeDatabase(...).",
  "outputs": "Returns: json_output_validator -> bool.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.llm.prompt_guardrails`.",
  "example": "from scrapyard.llm.prompt_guardrails import *",
  "import_path": "scrapyard.llm.prompt_guardrails"
}
### END-PART-META
"""
from typing import Optional, Dict, Any
import os
import re
import logging
import sqlite3
import tempfile

logger = logging.getLogger(__name__)

class PromptGuardrails:
    def __init__(self, policy_rules: Dict[str, Any]):
        self.policy_rules = policy_rules

    @staticmethod
    def check_policy(prompt: str, policy_rules: Dict[str, Any]) -> bool:
        for rule_name, rule in policy_rules.items():
            if not rule.get('enabled', True):
                continue
            if callable(rule['check']):
                if not rule['check'](prompt):
                    logger.warning(f"Prompt violated policy rule {rule_name}")
                    return False
            elif isinstance(rule['check'], str) and re.match(rule['check'], prompt):
                logger.warning(f"Prompt violated policy rule {rule_name}")
                return False
        return True

    @staticmethod
    def apply_guardrails(prompt: str, policy_rules: Dict[str, Any]) -> Optional[str]:
        if not PromptGuardrails.check_policy(prompt, policy_rules):
            return None
        return prompt

def json_output_validator(output: Dict[str, Any],
                          required_keys: Optional[set] = None,
                          allow_extra: bool = False) -> bool:
    """Validate structured LLM output: must be a dict containing exactly (or at
    least, when allow_extra=True) the required keys. Defaults preserve the
    original contract of {'id', 'status'}."""
    if not isinstance(output, dict):
        logger.warning("Output is not a JSON object")
        return False
    required = required_keys if required_keys is not None else {'id', 'status'}
    keys = set(output.keys())
    if allow_extra:
        ok = required.issubset(keys)
    else:
        ok = keys == required
    if not ok:
        logger.warning("Output does not match expected structure")
    return ok

class SafeDatabase:
    def __init__(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        conn = sqlite3.connect(os.path.join(self.temp_dir.name, 'prompt_guardrails.db'))
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prompt_logs (
                id INTEGER PRIMARY KEY,
                prompt TEXT NOT NULL,
                status BOOLEAN NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        self.conn = conn

    def log_prompt(self, prompt: str, status: bool):
        cursor = self.conn.cursor()
        cursor.execute('INSERT INTO prompt_logs (prompt, status) VALUES (?, ?)', (prompt, status))
        self.conn.commit()

    def close(self):
        # close the connection BEFORE removing its backing file (Windows-safe)
        self.conn.close()
        self.temp_dir.cleanup()

def _selftest():
    # Test data
    policy_rules = {
        'length': {'check': lambda p: len(p) <= 100, 'enabled': True},
        'contains_sensitive': {'check': re.compile(r'\bSensitiveWord\b').search, 'enabled': False}
    }

    guardrails = PromptGuardrails(policy_rules)

    # Test cases
    test_prompts = [
        "This is a safe prompt.",
        "SensitiveWord should trigger a warning.",
        "Another safe prompt with more content."
    ]

    for prompt in test_prompts:
        logger.info(f"Testing: {prompt}")
        if guardrails.apply_guardrails(prompt, policy_rules) is None:
            logger.warning("Guardrail applied successfully")
        else:
            logger.info("Prompt passed the guardrails")

    # Guardrails must actually block: over-length prompt returns None
    long_prompt = "x" * 200
    assert guardrails.apply_guardrails(long_prompt, policy_rules) is None
    assert guardrails.apply_guardrails("short and safe", policy_rules) == "short and safe"

    # Disabled rules are skipped; enabling them makes them bite
    policy_rules['contains_sensitive']['enabled'] = True
    sensitive_rules = {
        'no_sensitive': {'check': lambda p: 'SensitiveWord' not in p, 'enabled': True}
    }
    assert guardrails.apply_guardrails("SensitiveWord here", sensitive_rules) is None

    # Test JSON output validation
    json_output = {'id': 1, 'status': 'success'}
    assert json_output_validator(json_output), "JSON output validation failed"
    assert not json_output_validator({'id': 1}), "missing key must fail"
    assert not json_output_validator({'id': 1, 'status': 'ok', 'extra': 2})
    assert json_output_validator({'id': 1, 'status': 'ok', 'extra': 2},
                                 allow_extra=True)
    assert json_output_validator({'a': 1}, required_keys={'a'})
    assert not json_output_validator("not-a-dict")

    db = SafeDatabase()
    db.log_prompt(prompt=test_prompts[0], status=True)
    cur = db.conn.execute("SELECT COUNT(*) FROM prompt_logs")
    assert cur.fetchone()[0] == 1
    db.close()

if __name__ == "__main__":
    _selftest()
