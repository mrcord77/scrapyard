"""
result_aggregation — Aggregate results from multiple agents to form a comprehensive output or decision. This module provides tools to collect, merge, and finalize results from distributed agent execution.

### PART-META-JSON
{
  "name": "result_aggregation",
  "layer": "agents",
  "purpose": "Aggregate results from multiple agents to form a comprehensive output or decision. This module provides tools to collect, merge, and finalize results from distributed agent execution.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "task_queue",
    "role_definitions"
  ],
  "inputs": "Public API: aggregate_results(task_id, role_weights, results); RoleDefinition(...); AgentResult(...); ResultAggregator(...).",
  "outputs": "Returns: aggregate_results -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.agents.result_aggregation`.",
  "example": "from scrapyard.agents.result_aggregation import *",
  "import_path": "scrapyard.agents.result_aggregation"
}
### END-PART-META
"""

from dataclasses import dataclass
from typing import List, Dict, Any
import logging
import threading
import tempfile
import sqlite3
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class RoleDefinition:
    role: str
    weight: float


@dataclass
class AgentResult:
    agent_id: str
    result: Any


class ResultAggregator:
    def __init__(self, task_id: str, role_weights: Dict[str, float]) -> None:
        self.task_id = task_id
        self.role_weights = role_weights
        self.aggregated_results: Dict[str, Dict[str, Any]] = {}
        self.status: Dict[str, str] = {}
        self._lock = threading.Lock()
        self.created_at = datetime.now(timezone.utc).isoformat()

    def add_result(self, agent_id: str, result: Any) -> None:
        with self._lock:
            # Allow updates to existing agent results (streaming/overwrite behavior)
            self.aggregated_results[agent_id] = {'result': result}
            self.status[agent_id] = 'received'
            logger.debug(f"Added/updated result for agent {agent_id} in task {self.task_id}")

    def finalize(self) -> Dict[str, Any]:
        with self._lock:
            weighted_results = {}
            
            # Validate and prepare results with weights
            for agent_id, data in self.aggregated_results.items():
                if 'result' not in data:
                    logger.error(f"Missing result data structure for agent {agent_id}")
                    self.status[agent_id] = 'invalid_format'
                    continue
                
                result = data['result']
                
                # Handle None/failed results gracefully
                if result is None:
                    logger.warning(f"Null result from agent {agent_id}, treating as empty contribution")
                    result = {}
                    self.status[agent_id] = 'failed'
                else:
                    self.status[agent_id] = 'aggregated'
                
                role_weight = self.role_weights.get(agent_id, 0.0)
                weighted_results[agent_id] = {
                    'agent_id': agent_id,
                    'weight': role_weight,
                    'result': result
                }

            # Sort by weight ascending so higher weights overwrite lower weights during merge
            # This ensures highest weighted results take precedence on key conflicts
            sorted_entries = sorted(
                weighted_results.items(), 
                key=lambda x: x[1]['weight']
            )
            
            # Merge results sequentially
            final_result = {}
            conflict_log = []
            
            for agent_id, entry in sorted_entries:
                if not isinstance(entry['result'], dict):
                    logger.warning(f"Result from {agent_id} is not a dict, wrapping")
                    try:
                        entry_result = {'value': entry['result']} if entry['result'] is not None else {}
                    except Exception:
                        entry_result = {}
                else:
                    entry_result = entry['result'].copy()
                
                # Track conflicts for audit metadata
                for key in entry_result:
                    if key in final_result and final_result[key] != entry_result[key]:
                        conflict_log.append({
                            'key': key,
                            'previous_value': final_result[key],
                            'new_value': entry_result[key],
                            'overwritten_by': agent_id,
                            'weight': entry['weight']
                        })
                
                final_result.update(entry_result)

            metadata = {
                'task_id': self.task_id,
                'created_at': self.created_at,
                'finalized_at': datetime.now(timezone.utc).isoformat(),
                'total_agents': len(self.aggregated_results),
                'successful_agents': sum(1 for s in self.status.values() if s == 'aggregated'),
                'failed_agents': sum(1 for s in self.status.values() if s == 'failed'),
                'conflicts_resolved': len(conflict_log),
                'aggregation_strategy': 'weighted_merge'
            }

            return {
                'task_id': self.task_id,
                'final_result': final_result,
                'status': self.status.copy(),
                'metadata': metadata,
                'role_weights_applied': self.role_weights.copy()
            }

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'task_id': self.task_id,
                'agent_status': self.status.copy(),
                'results_collected': len(self.aggregated_results),
                'pending_finalization': True
            }


