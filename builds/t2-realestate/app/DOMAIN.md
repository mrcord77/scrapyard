# Domain: Property listings / brokerage

## Terminology
- **listing** — a property for sale/rent
- **agent** — licensed broker
- **showing** — scheduled property visit
- **MLS** — multiple listing service feed

## Entities to scaffold
- **Listing**: id, address, price_cents, status, beds, baths, sqft, agent_id
- **Agent**: id, user_id, license_no, brokerage
- **Showing**: id, listing_id, client_id, scheduled_at, status
- **Inquiry**: id, listing_id, name, contact, message, created_at

## Workflows
- create listing + media -> publish -> faceted search
- schedule showing
- capture + route inquiry
- status: active/pending/sold

## Permissions
- listing.manage.own
- showing.schedule
- inquiry.view

## Reports
- active inventory
- days on market
- showings per listing
- inquiry conversion
