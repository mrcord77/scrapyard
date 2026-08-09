"""
interactive_prompts — Manages interactive prompts for user input in CLI applications, providing flexible and reusable input handling with session-based state.

### PART-META-JSON
{
  "name": "interactive_prompts",
  "layer": "clitools",
  "purpose": "Interactive CLI prompts (ask/confirm/password) with defaults, validation, injectable input for testing, and EOF-safe non-interactive fallback.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "prompt text, optional default, optional validate callable; optional input_fn for non-tty use.",
  "outputs": "User-entered (or defaulted) strings / booleans; passwords via getpass.",
  "files_created": [],
  "security_notes": "password() uses getpass so input is not echoed; never log returned passwords. On EOF (non-interactive), prompts fall back to the default rather than crashing - do not rely on prompts as a security gate in unattended runs.",
  "ai_usage": "Import PromptSession or get_user_input from `scrapyard.clitools.interactive_prompts`. Pass input_fn to script answers in tests.",
  "example": "from scrapyard.clitools.interactive_prompts import PromptSession; PromptSession().ask('Name?', default='anon')",
  "import_path": "scrapyard.clitools.interactive_prompts"
}
### END-PART-META
"""

from typing import Optional, Dict, Callable
import logging

logger = logging.getLogger(__name__)

STATUS = "core"

InputFn = Callable[[str], str]


def _read(prompt_text: str, input_fn: Optional[InputFn], default: Optional[str]) -> Optional[str]:
    """Read one line via input_fn (or builtin input). Returns None on EOF/interrupt
    so callers can fall back to the default instead of crashing headless."""
    reader = input_fn if input_fn is not None else input
    try:
        return reader(prompt_text)
    except (EOFError, KeyboardInterrupt):
        logger.debug("No interactive input available; falling back to default %r", default)
        return None


class PromptSession:
    """Reusable prompt session. `context` carries arbitrary state across prompts;
    `input_fn` lets tests (or non-tty callers) inject scripted answers."""

    def __init__(self, context: Optional[Dict] = None, input_fn: Optional[InputFn] = None):
        self.context = context if context is not None else {}
        self.input_fn = input_fn

    def ask(self, prompt: str, default: Optional[str] = None,
            validate: Optional[Callable[[str], bool]] = None) -> str:
        while True:
            user_input = _read(f"{prompt} [{default or ''}]: ", self.input_fn, default)
            if user_input is None:  # EOF / non-interactive
                if default is not None:
                    return default
                raise EOFError(f"No input available for prompt {prompt!r} and no default given")
            if not user_input and default is not None:
                return default
            if validate is None or validate(user_input):
                return user_input
            logger.warning("Invalid input. Please try again.")

    def confirm(self, prompt: str, default: bool = False) -> bool:
        while True:
            user_input = _read(f"{prompt} [{'Y/n' if default else 'y/N'}]: ",
                               self.input_fn, str(default))
            if user_input is None or not user_input.strip():
                return default
            answer = user_input.strip().lower()
            if answer in ('y', 'yes'):
                return True
            if answer in ('n', 'no'):
                return False
            logger.warning("Invalid input. Please answer y or n.")

    def password(self, prompt: str) -> str:
        if self.input_fn is not None:  # scripted/testing path — never echoes
            value = _read(prompt, self.input_fn, "")
            return value if value is not None else ""
        import getpass
        try:
            return getpass.getpass(prompt)
        except (EOFError, KeyboardInterrupt):
            return ""


def get_user_input(prompt: str, default: Optional[str] = None,
                   validate: Optional[Callable[[str], bool]] = None,
                   input_fn: Optional[InputFn] = None) -> str:
    """Module-level one-shot prompt with the same semantics as PromptSession.ask."""
    return PromptSession(input_fn=input_fn).ask(prompt, default=default, validate=validate)


def _selftest():
    # Scripted answers: fully offline, no tty required.
    def scripted(*answers):
        answer_iter = iter(answers)

        def fn(_prompt: str) -> str:
            try:
                return next(answer_iter)
            except StopIteration:
                raise EOFError
        return fn

    # Defaults apply on empty input
    assert get_user_input("Enter your name", "John Doe", input_fn=scripted("")) == "John Doe"
    # Explicit answer wins over default
    assert get_user_input("Enter your name", "John Doe", input_fn=scripted("Alice")) == "Alice"
    # Validation: first answer rejected, second accepted
    assert get_user_input("Enter a number (1-10)", default="5", input_fn=scripted("99", "7"),
                          validate=lambda x: x.isdigit() and 1 <= int(x) <= 10) == "7"
    # EOF (no input at all) falls back to the default
    assert get_user_input("Enter a number", default="5", input_fn=scripted()) == "5"
    # EOF with no default raises
    try:
        get_user_input("Required", input_fn=scripted())
    except EOFError:
        pass
    else:
        raise AssertionError("EOF without default must raise EOFError")

    session = PromptSession(input_fn=scripted("Alice", "y", "n", "", "maybe", "yes", "s3cret"))
    assert session.ask("What is your name?", "Bob") == "Alice"
    assert session.confirm("Are you sure?", False) is True
    assert session.confirm("Delete everything?", True) is False
    assert session.confirm("Use default?", True) is True          # empty -> default
    assert session.confirm("Retry?", False) is True               # 'maybe' rejected, then 'yes'
    assert session.password("Enter your password: ") == "s3cret"

    # EOF-safe confirm in a fully non-interactive session
    eof_session = PromptSession(input_fn=scripted())
    assert eof_session.confirm("Proceed?", default=True) is True

    print("All tests passed.")


if __name__ == "__main__":
    _selftest()
