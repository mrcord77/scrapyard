# Domain: Learning / courses

## Terminology
- **cohort** — a group moving through together
- **enrollment** — a learner registered in a course
- **module** — a unit of lessons
- **progress** — completion state

## Entities to scaffold
- **Course**: id, title, description, status, price_cents
- **Module**: id, course_id, title, order
- **Lesson**: id, module_id, title, content, media_id, order
- **Enrollment**: id, user_id, course_id, status, enrolled_at
- **Progress**: id, enrollment_id, lesson_id, completed_at

## Workflows
- publish course -> enroll (free/paid) -> track progress -> certificate
- cohort scheduling
- quizzes/assessments

## Permissions
- course.author
- enrollment.manage
- grade.submit

## Reports
- completion rate
- enrollment trend
- revenue per course
- lesson drop-off
