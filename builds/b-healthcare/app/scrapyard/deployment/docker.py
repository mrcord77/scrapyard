"""
docker — Multistage Dockerfile + compose generation with real validation.

### PART-META-JSON
{
  "name": "docker",
  "layer": "deployment",
  "purpose": "Generate Dockerfiles (single and multistage), docker-compose files, healthchecks and .env secrets - with real structural validation of Dockerfile instructions and compose YAML.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Python version/app module/port/base image/env maps for generators; Dockerfile or compose text for validators (PyYAML used lazily for compose when available).",
  "outputs": "Dockerfile/compose/healthcheck strings; appended .env lines from generate_secrets.",
  "files_created": [".env (or the file_path passed to generate_secrets - appended, not overwritten)"],
  "security_notes": "generate_secrets writes plaintext key=value to disk: keep the file out of version control and never bake it into images. Generated compose uses a default postgres password - override it in real deployments. Validators are structural (instruction/schema checks), not a security scanner.",
  "ai_usage": "content = generate_multistage_dockerfile(); assert validate_dockerfile(content); yml = generate_docker_compose(app_name='web'); assert validate_compose(yml).",
  "example": "from scrapyard.deployment.docker import generate_dockerfile, validate_dockerfile",
  "import_path": "scrapyard.deployment.docker"
}
### END-PART-META
"""
from __future__ import annotations

import re
from typing import List, Optional

import jinja2

STATUS = "core"

VALID_INSTRUCTIONS = {
    "FROM", "RUN", "CMD", "LABEL", "MAINTAINER", "EXPOSE", "ENV", "ADD", "COPY",
    "ENTRYPOINT", "VOLUME", "USER", "WORKDIR", "ARG", "ONBUILD", "STOPSIGNAL",
    "HEALTHCHECK", "SHELL",
}


def dockerfile(*, python="3.12", app="main:app", port=8000) -> str:
    lines = [
        f"FROM python:{python}-slim", "WORKDIR /app",
        "COPY requirements.txt .", "RUN pip install --no-cache-dir -r requirements.txt",
        "COPY . .", f"EXPOSE {port}",
        f'CMD ["uvicorn", "{app}", "--host", "0.0.0.0", "--port", "{port}"]']
    return "\n".join(lines) + "\n"


def compose(*, app="web", port=8000, with_postgres=True) -> str:
    lines = ["services:", f"  {app}:", "    build: .", f'    ports: ["{port}:{port}"]']
    if with_postgres:
        lines += ["  db:", "    image: postgres:16", "    environment:",
                  "      POSTGRES_PASSWORD: postgres",
                  '    volumes: ["pgdata:/var/lib/postgresql/data"]',
                  "volumes:", "  pgdata:"]
    return "\n".join(lines) + "\n"


def _secret_model():
    """Optional ORM model for storing deploy secrets (own Base, lazy so plain
    generation never needs SQLAlchemy loaded)."""
    from sqlalchemy import Column, Integer, String
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()

    class Secret(Base):
        __tablename__ = 'docker_secrets'
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String, unique=True, index=True)
        value = Column(String)

    return Base, Secret


def generate_dockerfile(
    *,
    python: str = "3.12",
    app: str = "main:app",
    port: int = 8000,
    base_image: str = "python:3.12-slim",
    build_args: dict | None = None,
    env_vars: dict | None = None,
) -> str:
    lines = [f"FROM {base_image}", "WORKDIR /app"]
    if build_args:
        for key, value in build_args.items():
            lines.append(f'ARG {key}={value}')
    if env_vars:
        for key, value in env_vars.items():
            lines.append(f'ENV {key}="{value}"')
    lines.extend([
        "COPY requirements.txt .",
        "RUN pip install --no-cache-dir -r requirements.txt",
        "COPY . .",
        f"EXPOSE {port}",
        f'CMD ["uvicorn", "{app}", "--host", "0.0.0.0", "--port", "{port}"]',
    ])
    return "\n".join(lines)


def generate_docker_compose(
    *,
    app_name: str = "web",
    port: int = 8000,
    with_postgres: bool = True,
    env_vars: dict | None = None,
    services: dict | None = None,
    volumes: dict | None = None,
) -> str:
    lines = ["services:", f"  {app_name}:", "    build: .",
             f'    ports: ["{port}:{port}"]']
    if env_vars:
        lines.append("    environment:")
        for key, value in env_vars.items():
            lines.append(f'      {key}: "{value}"')
    if services:
        for service_name, service_config in services.items():
            lines.append(f"  {service_name}:")
            for config_key, config_value in service_config.items():
                lines.append(f"    {config_key}: {config_value}")
    if with_postgres:
        lines += [
            "  db:",
            "    image: postgres:16",
            "    environment:",
            "      POSTGRES_PASSWORD: postgres",
            '    volumes: ["pgdata:/var/lib/postgresql/data"]',
        ]
    named_volumes = dict(volumes or {})
    if with_postgres:
        named_volumes.setdefault("pgdata", None)
    if named_volumes:
        lines.append("volumes:")
        for vol_name in named_volumes:
            lines.append(f"  {vol_name}:")
    return "\n".join(lines)


