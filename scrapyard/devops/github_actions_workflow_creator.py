"""
github_actions_workflow_creator — Create GitHub Actions workflows for CI/CD pipelines, enabling automated testing, building, and deployment.

### PART-META-JSON
{
  "name": "github_actions_workflow_creator",
  "layer": "devops",
  "purpose": "Create GitHub Actions workflows for CI/CD pipelines, enabling automated testing, building, and deployment.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_github_action(name, steps); WorkflowStep(...).",
  "outputs": "Returns: create_github_action -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.devops.github_actions_workflow_creator`.",
  "example": "from scrapyard.devops.github_actions_workflow_creator import *",
  "import_path": "scrapyard.devops.github_actions_workflow_creator"
}
### END-PART-META
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any

@dataclass
class WorkflowStep:
    name: str
    uses: str
    env: Optional[Dict[str, str]] = None
    if_: Optional[str] = None

def create_github_action(name: str, steps: List[WorkflowStep]) -> Dict[str, Any]:
    """
    Generate a GitHub Actions workflow from the provided steps.

    :param name: The name of the workflow.
    :param steps: A list of WorkflowStep objects defining the steps in the workflow.
    :return: A dictionary representing the GitHub Actions workflow structure.
    """
    workflow = {
        "name": name,
        "on": {"push": {}, "pull_request": {}},
        "jobs": {}
    }

    for step in steps:
        job_name = f"job_{hash(step.name)}"
        if job_name not in workflow["jobs"]:
            workflow["jobs"][job_name] = {
                "runs_on": "ubuntu-latest",
                "env": {},
                "steps": []
            }
        
        env_vars = step.env or {}
        for key, value in env_vars.items():
            workflow["jobs"][job_name]["env"][key] = value
        
        if step.if_:
            workflow["jobs"][job_name]["if"] = step.if_
        
        workflow["jobs"][job_name]["steps"].append({
            "name": step.name,
            "uses": step.uses
        })

    return workflow

def _selftest():
    """
    Self-test the module to ensure it meets the specified criteria.
    """
    steps = [
        WorkflowStep(name="lint", uses="actions/lint@v1"),
        WorkflowStep(name="test", uses="actions/run-tests@v2", env={"TEST_ENV": "production"}),
        WorkflowStep(name="deploy", uses="actions/deploy-app@v3", if_="github.ref == 'refs/heads/main'")
    ]
    
    workflow = create_github_action("My CI Pipeline", steps)
    
    assert isinstance(workflow, dict), "create_github_action() must return a dictionary"
    assert "name" in workflow, "Workflow must have a name"
    assert "on" in workflow, "Workflow must have an 'on' section"
    assert "jobs" in workflow, "Workflow must have a 'jobs' section"
    
    for job_name, job in workflow["jobs"].items():
        assert "runs_on" in job, f"Job {job_name} must specify runs_on"
        assert "steps" in job, f"Job {job_name} must specify steps"
        for step in job["steps"]:
            assert "name" in step and isinstance(step["name"], str), f"Step name must be a string"
            assert "uses" in step and isinstance(step["uses"], str), f"Step uses must be a string"
    
    print("Self-test passed successfully.")

if __name__ == "__main__":
    _selftest()
