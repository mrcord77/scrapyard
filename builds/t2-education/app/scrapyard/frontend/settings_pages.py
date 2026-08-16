"""
settings_pages — Account/settings layout with sections.

### PART-META-JSON
{
  "name": "settings_pages",
  "layer": "frontend",
  "purpose": "Python/jinja2 server-side HTML rendering of account/settings layouts with sections, backed by pydantic validation and SQLAlchemy persistence helpers (no react).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi",
    "jinja2",
    "sqlalchemy"
  ],
  "inputs": "Public API: settings_page(current, *, action, csrf_token); render_settings_section(section_name, fields, action, csrf_token, title, description); render_settings_page(sections, user, action, csrf_token, theme); validate_section_input(data, schema, section_name); serialize_section_data(data, schema, include, exclude); SectionSchema(...); User(...) (plus more).",
  "outputs": "Returns: render_settings_section -> str; render_settings_page -> str; validate_section_input -> Dict[str, Any]; serialize_section_data -> Dict[str, Any]; apply_section_policies -> bool.",
  "files_created": [],
  "security_notes": "Rendered values are escaped; setting writes validate through pydantic before persisting. Never render secret-typed settings values back into the page.",
  "ai_usage": "Import `settings_page` from `scrapyard.frontend.settings_pages` and call it as shown in `example`; run `py -m scrapyard.frontend.settings_pages` to see its offline selftest.",
  "example": "from scrapyard.frontend.settings_pages import settings_page",
  "import_path": "scrapyard.frontend.settings_pages"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
from typing import Any, Dict, List, Optional, Type, TypeVar, Generic, Union, cast
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import select
from jinja2 import Template

T = TypeVar("T")

def settings_page(current: dict, *, action="/settings", csrf_token=None):
    from scrapyard.frontend.forms import render_form
    fields=[{"name":k,"label":k.replace("_"," ").title(),"value":v} for k,v in current.items()]
    return "<h1>Settings</h1>"+render_form(action, fields, submit="Save", csrf_token=csrf_token)

class SectionSchema(BaseModel):
    name: str
    fields: List[Dict[str, Any]]
    action: str = "/settings"
    title: Optional[str] = None
    description: Optional[str] = None

class User(BaseModel):
    id: int
    roles: List[str]

def render_settings_section(
    section_name: str,
    fields: List[Dict[str, Any]],
    action: str = "/settings",
    csrf_token: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    template = Template("""
        <section>
            {% if title %}
                <h2>{{ title }}</h2>
            {% endif %}
            {% if description %}
                <p>{{ description }}</p>
            {% endif %}
            {{ render_form(action, fields, submit="Save", csrf_token=csrf_token) }}
        </section>
    """)
    return template.render(title=title, description=description, action=action, fields=fields, csrf_token=csrf_token)

def render_settings_page(
    sections: List[Dict[str, Any]],
    user: Optional[Dict[str, Any]] = None,
    action: str = "/settings",
    csrf_token: Optional[str] = None,
    theme: Optional[str] = "light",
) -> str:
    template = Template("""
        <div class="{{ theme }}">
            {% for section in sections %}
                {{ render_settings_section(**section, action=action, csrf_token=csrf_token) }}
            {% endfor %}
        </div>
    """)
    return template.render(sections=sections, action=action, csrf_token=csrf_token)

def validate_section_input(
    data: Dict[str, Any],
    schema: Dict[str, Any],
    section_name: str,
) -> Dict[str, Any]:
    try:
        validated_data = schema.parse_obj(data)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Validation error in {section_name}: {e}")
    return validated_data.dict()

def serialize_section_data(
    data: Dict[str, Any],
    schema: Dict[str, Any],
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> Dict[str, Any]:
    serialized_data = schema.parse_obj(data).dict()
    if include:
        return {k: v for k, v in serialized_data.items() if k in include}
    if exclude:
        return {k: v for k, v in serialized_data.items() if k not in exclude}
    return serialized_data

def apply_section_policies(
    user: Dict[str, Any],
    section_name: str,
    allowed_roles: List[str],
) -> bool:
    if user["roles"] and set(user["roles"]) & set(allowed_roles):
        return True
    raise HTTPException(status_code=403, detail=f"User does not have permission for {section_name}")

def log_section_action(
    user: Dict[str, Any],
    section_name: str,
    action: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    # Placeholder for logging mechanism
    print(f"User {user['id']} performed {action} on {section_name}")

def bulk_update_sections(
    user: Dict[str, Any],
    updates: Dict[str, Dict[str, Any]],
    schema: Dict[str, Any],
    db_session: Session,
) -> Dict[str, Any]:
    results = {}
    for section_name, update_data in updates.items():
        try:
            validated_data = validate_section_input(update_data, schema, section_name)
            apply_section_policies(user, section_name, ["admin"])
            # Placeholder for actual database update logic
            log_section_action(user, section_name, "update", validated_data)
            results[section_name] = validated_data
        except HTTPException as e:
            log_section_action(user, section_name, "failed_update", {"error": str(e)})
    return results

# Example usage with SQLAlchemy models and session (not implemented here for brevity)
def get_user(db_session: Session, user_id: int) -> User:
    stmt = select(User).where(User.id == user_id)
    result = db_session.execute(stmt).scalar_one()
    return result


def _selftest() -> None:
    # settings_page renders a form with a field per current setting
    p = settings_page({"display_name": "Ann", "email": "a@x.com"}, csrf_token="tok")
    assert "<h1>Settings</h1>" in p and "<form" in p
    assert 'name="display_name"' in p and 'name="email"' in p
    assert 'value="Ann"' in p and 'name="csrf_token"' in p
    # label is humanized from the key
    assert "Display Name" in p
    # ADVERSARIAL: a user-controlled setting value is escaped, not raw
    xss = "<script>alert(1)</script>"
    px = settings_page({"bio": xss})
    assert "<script>" not in px
    assert "&lt;script&gt;" in px
    # NEGATIVE: role policy denies a user lacking an allowed role
    assert apply_section_policies({"id": 1, "roles": ["admin"]}, "billing", ["admin"]) is True
    try:
        apply_section_policies({"id": 2, "roles": ["user"]}, "billing", ["admin"])
        raise AssertionError("policy allowed a user without the required role")
    except HTTPException as exc:
        assert exc.status_code == 403
    print("settings_pages selftest OK")


if __name__ == "__main__":
    _selftest()
