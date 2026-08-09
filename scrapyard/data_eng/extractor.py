"""
extractor — The `extractor` module provides reusable functions for pulling data from diverse sources (files, REST APIs, databases), enabling flexible and scalable data pipeline architectures.

### PART-META-JSON
{
  "name": "extractor",
  "layer": "data_eng",
  "purpose": "Pulls data from diverse sources into pipeline-friendly shapes: extract_from_file loads CSV/JSON into pandas DataFrames, fetch_from_api GETs JSON from REST endpoints via urllib (with injectable opener for tests), and read_from_db selects all rows of a SQLAlchemy model.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "pandas",
    "sqlalchemy (read_from_db only)"
  ],
  "inputs": "File paths + format names; API URLs + query params (and an optional opener callable); a SQLAlchemy session + mapped model class.",
  "outputs": "pandas DataFrames, parsed JSON dicts, lists of ORM model instances.",
  "files_created": [],
  "security_notes": "fetch_from_api performs real network requests to caller-supplied URLs with urllib and no scheme allowlist - passing untrusted URLs enables SSRF (including file:// via urllib), so validate/allowlist URLs before calling and never interpolate user input into them. pd.read_csv/read_json parse untrusted files in native code; keep pandas patched. read_from_db executes a full-table SELECT - it does not filter, so apply row-level authorization upstream. No secrets are handled or logged by this module.",
  "ai_usage": "extract_from_file(path, 'csv') for files; fetch_from_api(url, params) for APIs; read_from_db(session, Model) for DB reads.",
  "example": "from scrapyard.data_eng.extractor import extract_from_file",
  "import_path": "scrapyard.data_eng.extractor"
}
### END-PART-META
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import urllib.request
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def extract_from_file(file_path: str, format: str = "csv") -> "pd.DataFrame":
    """Extract data from a file into a pandas DataFrame.

    Args:
        file_path: Path to the file.
        format: File format ("csv" or "json").

    Returns:
        DataFrame containing the file data.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the format is unsupported.
    """
    import pandas as pd

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    fmt = format.lower()
    if fmt == "csv":
        return pd.read_csv(file_path)
    elif fmt == "json":
        return pd.read_json(file_path)
    else:
        raise ValueError(f"Unsupported format: {format}")


def fetch_from_api(url: str, params: Optional[Dict] = None,
                   opener: Optional[Callable[..., Any]] = None,
                   timeout: float = 30.0) -> Dict:
    """Fetch data from a RESTful API endpoint.

    Args:
        url: The API endpoint URL.
        params: Optional query parameters.
        opener: Optional replacement for urllib.request.urlopen (used by
            tests to stay offline); must return a context manager whose
            value has a .read() method.
        timeout: Socket timeout in seconds for the default opener.

    Returns:
        Parsed JSON response as a dictionary.
    """
    if params:
        query = urllib.parse.urlencode(params)
        url = f"{url}?{query}"

    req = urllib.request.Request(url, headers={"Accept": "application/json"})

    if opener is None:
        def opener(r):
            return urllib.request.urlopen(r, timeout=timeout)

    with opener(req) as response:
        data = response.read()
        return json.loads(data)


def read_from_db(session: "Session", model: "type") -> "List[Any]":
    """Read all records of a model from the database.

    Args:
        session: SQLAlchemy session.
        model: SQLAlchemy mapped class (model).

    Returns:
        List of model instances.
    """
    from sqlalchemy import select

    stmt = select(model)
    result = session.execute(stmt)
    return list(result.scalars().all())


def _selftest():
    """Offline self-test validating core functionality."""

    errors: List[str] = []

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Test extract_from_file (CSV)
        try:
            csv_path = os.path.join(tmpdir, "data.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("id,name,value\n1,Alice,100\n2,Bob,200\n")

            df = extract_from_file(csv_path, "csv")
            import pandas as pd

            assert isinstance(df, pd.DataFrame), "CSV did not return DataFrame"
            assert df.shape == (2, 3), f"CSV shape mismatch: {df.shape}"
            assert list(df.columns) == ["id", "name", "value"], "CSV columns mismatch"
        except Exception as e:
            errors.append(f"extract_from_file CSV: {e}")

        # Test extract_from_file (JSON)
        try:
            json_path = os.path.join(tmpdir, "data.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}], f)

            df = extract_from_file(json_path, "json")
            assert isinstance(df, pd.DataFrame), "JSON did not return DataFrame"
            assert len(df) == 2, "JSON row count mismatch"
        except Exception as e:
            errors.append(f"extract_from_file JSON: {e}")

        # Test extract_from_file exceptions
        try:
            extract_from_file(os.path.join(tmpdir, "nonexistent.csv"))
            errors.append("extract_from_file should raise FileNotFoundError")
        except FileNotFoundError:
            pass
        except Exception as e:
            errors.append(f"extract_from_file FileNotFoundError test: {e}")

        try:
            extract_from_file(csv_path, format="xml")
            errors.append("extract_from_file should raise ValueError for bad format")
        except ValueError:
            pass
        except Exception as e:
            errors.append(f"extract_from_file ValueError test: {e}")

        # Test fetch_from_api via injected opener (offline, no unittest.mock)
        try:
            canned = {"status": "success", "items": [{"id": 1}, {"id": 2}]}
            seen_urls: List[str] = []

            class _FakeResponse:
                def read(self):
                    return json.dumps(canned).encode("utf-8")

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            def fake_opener(req):
                seen_urls.append(req.full_url)
                return _FakeResponse()

            result = fetch_from_api("http://test.api/data", {"key": "val"},
                                    opener=fake_opener)
            assert result == canned, f"API result mismatch: {result}"
            assert seen_urls == ["http://test.api/data?key=val"], seen_urls
        except Exception as e:
            errors.append(f"fetch_from_api offline: {e}")

        # Test read_from_db with temporary SQLite
        db_path = os.path.join(tmpdir, "test.db")
        engine = None
        try:
            # Lazy import SQLAlchemy inside test
            from sqlalchemy import Column, Integer, String, create_engine
            from sqlalchemy.orm import declarative_base, sessionmaker

            Base = declarative_base()

            class TestItem(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True)
                name = Column(String(50))

            engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(engine)

            Session = sessionmaker(bind=engine)
            session = Session()
            session.add_all([TestItem(id=1, name="foo"), TestItem(id=2, name="bar")])
            session.commit()

            # Test the function
            results = read_from_db(session, TestItem)
            assert len(results) == 2, f"DB read count mismatch: {len(results)}"
            names = {r.name for r in results}
            assert names == {"foo", "bar"}, f"DB data mismatch: {names}"

            session.close()
        except Exception as e:
            errors.append(f"read_from_db: {e}")
        finally:
            if engine:
                engine.dispose()
            # Ensure file handle released
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except Exception:
                    pass

    if errors:
        raise AssertionError(f"_selftest failed:\n" + "\n".join(errors))

    logger.info("_selftest passed")
    print("extractor selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
