"""
seo_metadata — Per-page title/description/OG/Twitter tags.

### PART-META-JSON
{
  "name": "seo_metadata",
  "layer": "content",
  "purpose": "Per-page title/description/OG/Twitter tags.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: validate_seo_data(data); generate_seo_from_content(content, config); serialize_seo_for_export(seo_data); audit_seo_change(old, new); get_seo_metadata(page_id, db_session); SEODataModel(...); SEOCreateModel(...); SEOModelUpdate(...) (plus more).",
  "outputs": "Returns: validate_seo_data -> ValidationResult; generate_seo_from_content -> SEODataModel; serialize_seo_for_export -> Dict[str, Any]; audit_seo_change -> AuditLog; get_seo_metadata -> SEODataModel.",
  "files_created": [],
  "security_notes": "Renders HTML with all caller text escaped via html.escape (XSS-safe); any HTML 'slot' arguments are inserted verbatim and must be pre-escaped by the caller. Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `validate_seo_data` from `scrapyard.content.seo_metadata` and call it as shown in `example`; run `py -m scrapyard.content.seo_metadata` to see its offline selftest.",
  "example": "from scrapyard.content.seo_metadata import validate_seo_data",
  "import_path": "scrapyard.content.seo_metadata"
}
### END-PART-META
"""
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import select
from datetime import datetime, timezone
import re

STATUS = "core"

class SEODataModel(BaseModel):
    title: str
    description: str
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_url: Optional[str] = None
    og_image: Optional[str] = None

class SEOCreateModel(BaseModel):
    title: str
    description: str
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_url: Optional[str] = None
    og_image: Optional[str] = None

class SEOModelUpdate(BaseModel):
    title: Optional[str]
    description: Optional[str]
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_url: Optional[str] = None
    og_image: Optional[str] = None

class SEOFilterModel(BaseModel):
    page_id: Optional[UUID] = None
    title: Optional[str] = None
    description: Optional[str] = None

class PaginationModel(BaseModel):
    limit: int = Field(default=10, ge=1)
    offset: int = Field(default=0, ge=0)

class SEOGenerationConfig(BaseModel):
    title_max_length: int = Field(default=60, ge=10, le=120)
    description_max_length: int = Field(default=160, ge=40, le=320)
    fallback_title: str = "Untitled page"

class ValidationResult(BaseModel):
    valid: bool
    errors: List[str]

class AuditLog(BaseModel):
    old_data: Dict[str, Any]
    new_data: Dict[str, Any]
    timestamp: str

class InvalidInputError(Exception):
    pass

class MissingFieldError(Exception):
    pass

class PolicyViolationError(Exception):
    pass

class DuplicateEntryError(Exception):
    pass

def validate_seo_data(data: SEODataModel) -> ValidationResult:
    errors = []
    if not data.title.strip(): errors.append("title is required")
    if len(data.title) > 60: errors.append("title exceeds 60 characters")
    if not data.description.strip(): errors.append("description is required")
    if len(data.description) > 160: errors.append("description exceeds 160 characters")
    for field in ("og_url", "og_image"):
        value = getattr(data, field)
        if value and not value.startswith(("https://", "http://")):
            errors.append(f"{field} must use http or https")
    return ValidationResult(valid=not errors, errors=errors)

def generate_seo_from_content(content: str, config: SEOGenerationConfig) -> SEODataModel:
    text = re.sub(r"<[^>]+>", " ", content or "")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise InvalidInputError("content must contain text")
    first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    title = first_sentence[:config.title_max_length].rstrip(" ,.;:-")
    if not title: title = config.fallback_title
    description = text[:config.description_max_length].rstrip()
    return SEODataModel(title=title, description=description,
                        og_title=title, og_description=description)

def serialize_seo_for_export(seo_data: SEODataModel) -> Dict[str, Any]:
    return seo_data.dict()

def audit_seo_change(old: SEODataModel, new: SEODataModel) -> AuditLog:
    return AuditLog(old_data=old.model_dump(), new_data=new.model_dump(),
                    timestamp=datetime.now(timezone.utc).isoformat())

class YourSEOModel:
    def __init__(self, page_id: UUID, title: str, description: str, og_title: Optional[str] = None, og_description: Optional[str] = None, og_url: Optional[str] = None, og_image: Optional[str] = None):
        self.page_id = page_id
        self.title = title
        self.description = description
        self.og_title = og_title
        self.og_description = og_description
        self.og_url = og_url
        self.og_image = og_image

def get_seo_metadata(page_id: UUID, db_session: Session) -> SEODataModel:
    try:
        query = select(YourSEOModel).where(YourSEOModel.page_id == page_id)
        result = db_session.execute(query).scalar_one()
        return SEODataModel(
            title=result.title,
            description=result.description,
            og_title=result.og_title,
            og_description=result.og_description,
            og_url=result.og_url,
            og_image=result.og_image
        )
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Page not found")
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))

def create_seo_metadata(data: SEOCreateModel, db_session: Session) -> SEODataModel:
    seo_data = YourSEOModel(
        page_id=data.page_id,
        title=data.title,
        description=data.description,
        og_title=data.og_title,
        og_description=data.og_description,
        og_url=data.og_url,
        og_image=data.og_image
    )
    try:
        db_session.add(seo_data)
        db_session.commit()
        return SEODataModel(
            title=seo_data.title,
            description=seo_data.description,
            og_title=seo_data.og_title,
            og_description=seo_data.og_description,
            og_url=seo_data.og_url,
            og_image=seo_data.og_image
        )
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))

