"""
metadata — Single source of model metadata for migrations.

Importing this module (via import_all_models) registers every table-defining part
on the shared Base.metadata, so Alembic autogenerate sees the complete schema for
whatever parts an app composes. Imports are guarded: a part whose optional deps are
absent is skipped rather than breaking migration generation.

### PART-META-JSON
{
  "name": "metadata",
  "layer": "database",
  "purpose": "Single source of model metadata for migrations: import_all_models() imports the MODEL_MODULES list (or a caller-chosen subset) so their tables register on the shared Base.metadata, and target_metadata() hands that metadata to Alembic autogenerate. Also ships a MetadataManager registry with policy tags and JSON export/import.",
  "status": "core",
  "dependencies": [
    "sqlalchemy",
    "fastapi"
  ],
  "inputs": "import_all_models(only=[...]) / target_metadata(only=[...]); MetadataManager().register_model('scrapyard.layer.part').",
  "outputs": "Base.metadata populated with the composed parts' tables; ModelInfo listings from get_registered_models().",
  "files_created": [],
  "security_notes": "register_model() and import_all_models() import modules by dotted path via importlib - importing executes module top-level code, so ONLY pass trusted scrapyard part paths, never user-supplied strings. Failed imports in import_all_models are swallowed by design (optional parts), which also means a typo silently drops a table from migrations - check the returned loaded list. Importing this module alone has no registry side effects; callers choose which models to register.",
  "ai_usage": "In alembic env.py: from scrapyard.database.metadata import target_metadata; target_metadata(only=my_app_modules).",
  "example": "from scrapyard.database.metadata import import_all_models, target_metadata",
  "import_path": "scrapyard.database.metadata"
}
### END-PART-META
"""
from typing import List, Dict, Type, Any, Optional
import json
from sqlalchemy.orm import Session
from sqlalchemy import MetaData
from scrapyard.database.base_model import Base
from fastapi import HTTPException
import importlib

class ModelConfig:
    def __init__(self, table_name: str = None):
        self.table_name = table_name

class ModelInfo:
    def __init__(self, name: str, module: str, table_name: str, schema_version: str):
        self.name = name
        self.module = module
        self.table_name = table_name
        self.schema_version = schema_version

class ModelPolicy:
    def __init__(self, policy_type: str, config: Dict[str, Any] = None):
        self.policy_type = policy_type
        self.config = config or {}

class ModelRegistrationError(Exception):
    pass

class ModelAlreadyRegisteredError(Exception):
    pass

class ModelPolicyNotFoundError(Exception):
    pass

class ModelVersionMismatchError(Exception):
    pass

class ModelUnregistrationError(Exception):
    pass

class InvalidModelConfigError(Exception):
    pass

STATUS = "core"

class MetadataManager:
    def __init__(self):
        self.registered_models: Dict[str, Type] = {}
        self.model_policies: Dict[str, ModelPolicy] = {}
        self.events: List[Dict[str, str]] = []

    def register_model(self, module: str, config: ModelConfig = None) -> None:
        try:
            model_module = importlib.import_module(module)
            for name, cls in model_module.__dict__.items():
                # Pick a CONCRETE mapped model: skip Base itself and abstract bases
                # (e.g. an imported IntPKModel). A mapped class has a real __table__;
                # abstract declarative bases do not, so __table__ is the reliable signal.
                if (isinstance(cls, type) and issubclass(cls, Base) and cls is not Base
                        and "__table__" in cls.__dict__):
                    self.registered_models[module] = cls
                    self.on_model_registered(module, cls)
                    break
            else:
                raise ModelRegistrationError(f"No SQLAlchemy model found in module {module}")
        except ModuleNotFoundError as e:
            raise ModelRegistrationError(f"Failed to import module {module}: {e}")

    def unregister_model(self, module: str) -> None:
        if module not in self.registered_models:
            raise ModelUnregistrationError(f"Model module {module} is not registered")
        del self.registered_models[module]
        self.model_policies.pop(module, None)
        self.on_model_unregistered(module)

    def get_registered_models(self) -> List[ModelInfo]:
        return [ModelInfo(name=model.__name__, module=module, table_name=model.__tablename__, schema_version="1.0") for module, model in self.registered_models.items()]

    def apply_model_policy(self, policy: str, module: str) -> None:
        if module not in self.registered_models:
            raise ModelUnregistrationError(f"Model module {module} is not registered")
        if policy not in ["audit", "soft_delete"]:
            raise ModelPolicyNotFoundError(f"Unsupported model policy type {policy}")
        self.model_policies[module] = ModelPolicy(policy_type=policy)

    def get_model_policy(self, module: str) -> ModelPolicy:
        return self.model_policies.get(module, None)

    def on_model_registered(self, module: str, model: Type) -> None:
        self.events.append({"event": "registered", "module": module,
                            "model": model.__name__})

    def on_model_unregistered(self, module: str) -> None:
        self.events.append({"event": "unregistered", "module": module})

    @staticmethod
    def bulk_register_models(modules: List[str], config: Dict[str, ModelConfig]) -> None:
        manager = MetadataManager()
        for module in modules:
            if module in config and not isinstance(config[module], ModelConfig):
                raise InvalidModelConfigError(f"Invalid configuration for model {module}")
            manager.register_model(module, config.get(module))

    def export_registered_models(self, format: str = "json") -> str:
        if format != "json":
            raise ValueError("only json metadata export is supported")
        return json.dumps([
            {"module": info.module, "name": info.name,
             "table_name": info.table_name, "schema_version": info.schema_version}
            for info in self.get_registered_models()
        ], sort_keys=True)

    def import_registered_models(self, data: str, format: str = "json") -> None:
        if format != "json":
            raise ValueError("only json metadata import is supported")
        payload = json.loads(data)
        if not isinstance(payload, list):
            raise InvalidModelConfigError("model metadata must be a list")
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("module"), str):
                raise InvalidModelConfigError("each model entry needs a module")
            self.register_model(item["module"])

    @staticmethod
    def check_model_compatibility(model: Type, version: str) -> bool:
        return True

