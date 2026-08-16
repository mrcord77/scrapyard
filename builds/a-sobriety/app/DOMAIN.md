# Domain: Recovery / sobriety support

> Privacy/anonymity are first-class. Prefer field_encryption for journals, avoid auto-location, default journals private.

## Terminology
- **user** — an authenticated person using the app
- **profile** — a user's editable details
- **member** — a user participating in the community
- **feed** — stream of community activity
- **chip** — milestone token marking days/months sober
- **sponsor** — experienced peer guiding another member
- **meeting** — recovery gathering (in-person or online)
- **streak** — continuous days of sobriety
- **step work** — structured recovery program progress

## Entities to scaffold
- **User**: id, display_name, sobriety_date, timezone, is_anonymous  _(anonymity-first: display_name may be a handle)_
- **Membership**: id, user_id, role, joined_at
- **Post**: id, user_id, body, created_at
- **Sponsor**: id, sponsor_user_id, sponsee_user_id, since, status
- **Meeting**: id, title, kind, schedule, location_or_url, tags
- **Attendance**: id, user_id, meeting_id, attended_on
- **Chip**: id, user_id, milestone_days, awarded_on
- **JournalEntry**: id, user_id, body, mood, created_at, private  _(private by default)_
- **Milestone**: id, user_id, kind, reached_on

## Workflows
- sign up / sign in
- edit profile
- delete account
- join community
- post + react
- moderate content
- set sobriety date -> auto streak + chip awards
- find + attend meeting -> log attendance
- daily journal entry
- sponsor/sponsee pairing
- milestone celebration + chip

## Permissions
- profile.read.own
- profile.write.own
- post.write
- post.moderate
- journal.read.own
- journal.write.own
- sponsor.view.sponsee_progress
- meeting.manage

## Reports
- active users
- signups over time
- engagement
- retention cohorts
- current streak
- chips earned
- meeting attendance over time
- journaling consistency
