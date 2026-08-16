# Domain: Community Tool Library

## Entities to scaffold
- **Member**: id, name, status
- **Tool**: id, name, status
- **Reservation**: id, member_id, tool_id, start_at, end_at, status
- **Incident**: id, tool_id, reservation_id, note
- **MaintenanceRecord**: id, tool_id, status, resolution
- **Tag**: id, name

## Workflows
- reserve -> approve -> check out (tool->checked_out) -> return or damaged-return (auto incident+maintenance, tool->broken) -> complete maintenance (tool->available)
