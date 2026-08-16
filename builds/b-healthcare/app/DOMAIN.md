# Domain: Health / clinical (NON-clinical-decision; admin & scheduling focus)

> Compliance-heavy (HIPAA-style). Treat all patient fields as PHI: encrypt at rest, audit every read. Not for clinical decision-making.

## Terminology
- **patient** — care recipient
- **provider** — clinician
- **encounter** — a visit
- **PHI** — protected health information

## Entities to scaffold
- **Patient**: id, user_id, dob, mrn  _(PHI — encrypt + audit access)_
- **Provider**: id, user_id, npi, specialty
- **Appointment**: id, patient_id, provider_id, starts_at, status
- **Encounter**: id, appointment_id, notes_ref, created_at

## Workflows
- book appointment -> reminders -> check-in
- provider schedule management
- consent capture
- record access with audit

## Permissions
- patient.read
- appointment.manage
- record.access.audited

## Reports
- appointment volume
- no-show rate
- provider utilization
