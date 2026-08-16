# Domain: Construction project management

## Terminology
- **RFI** — request for information
- **change order** — scope/price change
- **punch list** — final fixes
- **submittal** — material approval doc

## Entities to scaffold
- **Project**: id, name, client, status, budget_cents
- **Task**: id, project_id, title, assignee_id, status, due
- **ChangeOrder**: id, project_id, amount_cents, status, reason
- **Document**: id, project_id, kind, media_id, uploaded_at

## Workflows
- create project -> schedule tasks
- RFI + submittal routing
- change order approval
- punch list close-out

## Permissions
- project.manage
- task.assign
- changeorder.approve

## Reports
- budget vs actual
- task completion
- open RFIs/change orders