def update_seo_metadata(page_id: UUID, data: SEOModelUpdate, db_session: Session) -> SEODataModel:
    try:
        query = select(YourSEOModel).where(YourSEOModel.page_id == page_id)
        result = db_session.execute(query).scalar_one()
        for key, value in data.dict(exclude_unset=True).items():
            setattr(result, key, value)
        db_session.commit()
        return SEODataModel(
            title=result.title,
            description=result.description,
            og_title=result.og_title,
            og_description=result.og_description,
            og_url=result.og_url,
            og_image=result.og_image
        )
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Page not found")
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))

def delete_seo_metadata(page_id: UUID, db_session: Session) -> None:
    try:
        query = select(YourSEOModel).where(YourSEOModel.page_id == page_id)
        result = db_session.execute(query).scalar_one()
        db_session.delete(result)
        db_session.commit()
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Page not found")
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))

def list_seo_metadata(filters: SEOFilterModel, pagination: PaginationModel, db_session: Session) -> List[SEODataModel]:
    query = select(YourSEOModel)
    if filters.page_id:
        query = query.where(YourSEOModel.page_id == filters.page_id)
    if filters.title:
        query = query.where(YourSEOModel.title == filters.title)
    if filters.description:
        query = query.where(YourSEOModel.description == filters.description)
    try:
        results = db_session.execute(query).scalars().all()
        return [SEODataModel(
            title=r.title,
            description=r.description,
            og_title=r.og_title,
            og_description=r.og_description,
            og_url=r.og_url,
            og_image=r.og_image
        ) for r in results]
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))

def bulk_update_seo_metadata(data: List[SEOModelUpdate], db_session: Session) -> List[SEODataModel]:
    updated_data = []
    for update in data:
        try:
            query = select(YourSEOModel).where(YourSEOModel.page_id == update.page_id)
            result = db_session.execute(query).scalar_one()
            for key, value in update.dict(exclude_unset=True).items():
                setattr(result, key, value)
            db_session.commit()
            updated_data.append(SEODataModel(
                title=result.title,
                description=result.description,
                og_title=result.og_title,
                og_description=result.og_description,
                og_url=result.og_url,
                og_image=result.og_image
            ))
        except NoResultFound:
            raise HTTPException(status_code=404, detail="Page not found")
    return updated_data


# --- grafted from original part (API stability) ---
import html

def meta_tags(*, title, description, url=None, image=None) -> str:
    e=html.escape
    tags=[f'<title>{e(title)}</title>',
          f'<meta name="description" content="{e(description)}">',
          f'<meta property="og:title" content="{e(title)}">',
          f'<meta property="og:description" content="{e(description)}">']
    if url: tags.append(f'<meta property="og:url" content="{e(url)}">')
    if image: tags.append(f'<meta property="og:image" content="{e(image)}">')
    return "\n".join(tags)


def _selftest() -> None:
    """Offline self-test: meta_tags emits the expected title/description/OpenGraph
    tags, includes optional og:url / og:image only when provided, and HTML-escapes
    all values so injected markup cannot break out of the attribute."""
    html_out = meta_tags(title="My Page", description="A great page")
    generated = generate_seo_from_content(
        "A concise title. This is useful supporting copy.", SEOGenerationConfig())
    assert generated.title == "A concise title"
    assert validate_seo_data(generated).valid
    assert audit_seo_change(generated, generated).timestamp.endswith("+00:00")
    try:
        generate_seo_from_content("   ", SEOGenerationConfig())
        raise AssertionError("accepted empty content")
    except InvalidInputError:
        pass

    # Required tags are present with the given values.
    assert "<title>My Page</title>" in html_out, html_out
    assert '<meta name="description" content="A great page">' in html_out
    assert '<meta property="og:title" content="My Page">' in html_out
    assert '<meta property="og:description" content="A great page">' in html_out

    # Optional tags are omitted when their inputs are absent...
    assert "og:url" not in html_out and "og:image" not in html_out

    # ...and included when supplied.
    full = meta_tags(title="T", description="D", url="https://x.test/p",
                     image="https://x.test/i.png")
    assert '<meta property="og:url" content="https://x.test/p">' in full
    assert '<meta property="og:image" content="https://x.test/i.png">' in full

    # Negative/adversarial: an injected <script>/quote payload must be escaped, not
    # emitted as live markup that could break the tag or inject script.
    xss = meta_tags(title='<script>alert("x")</script>', description='" onload="evil()')
    assert "<script>" not in xss, "raw <script> leaked into output (XSS)"
    assert "&lt;script&gt;" in xss
    assert 'onload="evil()' not in xss.replace("&quot;", ""), "attribute break-out not escaped"
    assert "&quot;" in xss

    # validate_seo_data returns a well-formed ValidationResult for valid input.
    res = validate_seo_data(SEODataModel(title="t", description="d"))
    assert res.valid is True and res.errors == []

    # serialize_seo_for_export round-trips the model fields.
    dumped = serialize_seo_for_export(SEODataModel(title="t", description="d", og_title="ot"))
    assert dumped["title"] == "t" and dumped["og_title"] == "ot"

    print("seo_metadata selftest: PASS")


if __name__ == "__main__":
    _selftest()