# Empty by default: a generated application may contain only a subset of the
# catalog, so importing this module must not demand identity or admin modules
# that were not assembled. Callers explicitly register/import their model set.
metadata_manager = MetadataManager()


# --- grafted from original part (API stability) ---
MODEL_MODULES = [
    "scrapyard.identity.users",
    "scrapyard.identity.session_manager",
    "scrapyard.identity.password_reset",
    "scrapyard.identity.email_verification",
    "scrapyard.admin.audit_logs",
    "scrapyard.admin.moderation_tools",
    "scrapyard.ai.document_store",
    "scrapyard.analytics.event_tracking",
    "scrapyard.authorization.roles",
    "scrapyard.billing.invoices",
    "scrapyard.billing.subscriptions",
    "scrapyard.billing.stripe_webhooks",
    "scrapyard.billing.usage_metering",
    "scrapyard.communication.notification_center",
    "scrapyard.compliance.consent_logs",
    "scrapyard.content.blog",
    "scrapyard.content.cms",
    "scrapyard.content.media_library",
    "scrapyard.jobs.db_queue",
    "scrapyard.marketplace.listings",
    "scrapyard.search.saved_searches",
]

def import_all_models(only: list[str] | None = None) -> list[str]:
    """Import model modules so their tables register on Base.metadata.
    `only` restricts to a subset (used by a generated app that ships a subset).
    Returns the modules successfully imported."""
    import importlib
    mods = only if only is not None else MODEL_MODULES
    loaded = []
    for m in mods:
        try:
            importlib.import_module(m)
            loaded.append(m)
        except Exception:
            # optional/absent part — skip; its tables simply won't be in metadata
            pass
    return loaded

def target_metadata(only: list[str] | None = None):
    """Base.metadata with all (or a subset of) model tables registered."""
    import_all_models(only)
    return Base.metadata


def _selftest() -> None:
    mgr = MetadataManager()
    mgr.register_model("scrapyard.database.migrations")   # real part defining a Base model
    infos = mgr.get_registered_models()
    assert any(i.table_name == "schema_migrations" for i in infos)   # actual __tablename__ discovered

    mgr.apply_model_policy("audit", "scrapyard.database.migrations")
    assert mgr.get_model_policy("scrapyard.database.migrations").policy_type == "audit"
    exported = mgr.export_registered_models()
    clone = MetadataManager(); clone.import_registered_models(exported)
    assert clone.get_registered_models()[0].table_name == "schema_migrations"
    assert mgr.events[0]["event"] == "registered"

    try:                                                  # negative: unknown policy rejected
        mgr.apply_model_policy("bogus", "scrapyard.database.migrations")
        raise AssertionError("accepted an unknown policy")
    except ModelPolicyNotFoundError:
        pass
    try:                                                  # negative: policy on unregistered module
        mgr.apply_model_policy("audit", "scrapyard.database.__not_registered__")
        raise AssertionError("applied policy to an unregistered module")
    except ModelUnregistrationError:
        pass
    try:                                                  # negative: importing a missing module errors
        mgr.register_model("scrapyard.database.__does_not_exist__")
        raise AssertionError("registered a nonexistent module")
    except ModelRegistrationError:
        pass

    mgr.unregister_model("scrapyard.database.migrations")
    assert mgr.get_registered_models() == []

    loaded = import_all_models(only=["scrapyard.database.migrations"])
    assert loaded == ["scrapyard.database.migrations"]
    assert "schema_migrations" in Base.metadata.tables    # subset really registered on Base
    print("metadata selftest: PASS")


if __name__ == "__main__":
    _selftest()

