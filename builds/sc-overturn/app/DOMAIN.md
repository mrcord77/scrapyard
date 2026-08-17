# Domain: Overturn

## Entities to scaffold
- **Claim**: id, user_id, insurer, claim_number, service, provider, service_date, billed_cents, status
- **Denial**: id, user_id, claim_id, denial_date, reason_code, reason_text, internal_appeal_deadline, external_review_deadline
- **Appeal**: id, user_id, claim_id, level, filed_at, argument, status
- **EvidenceItem**: id, user_id, claim_id, kind, title, body, received_at
- **CallLog**: id, user_id, claim_id, called_at, rep_name, reference_number, summary

## Workflows
- claim submitted -> denied (capture denial letter + deadlines) -> draft internal appeal -> file -> won (claim overturned -> paid) or upheld -> external review -> overturned/final
- every call to the insurer logged with rep name + reference number on a tamper-evident audit chain
