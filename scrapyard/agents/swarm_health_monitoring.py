"""
swarm_health_monitoring — Monitor the health and status of a swarm of agents to ensure system reliability. It provides tools to track agent status, detect failures, and trigger alerts based on predefined thresholds and quorum 

### PART-META-JSON
{
  "name": "swarm_health_monitoring",
  "layer": "agents",
  "purpose": "Monitor the health and status of a swarm of agents to ensure system reliability. It provides tools to track agent status, detect failures, and trigger alerts based on predefined thresholds and quorum ",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: HealthMonitor(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.agents.swarm_health_monitoring`.",
  "example": "from scrapyard.agents.swarm_health_monitoring import *",
  "import_path": "scrapyard.agents.swarm_health_monitoring"
}
### END-PART-META
"""

from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class HealthMonitor:
    def __init__(self, quorum_threshold: int, role_definitions: dict):
        self.quorum_threshold = quorum_threshold
        self.role_definitions = role_definitions
        self.agent_status = {}
        self.failure_alerts = []

    def check_health(self, agent_id: str) -> Dict[str, Any]:
        if agent_id not in self.agent_status:
            return {"status": "unknown", "metrics": {}}
        
        status = self.agent_status[agent_id]
        metrics = status.get("metrics", {})
        return {
            "status": status["health"],
            "metrics": metrics
        }

    def notify_failure(self, agent_id: str, reason: str) -> None:
        if agent_id not in self.agent_status:
            logger.warning(f"Agent {agent_id} not found before notifying failure.")
            return
        
        status = self.agent_status[agent_id]
        status["health"] = "failed"
        status["failure_reason"] = reason
        self.failure_alerts.append((agent_id, reason))
        logger.error(f"Agent {agent_id} failed: {reason}")

    def register_agent(self, agent_id: str, role: str) -> None:
        if agent_id in self.agent_status:
            raise ValueError(f"Agent {agent_id} already registered.")
        
        self.agent_status[agent_id] = {
            "role": role,
            "health": "unknown",
            "metrics": {},
            "failure_reason": ""
        }

    def remove_agent(self, agent_id: str) -> None:
        if agent_id not in self.agent_status:
            raise ValueError(f"Agent {agent_id} not found.")
        
        del self.agent_status[agent_id]

    def apply_role_rules(self, agent_id: str) -> None:
        role = self.agent_status.get(agent_id, {}).get("role")
        if role and self.role_definitions.get(role):
            rules = self.role_definitions[role]
            for metric, threshold in rules.items():
                current_value = self.agent_status[agent_id]["metrics"].get(metric)
                if current_value is not None and current_value < threshold:
                    self.notify_failure(agent_id, f"Metric {metric} below threshold {threshold}")

    def quorum_based_failure_detection(self) -> bool:
        active_agents = sum(1 for status in self.agent_status.values() if status["health"] == "active")
        return active_agents >= self.quorum_threshold

def _selftest():
    # Setup
    monitor = HealthMonitor(quorum_threshold=3, role_definitions={"worker": {"cpu_utilization": 0.8}})

    # Register agents
    monitor.register_agent("agent1", "worker")
    monitor.register_agent("agent2", "worker")
    monitor.register_agent("agent3", "worker")

    # Check initial status
    assert monitor.check_health("agent1") == {"status": "unknown", "metrics": {}}

    # Simulate agent health checks
    for agent_id in ["agent1", "agent2", "agent3"]:
        monitor.agent_status[agent_id]["health"] = "active"
        monitor.agent_status[agent_id]["metrics"] = {"cpu_utilization": 0.75}

    # Apply role rules and check failures
    monitor.apply_role_rules("agent1")
    assert len(monitor.failure_alerts) == 1

    # Remove an agent and recheck quorum
    monitor.remove_agent("agent3")
    assert not monitor.quorum_based_failure_detection()

if __name__ == "__main__":
    _selftest()
