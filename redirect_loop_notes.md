# Notes: Redirect Loop Investigation

## Observed Behavior
- POST /login → 302 (successful)
- GET /admin or /schueler → 302 (redirects to /)
- GET / → 302 (redirects to /admin or /schueler)
- **Loop continues indefinitely**

## Pattern Analysis
This is a classic redirect loop where:
1. Login succeeds (session created)
2. Protected route redirects unauthenticated users
3. Root route redirects authenticated users
4. This suggests **session is not being persisted/read correctly**

## Hypothesis
The Python script that removed caching might have accidentally removed critical session or database code that was near cache operations.

## Next Steps
1. Check models.py for any accidentally removed code
2. Verify session handling in login route
3. Check @admin_required and @student_required decorators
