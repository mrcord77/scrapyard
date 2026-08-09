"""
capacity_allocator — Distribute resource capacity proportionally to demand.

### PART-META-JSON
{
  "name": "capacity_allocator",
  "layer": "projects",
  "purpose": "Proportional capacity allocation across project resources: CapacityAllocator takes Resource(name, capacity) entries plus a demand map and computes allocation[resource] = (resource_demand / total_demand) * resource.capacity; reallocate_capacity() recomputes for new demand, and zero total demand or an empty resource list yields zero/empty allocations.",
  "status": "core",
  "dependencies": [],
  "inputs": "CapacityAllocator([Resource(name, capacity), ...], {'name': demand_float, ...}); distribute_capacity(); reallocate_capacity(new_demand).",
  "outputs": "Dict[Resource, float] allocation maps (also cached on .allocations).",
  "files_created": [],
  "security_notes": "Pure in-memory arithmetic on caller-supplied numbers; no network, file (selftest temp SQLite only), subprocess, or secret handling. Semantics to know before trusting outputs: each resource is weighted by ITS OWN demand share times ITS OWN capacity, so an allocation can exceed what the demand asked for and unmatched demand names are ignored - validate demand keys against resource names upstream. Negative demands are not rejected; sanitize inputs if they originate from users.",
  "ai_usage": "alloc = CapacityAllocator(resources, demand).distribute_capacity(); after demand shifts call reallocate_capacity(new_demand).",
  "example": "from scrapyard.projects.capacity_allocator import CapacityAllocator, Resource",
  "import_path": "scrapyard.projects.capacity_allocator"
}
### END-PART-META
"""
from dataclasses import dataclass
from typing import Dict, List
import logging
import math
import os
import sqlite3
import tempfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resource:
    name: str
    capacity: float


class CapacityAllocator:
    def __init__(self, resources: List[Resource], demand: Dict[str, float]) -> None:
        self._resources = list(resources)
        self._resource_map = {resource.name: resource for resource in resources}
        self.demand = dict(demand)
        self.allocations: Dict[Resource, float] = {}

    def _calculate_allocations(self, demand: Dict[str, float]) -> Dict[Resource, float]:
        total_demand = sum(demand.values())
        if total_demand == 0 or not self._resources:
            return {resource: 0.0 for resource in self._resources}

        allocations: Dict[Resource, float] = {}
        for resource in self._resources:
            resource_demand = demand.get(resource.name, 0.0)
            allocations[resource] = (resource_demand / total_demand) * resource.capacity
        return allocations

    def distribute_capacity(self) -> Dict[Resource, float]:
        self.allocations = self._calculate_allocations(self.demand)
        return dict(self.allocations)

    def reallocate_capacity(self, new_demand: Dict[str, float]) -> Dict[Resource, float]:
        self.demand = dict(new_demand)
        self.allocations = self._calculate_allocations(self.demand)
        return dict(self.allocations)


def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, "capacity_allocator_test.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS allocations ("
                "resource TEXT PRIMARY KEY, allocation REAL NOT NULL"
                ")"
            )
            conn.commit()

            resources = [
                Resource(name="ResourceA", capacity=100.0),
                Resource(name="ResourceB", capacity=200.0),
                Resource(name="ResourceC", capacity=300.0),
            ]

            initial_demand = {
                "ResourceA": 50.0,
                "ResourceB": 75.0,
                "ResourceC": 100.0,
            }

            allocator = CapacityAllocator(resources, initial_demand)
            allocations = allocator.distribute_capacity()
            logger.info(f"Initial allocations: {allocations}")

            assert isinstance(allocations, dict)
            assert len(allocations) == len(resources)

            initial_total_demand = sum(initial_demand.values())
            for resource in resources:
                assert isinstance(resource, Resource)
                assert resource in allocations
                expected = (initial_demand[resource.name] / initial_total_demand) * resource.capacity
                assert math.isclose(allocations[resource], expected, rel_tol=1e-9), (
                    f"Allocation for {resource.name} expected ~{expected}, got {allocations[resource]}"
                )
                conn.execute(
                    "INSERT OR REPLACE INTO allocations (resource, allocation) VALUES (?, ?)",
                    (resource.name, allocations[resource]),
                )
            conn.commit()

            cursor = conn.execute("SELECT resource, allocation FROM allocations")
            stored = {row[0]: row[1] for row in cursor.fetchall()}
            for resource in resources:
                assert math.isclose(stored[resource.name], allocations[resource], rel_tol=1e-9)

            new_demand = {
                "ResourceA": 60.0,
                "ResourceB": 80.0,
                "ResourceC": 120.0,
            }

            reallocated_allocations = allocator.reallocate_capacity(new_demand)
            logger.info(f"Reallocated allocations: {reallocated_allocations}")

            assert isinstance(reallocated_allocations, dict)
            assert len(reallocated_allocations) == len(resources)

            new_total_demand = sum(new_demand.values())
            for resource in resources:
                expected = (new_demand[resource.name] / new_total_demand) * resource.capacity
                assert math.isclose(reallocated_allocations[resource], expected, rel_tol=1e-9), (
                    f"Reallocated allocation for {resource.name} expected ~{expected}, "
                    f"got {reallocated_allocations[resource]}"
                )

            zero_demand = {resource.name: 0.0 for resource in resources}
            zero_allocations = allocator.reallocate_capacity(zero_demand)
            assert all(allocation == 0.0 for allocation in zero_allocations.values()), (
                "Zero demand should result in zero allocations"
            )

            empty_allocator = CapacityAllocator([], {})
            empty_allocations = empty_allocator.distribute_capacity()
            assert empty_allocations == {}, "No resources should produce an empty allocation map"

            logger.info("CapacityAllocator _selftest passed")
        finally:
            conn.close()


if __name__ == "__main__":
    _selftest()
