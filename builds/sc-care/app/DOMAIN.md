# Domain: Care Circle

## Entities to scaffold
- **CareRecipient**: id, name, lives_at, primary_doctor, emergency_contact
- **CareTask**: id, recipient_id, title, assigned_to, due_at, status
- **Medication**: id, recipient_id, name, dose, schedule, prescriber, status
- **DoseLog**: id, medication_id, given_at, given_by, taken, note
- **Appointment**: id, recipient_id, with_whom, at, driver, outcome_note, status
- **Update**: id, recipient_id, author, posted_at, body

## Workflows
- family shares one circle: tasks get claimed (not assigned into a void), missed tasks escalate instead of vanishing
- every dose logged against an active med; appointments have a named driver; updates keep long-distance siblings in the loop
