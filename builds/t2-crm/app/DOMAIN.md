# Domain: EV Charger Installation Leads

## Terminology
- **lead** — a homeowner inquiry about EV charger installation
- **installer** — the licensed electrician who receives and works leads
- **verdict** — the intake decision: HOT, WARM, NURTURE, or ESCALATE
- **panel risk** — fine, load-management candidate, or upgrade likely

## Entities to scaffold
- **Lead**: id, source, name, email, phone, zip, intent, answers, estimate_lo, estimate_hi, message, score, verdict, flags, gaps, draft_reply, panel_risk, status, created_at  _(A homeowner lead from the estimator form. Operator writes verdict/flags/gaps/draft_reply onto the record.)_