def render_template(template_name: str, context: dict) -> str:
    template_loader = jinja2.FileSystemLoader(searchpath="./")
    template_env = jinja2.Environment(loader=template_loader, autoescape=False)
    try:
        template = template_env.get_template(f"{template_name}.j2")
        return template.render(context)
    except jinja2.exceptions.TemplateNotFound as e:
        raise ValueError(f"Template {template_name} not found") from e


def _dockerfile_logical_lines(content: str) -> List[str]:
    """Join backslash continuations, drop comments/blank lines."""
    logical: List[str] = []
    pending = ""
    for raw in content.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue
        logical.append((pending + stripped).strip())
        pending = ""
    if pending.strip():
        logical.append(pending.strip())
    return logical


def validate_dockerfile(content: str, errors: Optional[List[str]] = None) -> bool:
    """REAL structural validation.

    Checks: non-empty; first instruction is FROM (ARG allowed before it); every
    instruction is a known Dockerfile keyword; FROM has an image; EXPOSE ports are
    numeric/valid; at most one CMD; stage names referenced by COPY --from exist.
    Pass an `errors` list to collect the reasons.
    """
    errs: List[str] = [] if errors is None else errors
    if not isinstance(content, str) or not content.strip():
        errs.append("empty Dockerfile")
        return False
    lines = _dockerfile_logical_lines(content)
    if not lines:
        errs.append("no instructions found")
        return False

    stages: List[str] = []
    cmd_count = 0
    seen_from = False
    for i, line in enumerate(lines):
        m = re.match(r"^(\S+)\s*(.*)$", line)
        instr, args = m.group(1).upper(), m.group(2)
        if instr not in VALID_INSTRUCTIONS:
            errs.append(f"line {i + 1}: unknown instruction {instr!r}")
            continue
        if not seen_from and instr not in ("FROM", "ARG"):
            errs.append(f"line {i + 1}: {instr} before first FROM")
        if instr == "FROM":
            seen_from = True
            fm = re.match(r"^(\S+)(?:\s+[Aa][Ss]\s+(\S+))?\s*$", args)
            if not fm or not fm.group(1):
                errs.append(f"line {i + 1}: FROM requires an image")
            elif fm.group(2):
                stages.append(fm.group(2))
        elif instr == "EXPOSE":
            for p in args.split():
                port_part = p.split("/")[0]
                if not port_part.isdigit() or not (0 < int(port_part) <= 65535):
                    errs.append(f"line {i + 1}: invalid EXPOSE port {p!r}")
        elif instr == "CMD":
            cmd_count += 1
            if not args.strip():
                errs.append(f"line {i + 1}: CMD requires arguments")
        elif instr == "COPY":
            cm = re.search(r"--from=(\S+)", args)
            if cm:
                ref = cm.group(1)
                # numeric index or a previously defined stage name is valid
                if not ref.isdigit() and ref not in stages:
                    errs.append(f"line {i + 1}: COPY --from references "
                                f"unknown stage {ref!r}")
            if len(args.split()) < 2 and "--from" not in args:
                errs.append(f"line {i + 1}: COPY requires src and dest")
    if not seen_from:
        errs.append("missing FROM instruction")
    if cmd_count > 1:
        errs.append(f"multiple CMD instructions ({cmd_count}); only the last takes effect")
    return not errs


def validate_compose(content: str, errors: Optional[List[str]] = None) -> bool:
    """REAL compose validation: YAML-parse (lazy PyYAML, structural fallback),
    then schema basics - top-level mapping with a non-empty 'services' mapping;
    each service is a mapping defining 'image' or 'build'; 'volumes'/'networks'
    top-level keys must be mappings. Pass `errors` to collect reasons."""
    errs: List[str] = [] if errors is None else errors
    if not isinstance(content, str) or not content.strip():
        errs.append("empty compose file")
        return False
    try:
        import yaml  # lazy optional
    except ImportError:
        # structural fallback: require a services: block with at least one service
        if not re.search(r"(?m)^services:\s*$", content):
            errs.append("missing top-level 'services:' block")
            return False
        if not re.search(r"(?m)^  \S+:", content):
            errs.append("'services:' block defines no services")
            return False
        return True

    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError as e:
        errs.append(f"invalid YAML: {e}")
        return False
    if not isinstance(doc, dict):
        errs.append("compose root must be a mapping")
        return False
    services = doc.get("services")
    if not isinstance(services, dict) or not services:
        errs.append("'services' must be a non-empty mapping")
        return False
    for name, svc in services.items():
        if not isinstance(svc, dict):
            errs.append(f"service {name!r} must be a mapping")
            continue
        if "image" not in svc and "build" not in svc:
            errs.append(f"service {name!r} needs 'image' or 'build'")
        ports = svc.get("ports")
        if ports is not None and not isinstance(ports, list):
            errs.append(f"service {name!r}: 'ports' must be a list")
    for key in ("volumes", "networks"):
        if key in doc and doc[key] is not None and not isinstance(doc[key], dict):
            errs.append(f"top-level {key!r} must be a mapping")
    return not errs


