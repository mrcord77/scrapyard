# Domain: App where users interact around shared activity

## Terminology
- **user** — an authenticated person using the app
- **profile** — a user's editable details
- **member** — a user participating in the community
- **feed** — stream of community activity

## Entities to scaffold
- **User**: id, display_name, email, created_at
- **Membership**: id, user_id, role, joined_at
- **Post**: id, user_id, body, created_at

## Workflows
- sign up / sign in
- edit profile
- delete account
- join community
- post + react
- moderate content

## Permissions
- profile.read.own
- profile.write.own
- post.write
- post.moderate

## Reports
- active users
- signups over time
- engagement
- retention cohorts
