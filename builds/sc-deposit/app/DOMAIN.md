# Domain: Deposit Shield

## Entities to scaffold
- **Tenancy**: id, user_id, address, landlord, deposit_cents, move_in, move_out, return_deadline_days, status
- **EvidenceShot**: id, user_id, tenancy_id, phase, room, photo_ref, condition_note, taken_at
- **Deduction**: id, user_id, tenancy_id, amount_cents, landlord_reason, status
- **DisputeLetter**: id, user_id, tenancy_id, sent_at, method, body

## Workflows
- move in -> timestamped room-by-room evidence -> move out -> mirror evidence -> deductions arrive -> contest each with paired before/after proof -> dispute letter -> resolution or small claims with the full evidence log
