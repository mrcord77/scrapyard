"""
data_loader_factory — Provides a factory for creating data loaders with various transformations and augmentations, enabling flexible and reusable ML training pipelines.

### PART-META-JSON
{
  "name": "data_loader_factory",
  "layer": "ml",
  "purpose": "Provides a factory for creating data loaders with various transformations and augmentations, enabling flexible and reusable ML training pipelines.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: register_augmentation(name, factory); DataLoaderFactory(...); TransformBuilder(...).",
  "outputs": "Returns: register_augmentation -> None.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.data_loader_factory`.",
  "example": "from scrapyard.ml.data_loader_factory import *",
  "import_path": "scrapyard.ml.data_loader_factory"
}
### END-PART-META
"""

from typing import List, Dict, Any, Callable
import logging

logger = logging.getLogger(__name__)

class DataLoaderFactory:
    def __init__(self, dataset: Any, config: Dict) -> None:
        self.dataset = dataset
        self.config = config

    def build_loader(self, batch_size: int, shuffle: bool) -> Any:
        transform_builder = TransformBuilder()
        for key, value in self.config.get('transforms', {}).items():
            transform_builder.add_augmentation(key, value)
        
        transforms = transform_builder.build()
        if not isinstance(transforms, Callable):
            raise ValueError("Transforms must be callable")
        
        # Dummy DataLoader implementation
        class DummyDataLoader:
            def __init__(self, dataset: Any, batch_size: int, shuffle: bool, transforms: Callable):
                self.dataset = dataset
                self.batch_size = batch_size
                self.shuffle = shuffle
                self.transforms = transforms
            
            def __iter__(self):
                for item in self.dataset:
                    yield self.transforms(item)
        
        return DummyDataLoader(self.dataset, batch_size, shuffle, transforms)

    def apply_transforms(self, transforms: List[Callable]) -> Any:
        class TransformApplier:
            def __init__(self, dataset: Any, transforms: List[Callable]):
                self.dataset = dataset
                self.transforms = transforms
            
            def __iter__(self):
                for item in self.dataset:
                    for transform in self.transforms:
                        item = transform(item)
                    yield item
        
        return TransformApplier(self.dataset, transforms)

# Registry of REAL named augmentations: name -> factory(params) -> transform.
# Extend with register_augmentation(); unknown names fail loudly instead of
# silently degrading to identity (the old behavior).
_AUGMENTATIONS: Dict[str, Callable[[Dict], Callable[[Any], Any]]] = {}


def register_augmentation(name: str,
                          factory: Callable[[Dict], Callable[[Any], Any]]) -> None:
    """Register a named augmentation factory: factory(params) returns the
    per-item transform callable."""
    if not callable(factory):
        raise TypeError("factory must be callable")
    _AUGMENTATIONS[name] = factory


def _builtin_identity(params: Dict) -> Callable[[Any], Any]:
    return lambda item: item


def _builtin_uppercase(params: Dict) -> Callable[[Any], Any]:
    return lambda item: item.upper() if isinstance(item, str) else item


def _builtin_add_suffix(params: Dict) -> Callable[[Any], Any]:
    suffix = params.get("suffix", "")
    return lambda item: f"{item}{suffix}" if isinstance(item, str) else item


def _builtin_scale(params: Dict) -> Callable[[Any], Any]:
    factor = params.get("factor", 1.0)

    def scale(item: Any) -> Any:
        if isinstance(item, (int, float)):
            return item * factor
        if isinstance(item, (list, tuple)):
            return type(item)(x * factor for x in item)
        return item
    return scale


register_augmentation("identity", _builtin_identity)
register_augmentation("uppercase", _builtin_uppercase)
register_augmentation("add_suffix", _builtin_add_suffix)
register_augmentation("scale", _builtin_scale)


class TransformBuilder:
    def __init__(self):
        self.transforms: List[Callable] = []

    def add_augmentation(self, name: str, params: Dict) -> 'TransformBuilder':
        """Resolve a registered augmentation by name and append its transform."""
        factory = _AUGMENTATIONS.get(name)
        if factory is None:
            raise KeyError(f"Unknown augmentation '{name}'. Registered: "
                           f"{sorted(_AUGMENTATIONS)}")
        self.transforms.append(factory(params or {}))
        return self

    def build(self) -> Callable:
        if not self.transforms:
            raise ValueError("No transforms added")
        
        def composed_transforms(item: Any):
            for transform in self.transforms:
                item = transform(item)
            return item
        return composed_transforms
    
    def reset(self) -> None:
        self.transforms.clear()

def _selftest():
    class SmallDataset:
        def __iter__(self):
            yield 'item1'
            yield 'item2'

    config = {
        "transforms": {
            "uppercase": {},
            "add_suffix": {"suffix": "!"},
        }
    }

    factory = DataLoaderFactory(SmallDataset(), config)

    # build_loader applies the REAL named transforms in order
    loader = factory.build_loader(batch_size=2, shuffle=False)
    items = list(loader)
    assert items == ["ITEM1!", "ITEM2!"], items

    # apply_transforms applies caller transforms in order
    transforms = [lambda x: x + " transformed", lambda x: x.upper()]
    applier = factory.apply_transforms(transforms)
    items = list(applier)
    assert items == ["ITEM1 TRANSFORMED", "ITEM2 TRANSFORMED"], items

    # TransformBuilder composes real transforms
    builder = TransformBuilder()
    builder.add_augmentation("scale", {"factor": 2.0})
    builder.add_augmentation("scale", {"factor": 5.0})
    composed = builder.build()
    assert composed(3.0) == 30.0

    # reset clears the pipeline; empty build fails loudly
    builder.reset()
    try:
        builder.build()
        raise AssertionError("expected ValueError for empty builder")
    except ValueError:
        pass

    # unknown augmentation names fail loudly (regression: silent identity)
    try:
        TransformBuilder().add_augmentation("does_not_exist", {})
        raise AssertionError("expected KeyError for unknown augmentation")
    except KeyError:
        pass

    # custom registration
    register_augmentation("reverse", lambda params: (
        lambda item: item[::-1] if isinstance(item, str) else item))
    b = TransformBuilder().add_augmentation("reverse", {})
    assert b.build()("abc") == "cba"
    _AUGMENTATIONS.pop("reverse", None)

    logger.info("Self-test passed successfully")
    print("data_loader_factory selftest passed")

if __name__ == "__main__":
    _selftest()
