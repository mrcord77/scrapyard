"""
shell_completion — Generates shell completion scripts for CLI applications, enabling seamless integration with bash, zsh, and other shells. It abstracts the complexity of shell-specific syntax and provides a consistent 

### PART-META-JSON
{
  "name": "shell_completion",
  "layer": "clitools",
  "purpose": "Generates shell completion scripts for CLI applications, enabling seamless integration with bash, zsh, and other shells. It abstracts the complexity of shell-specific syntax and provides a consistent ",
  "addition": true,
  "status": "core",
  "dependencies": [
    "argument_parsing_scaffold"
  ],
  "inputs": "Public API: generate_completion_script(app_name, parser); CompletionGenerator(...).",
  "outputs": "Returns: generate_completion_script -> str.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.clitools.shell_completion`.",
  "example": "from scrapyard.clitools.shell_completion import *",
  "import_path": "scrapyard.clitools.shell_completion"
}
### END-PART-META
"""

from argparse import ArgumentParser
from dataclasses import dataclass
from typing import List
import logging

logger = logging.getLogger(__name__)


@dataclass
class CompletionGenerator:
    parser: ArgumentParser
    
    def generate_bash_completion_script(self) -> str:
        """
        Generate a bash completion script based on the parsed command-line arguments.
        """
        lines: List[str] = []
        prog = self.parser.prog or "app"
        
        lines.append(f"_{prog}_completions() {{")
        lines.append("    local cur=\"${COMP_WORDS[COMP_CWORD]}\"")
        lines.append("    case \"$cur\" in")
        
        for action in self.parser._actions:
            if hasattr(action, 'choices') and action.choices:
                for choice in action.choices:
                    choice_str = str(choice)
                    lines.append(f'        {choice_str}*) compadd {choice_str} ;;')
        
        lines.append("        *) ;;")
        lines.append("    esac")
        lines.append("}")
        lines.append(f"complete -F _{prog}_completions {prog}")
        
        return "\n".join(lines)

    def generate_zsh_completion_script(self) -> str:
        """
        Generate a zsh completion script based on the parsed command-line arguments.
        """
        lines: List[str] = []
        prog = self.parser.prog or "app"
        
        lines.append(f"#compdef {prog}")
        lines.append(f"_{prog}() {{")
        
        for action in self.parser._actions:
            if hasattr(action, 'choices') and action.choices:
                for choice in action.choices:
                    choice_str = str(choice)
                    lines.append(f'    compadd -W . -- {choice_str}')
        
        lines.append("}")
        lines.append(f"compdef _{prog} {prog}")
        
        return "\n".join(lines)


def generate_completion_script(app_name: str, parser: ArgumentParser) -> str:
    """
    Auto-generates bash/zsh completion scripts from parsed CLI argument schemas.
    
    :param app_name: Name of the application for which to generate completions.
    :param parser: Parsed command-line arguments object.
    :return: A string containing the generated shell completion script.
    """
    generator = CompletionGenerator(parser)
    bash_script = generator.generate_bash_completion_script()
    zsh_script = generator.generate_zsh_completion_script()
    
    return f"""# Bash completion for {app_name}
if [[ -n "$BASH_VERSION" ]]; then
{bash_script}
fi

# Zsh completion for {app_name}
if [[ -n "$ZSH_VERSION" ]]; then
{zsh_script}
fi"""


def _selftest() -> None:
    parser = ArgumentParser(description="Test CLI")
    parser.add_argument('--arg1', choices=['a', 'b', 'c'])
    parser.add_argument('--arg2', choices=[1, 2, 3])
    
    completion_script = generate_completion_script('testapp', parser)
    assert "compadd a" in completion_script, f"Missing 'compadd a' in script"
    assert "compadd -W . -- c" in completion_script, f"Missing 'compadd -W . -- c' in script"
    logger.info("Self-test passed successfully")


if __name__ == "__main__":
    _selftest()