def generate_multistage_dockerfile(
    *,
    build_stage: str = "builder",
    runtime_stage: str = "runtime",
    base_image: str = "python:3.12-slim",
    env_vars: dict | None = None,
) -> str:
    lines = [
        f"FROM {base_image} AS {build_stage}",
        "WORKDIR /app",
        "COPY requirements.txt .",
        "RUN pip install --no-cache-dir -r requirements.txt",
    ]
    if env_vars:
        for key, value in env_vars.items():
            lines.append(f'ENV {key}="{value}"')
    lines.extend([
        f"FROM {base_image} AS {runtime_stage}",
        "WORKDIR /app",
        f"COPY --from={build_stage} /app /app",  # fixed: was a literal "{build_stage}"
    ])
    return "\n".join(lines)


def generate_secrets(*, secret_name: str, value: str, file_path: str = ".env") -> None:
    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(f"{secret_name}={value}\n")


def generate_healthcheck(*, command: str = "curl -f http://localhost:8000/health",
                         interval: str = "10s", timeout: str = "5s") -> str:
    return f'HEALTHCHECK --interval={interval} --timeout={timeout} CMD {command}'


def _selftest() -> bool:
    import os
    import tempfile

    # generators produce valid artifacts
    df = generate_dockerfile(env_vars={"MODE": "prod"}, build_args={"VER": "1"})
    assert validate_dockerfile(df), df
    assert dockerfile().startswith("FROM python:3.12-slim")
    assert '"--port", "8000"' in dockerfile()

    # multistage: the f-string is fixed - no literal '{build_stage}' remains
    ms = generate_multistage_dockerfile(build_stage="deps", runtime_stage="app")
    assert "{build_stage}" not in ms and "COPY --from=deps /app /app" in ms
    assert ms.count("FROM") == 2
    assert validate_dockerfile(ms), ms

    # dockerfile validation is REAL: rejects garbage
    errs: List[str] = []
    assert not validate_dockerfile("", errs) and "empty" in errs[0]
    assert not validate_dockerfile("RUN echo hi\n")                    # no FROM
    assert not validate_dockerfile("FROM x\nFLY to the moon\n")        # unknown instr
    assert not validate_dockerfile("FROM x\nEXPOSE 99999\n")           # bad port
    assert not validate_dockerfile("FROM x\nCOPY --from=nope /a /b\n")  # unknown stage
    e2: List[str] = []
    assert not validate_dockerfile("FROM x\nCMD a\nCMD b\n", e2)
    assert any("multiple CMD" in e for e in e2)
    # ARG before FROM + continuations + comments are fine
    assert validate_dockerfile("# comment\nARG V=1\nFROM x\nRUN echo a \\\n && echo b\n")

    # compose validation is REAL
    yml = generate_docker_compose(app_name="api", env_vars={"A": "1"})
    assert validate_compose(yml), yml
    assert validate_compose(compose())
    assert not validate_compose("")
    assert not validate_compose("services: []\n")                       # not a mapping
    assert not validate_compose("nothing: here\n")
    e3: List[str] = []
    assert not validate_compose("services:\n  web:\n    ports: [\"80:80\"]\n", e3)
    assert any("image" in e for e in e3)                                # no image/build
    assert not validate_compose("services:\n  web:\n    build: .\n    ports: 80\n")

    # secrets append + healthcheck string
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        env = os.path.join(td, ".env")
        generate_secrets(secret_name="API_KEY", value="abc", file_path=env)
        generate_secrets(secret_name="OTHER", value="x", file_path=env)
        with open(env, encoding="utf-8") as f:
            body = f.read()
        assert body == "API_KEY=abc\nOTHER=x\n"
    hc = generate_healthcheck()
    assert hc.startswith("HEALTHCHECK --interval=10s --timeout=5s CMD ")

    print("docker selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
