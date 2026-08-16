# Domain: Personal Task Tracker

## Entities to scaffold
- **Project**: id, user_id, name, status
- **Task**: id, user_id, project_id, title, notes, priority, due_at, status
- **Label**: id, name

## Workflows
- create project -> add tasks -> todo -> doing -> done; blocked tasks resume to doing; cancelled tasks can be reopened
