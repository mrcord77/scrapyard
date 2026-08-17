# Domain: The Binder

## Entities to scaffold
- **Child**: id, user_id, first_name, grade, school, plan_type, diagnosis, notes, promised_minutes_week
- **Meeting**: id, user_id, child_id, kind, held_at, attendees, notes, status
- **Correspondence**: id, user_id, child_id, direction, with_whom, channel, sent_at, subject, body
- **ServiceEntry**: id, user_id, child_id, service, minutes, delivered_at, delivered
- **ActionItem**: id, user_id, child_id, owner, description, due_at, status

## Workflows
- request meeting (paper trail starts) -> scheduled -> held -> minutes received or disputed -> state complaint if stonewalled
- log every promised service delivery vs the plan's promised minutes - the gap IS the case
- every email/call with the school captured as correspondence on a tamper-evident chain