def aggregate_results(task_id: str, role_weights: Dict[str, float], results: List[Dict]) -> Dict[str, Any]:
    """
    Convenience function to aggregate a batch of results in a single call.
    Handles invalid entries gracefully by logging and skipping them.
    """
    if not isinstance(results, list):
        logger.error("Results parameter must be a list")
        results = []
    
    aggregator = ResultAggregator(task_id, role_weights)
    
    for idx, result in enumerate(results):
        if not isinstance(result, dict):
            logger.error(f"Invalid result format at index {idx}: {result}")
            continue
        if 'agent_id' not in result:
            logger.error(f"Missing agent_id in result at index {idx}")
            continue
        if 'result' not in result:
            logger.error(f"Missing result key for agent {result.get('agent_id', 'unknown')}")
            continue
        
        aggregator.add_result(result['agent_id'], result['result'])
    
    return aggregator.finalize()


def _selftest():
    """Self-test function with SQLite and tempfile as required."""
    import threading
    import time
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_aggregation.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS test_log (
                id INTEGER PRIMARY KEY,
                test_name TEXT,
                timestamp TEXT,
                passed BOOLEAN
            )
        """)
        
        try:
            # Test 1: Basic aggregation with duplicate agent updates and weight precedence
            role_weights = {'role1': 0.6, 'role2': 0.4}
            results = [
                {'agent_id': 'role1', 'result': {'value': 10}},
                {'agent_id': 'role2', 'result': {'value': 20}},
                {'agent_id': 'role1', 'result': {'value': 30}}
            ]
            
            final_result = aggregate_results('task1', role_weights, results)
            
            # Core assertions
            assert isinstance(final_result, dict), "Final result should be a dictionary"
            assert 'task_id' in final_result and final_result['task_id'] == 'task1', "Task ID mismatch"
            assert 'final_result' in final_result, "Missing final result key"
            assert 'status' in final_result, "Missing status key"
            assert 'metadata' in final_result, "Missing metadata key"
            
            # Weighted aggregation: role1 (weight 0.6 > 0.4) should win with value 30
            # Note: Second role1 result (30) overwrites first (10), and role1 processes after role2 due to sort order
            expected_result = {'value': 30}
            assert final_result['final_result'] == expected_result, f"Expected {expected_result}, got {final_result['final_result']}"
            
            # Verify status tracking
            assert 'role1' in final_result['status'], "Missing role1 status"
            assert 'role2' in final_result['status'], "Missing role2 status"
            assert final_result['status']['role1'] == 'aggregated', "Role1 should be marked aggregated"
            
            # Test 2: Thread safety verification
            agg = ResultAggregator('task2', {'agent_a': 0.3, 'agent_b': 0.7})
            errors = []
            
            def concurrent_adds(agent_id, values):
                try:
                    for v in values:
                        agg.add_result(agent_id, {'data': v, 'agent': agent_id})
                        time.sleep(0.001)
                except Exception as e:
                    errors.append(str(e))
            
            threads = [
                threading.Thread(target=concurrent_adds, args=('agent_a', list(range(5)))),
                threading.Thread(target=concurrent_adds, args=('agent_b', list(range(10, 15)))),
                threading.Thread(target=concurrent_adds, args=('agent_a', list(range(100, 105))))  # Overwrites
            ]
            
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            
            assert not errors, f"Thread safety errors occurred: {errors}"
            
            result2 = agg.finalize()
            assert result2['task_id'] == 'task2'
            assert result2['metadata']['total_agents'] == 2  # Only 2 unique agents despite concurrent updates
            
            # Test 3: Invalid and missing results handling
            invalid_results = [
                {'agent_id': 'valid_role', 'result': {'key': 'val'}},
                {'invalid': 'no agent_id'},  # Skip
                {'agent_id': 'missing_result'},  # Skip
                {'agent_id': 'null_agent', 'result': None},  # Handle as empty
                {'agent_id': 'valid_role', 'result': {'key': 'updated'}}  # Update existing
            ]
            
            result3 = aggregate_results('task3', {'valid_role': 1.0, 'null_agent': 0.1}, invalid_results)
            assert 'valid_role' in result3['status']
            assert result3['final_result'] == {'key': 'updated'}  # Last write wins
            
            # Log success
            cursor.execute(
                "INSERT INTO test_log (test_name, timestamp, passed) VALUES (?, datetime('now'), ?)",
                ('result_aggregation', True)
            )
            conn.commit()
            print("Self-test passed successfully.")
            
        except Exception as e:
            cursor.execute(
                "INSERT INTO test_log (test_name, timestamp, passed) VALUES (?, datetime('now'), ?)",
                ('result_aggregation', False)
            )
            conn.commit()
            raise
        finally:
            conn.close()


if __name__ == "__main__":
    _selftest()
