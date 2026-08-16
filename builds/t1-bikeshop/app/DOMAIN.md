# Domain: Bicycle Repair Shop

## Entities to scaffold
- **User**: id, email
- **RepairTicket**: id, user_id, bike_model, parts_received, paid, status

## Workflows
- intake -> diagnosed -> ready (needs parts) -> picked_up (needs payment)
