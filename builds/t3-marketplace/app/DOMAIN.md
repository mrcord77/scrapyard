# Domain: Online retail / storefront

## Terminology
- **sku** — stock-keeping unit
- **cart** — pending order
- **fulfillment** — pick/pack/ship
- **variant** — size/color of a product

## Entities to scaffold
- **Product**: id, title, description, status, tags
- **Variant**: id, product_id, sku, price_cents, inventory_qty
- **Cart**: id, user_id, items, updated_at
- **Order**: id, user_id, status, total_cents, placed_at
- **Shipment**: id, order_id, carrier, tracking, status

## Workflows
- browse/search -> cart -> checkout -> pay
- inventory decrement on order
- refund/return
- abandoned cart recovery

## Permissions
- catalog.manage
- order.fulfill
- refund.issue
- inventory.adjust

## Reports
- revenue by period
- top SKUs
- cart abandonment
- inventory turnover
