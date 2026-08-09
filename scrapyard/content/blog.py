"""
blog — Blog posts with tags, slugs, drafts.

### PART-META-JSON
{
  "name": "blog",
  "layer": "content",
  "purpose": "Blog posts with tags, slugs, drafts.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: Post(...); BlogService(...); SlugConflictError(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `Post` from `scrapyard.content.blog` and call it as shown in `example`; run `py -m scrapyard.content.blog` to see its offline selftest.",
  "example": "from scrapyard.content.blog import Post",
  "import_path": "scrapyard.content.blog"
}
### END-PART-META
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, Text, Boolean, DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel
def _slugify(t): 
    import re; return re.sub(r"[^a-z0-9]+","-",t.lower()).strip("-")
class Post(IntPKModel):
    __tablename__="blog_posts"
    title: Mapped[str]=mapped_column(String(200)); slug: Mapped[str]=mapped_column(String(220), unique=True, index=True)
    body: Mapped[str]=mapped_column(Text, default=""); published: Mapped[bool]=mapped_column(Boolean, default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), server_default=func.now())
class BlogService:
    def __init__(self, db): self.db=db
    def create(self, title, body, published=False):
        p=Post(title=title, slug=_slugify(title), body=body, published=published)
        self.db.add(p); self.db.flush(); return p
    def published(self):
        return list(self.db.scalars(select(Post).where(Post.published==True).order_by(Post.created_at.desc())))
    def by_slug(self, slug): 
        return self.db.scalars(select(Post).where(Post.slug==slug)).first()

from typing import List, Dict, Any, Optional, Callable
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException, status

class SlugConflictError(HTTPException):
    def __init__(self, detail: str = "Slug already exists"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)

class InvalidInputError(HTTPException):
    def __init__(self, detail: str = "Invalid input provided"):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

class NotFoundError(HTTPException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

class InvalidTagError(InvalidInputError):
    def __init__(self, detail: str = "Invalid tag provided"):
        super().__init__(detail=detail)

class BulkCreateError(HTTPException):
    def __init__(self, detail: str = "Failed to create one or more posts in bulk"):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

class PostTag(IntPKModel):
    """Tag attached to a blog post (real model backing add_tags/remove_tags)."""
    __tablename__ = "blog_post_tags"
    post_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(80), index=True)


class BlogServiceExtended(BlogService):
    def __init__(self, db):
        super().__init__(db)

    def create(self, title: str, body: str, published: bool = False, tags: Optional[List[str]] = None) -> Post:
        if len(title) > 200:
            raise InvalidInputError("Title is too long")
        slug = _slugify(title)
        if self.db.query(Post).filter_by(slug=slug).first():
            raise SlugConflictError()
        post = Post(title=title, slug=slug, body=body, published=published)
        self.db.add(post)
        self.db.flush()
        return post

    def query(self, filters: Dict[str, Any], sort: Optional[List[str]] = None, page: int = 1, per_page: int = 20) -> List[Post]:
        query = select(Post)
        for key, value in filters.items():
            if key == 'published':
                query = query.where(Post.published == value)
            elif key == 'slug':
                query = query.where(Post.slug == value)
        if sort:
            for field in sort:
                query = query.order_by(getattr(Post, field))
        return self.db.scalars(query.offset((page - 1) * per_page).limit(per_page)).all()

    def update(self, post: Post, **kwargs) -> Post:
        for key, value in kwargs.items():
            if hasattr(post, key):
                setattr(post, key, value)
            else:
                raise InvalidInputError(f"Invalid field {key}")
        self.db.flush()
        return post

    def archive(self, post: Post) -> Post:
        post.published = False
        self.db.flush()
        return post

    def bulk_create(self, posts: List[Dict[str, Any]]) -> List[Post]:
        """Create several posts on this service's session (the old static
        version imported a nonexistent session helper and required a 'slug'
        key it then ignored)."""
        try:
            created_posts = []
            for post_data in posts:
                title = post_data.get("title", "")
                slug = _slugify(title)
                if not title or len(title) > 200 or len(slug) > 220:
                    raise InvalidInputError("Invalid input provided")
                if self.db.query(Post).filter_by(slug=slug).first():
                    raise SlugConflictError()
                post = Post(title=title, slug=slug,
                            body=post_data.get("body", ""),
                            published=bool(post_data.get("published", False)))
                self.db.add(post)
                created_posts.append(post)
            self.db.flush()
        except SQLAlchemyError as e:
            self.db.rollback()
            raise BulkCreateError() from e
        return created_posts

    def add_tags(self, post: Post, tags: List[str]) -> Post:
        if len(tags) > 10:
            raise InvalidTagError("Too many tags")
        existing = {t.name for t in self.get_tags(post)}
        for tag in tags:
            tag = tag.strip().lower()
            if not tag:
                raise InvalidTagError("Empty tag")
            if tag not in existing:
                self.db.add(PostTag(post_id=post.id, name=tag))
        self.db.flush()
        return post

    def remove_tags(self, post: Post, tags: List[str]) -> Post:
        if len(tags) > 10:
            raise InvalidTagError("Too many tags")
        wanted = {t.strip().lower() for t in tags}
        for row in self.get_tags(post):
            if row.name in wanted:
                self.db.delete(row)
        self.db.flush()
        return post

    def get_tags(self, post: Post) -> List[PostTag]:
        return list(self.db.scalars(select(PostTag).where(PostTag.post_id == post.id)))

    @staticmethod
    def to_dict(post: Post) -> Dict[str, Any]:
        return {
            'id': post.id,
            'title': post.title,
            'slug': post.slug,
            'body': post.body,
            'published': post.published,
            'created_at': post.created_at.isoformat()
        }

    @staticmethod
    def to_list(posts: List[Post]) -> List[Dict[str, Any]]:
        # BlogService has no to_dict; the extended class defines it.
        return [BlogServiceExtended.to_dict(post) for post in posts]

    @staticmethod
    def set_slug_generator(func: Callable[[str], str]):
        global _slugify
        _slugify = func

    def on_create(self, post: Post):
        if getattr(BlogService, 'AUDIT_LOG_ENABLED', True):
            print(f"Post {post.id} created")

    def on_update(self, post: Post):
        if getattr(BlogService, 'AUDIT_LOG_ENABLED', True):
            print(f"Post {post.id} updated")

    def on_archive(self, post: Post):
        if getattr(BlogService, 'AUDIT_LOG_ENABLED', True):
            print(f"Post {post.id} archived")

    @staticmethod
    def is_visible(post: Post, user: Any) -> bool:
        return post.published

    @property
    def SLUG_MAX_LENGTH(self) -> int:
        return 220

    @property
    def MAX_TITLE_LENGTH(self) -> int:
        return 200

    @property
    def DEFAULT_PUBLISH_STATUS(self) -> bool:
        return False

    @property
    def MAX_TAGS_PER_POST(self) -> int:
        return 10

    @property
    def BULK_CREATE_BATCH_SIZE(self) -> int:
        return 50

    @property
    def AUDIT_LOG_ENABLED(self) -> bool:
        return True

    @property
    def ARCHIVE_FIELD_NAME(self) -> str:
        return 'published'


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                svc = BlogServiceExtended(db)
                p1 = svc.create("Hello World", "First body", published=True)
                assert p1.slug == "hello-world"
                try:
                    svc.create("Hello World", "dup")
                    raise AssertionError("duplicate slug must conflict")
                except SlugConflictError:
                    pass
                try:
                    svc.create("x" * 201, "body")
                    raise AssertionError("long title must be invalid")
                except InvalidInputError:
                    pass

                svc.create("Draft Post", "hidden", published=False)
                assert [p.slug for p in svc.published()] == ["hello-world"]
                assert svc.by_slug("hello-world").id == p1.id
                assert svc.by_slug("missing") is None

                # query / update / archive
                assert len(svc.query({"published": True})) == 1
                svc.update(p1, body="Edited body")
                assert svc.by_slug("hello-world").body == "Edited body"
                try:
                    svc.update(p1, nonsense=1)
                    raise AssertionError("unknown field must be invalid")
                except InvalidInputError:
                    pass
                svc.archive(p1)
                assert svc.published() == []
                svc.update(p1, published=True)

                # bulk create on the same session
                made = svc.bulk_create([{"title": "Bulk One", "body": "a"},
                                        {"title": "Bulk Two", "body": "b", "published": True}])
                assert [p.slug for p in made] == ["bulk-one", "bulk-two"]
                try:
                    svc.bulk_create([{"title": "Bulk One"}])
                    raise AssertionError("bulk duplicate must conflict")
                except SlugConflictError:
                    pass

                # real tags
                svc.add_tags(p1, ["News", "python"])
                assert sorted(t.name for t in svc.get_tags(p1)) == ["news", "python"]
                svc.add_tags(p1, ["python"])  # idempotent
                assert len(svc.get_tags(p1)) == 2
                svc.remove_tags(p1, ["news"])
                assert [t.name for t in svc.get_tags(p1)] == ["python"]
                try:
                    svc.add_tags(p1, ["t"] * 11)
                    raise AssertionError("too many tags must fail")
                except InvalidTagError:
                    pass

                # serialization
                d = BlogServiceExtended.to_dict(p1)
                assert d["slug"] == "hello-world" and d["published"] is True
                assert BlogServiceExtended.to_list([p1])[0]["id"] == p1.id
        finally:
            engine.dispose()
    print("blog self-test passed")


if __name__ == "__main__":
    _selftest()
