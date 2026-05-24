# Railway diagnostics — 2026-05-24T14:08:33.387644+00:00

## Tables present in schema

Present (16): activities, activity_laps, activity_streams, alembic_version, analysis_cache, goals, oauth_tokens, recommendation_feedback, recovery_metrics, sleep_sessions, strength_sets, sync_log, user_locations, user_profile, weather_snapshots, whoop_workouts

>>> MISSING expected tables (2): recovery_records, goal <<<
Extra tables not in audit list: goals, recovery_metrics

## oauth_tokens

- whoop: access=s53n…wnxw (len=87) refresh=HS1R…4NTc (len=87) expires_at=None (no-expiry) updated_at=2026-05-20 04:02:35.474586+00:00

## sync_log — last 30 rows

- 2026-04-28 23:43:24+00:00 whoop          status=error    records=0 error='Whoop refresh failed (HTTP 400): {"error":"invalid_request","error_description":"The request is missing a required parameter, includes an invalid parameter value, includes a parameter more than once, or is otherwise malformed","error_hint":"Make sure that the various parameters are correct, be aware of case sensitivity and trim you. Re-authorize at /api/auth/whoop.'
- 2026-04-28 23:43:21+00:00 strava         status=success  records=0 error='enriched=0'
- 2026-04-28 23:43:21+00:00 eight_sleep    status=success  records=0
- 2026-04-28 21:43:23+00:00 whoop          status=success  records=3
- 2026-04-28 21:43:22+00:00 eight_sleep    status=success  records=0
- 2026-04-28 21:43:21+00:00 strava         status=success  records=1 error='enriched=1'
- 2026-04-28 17:19:25+00:00 whoop          status=error    records=0 error='Whoop refresh failed (HTTP 400): {"error":"invalid_request","error_description":"The request is missing a required parameter, includes an invalid parameter value, includes a parameter more than once, or is otherwise malformed","error_hint":"Make sure that the various parameters are correct, be aware of case sensitivity and trim you. Re-authorize at /api/auth/whoop.'
- 2026-04-28 17:19:24+00:00 eight_sleep    status=success  records=0
- 2026-04-28 17:19:23+00:00 strava         status=success  records=0 error='enriched=0'
- 2026-04-28 15:19:26+00:00 whoop          status=error    records=0 error='Whoop refresh failed (HTTP 400): {"error":"invalid_request","error_description":"The request is missing a required parameter, includes an invalid parameter value, includes a parameter more than once, or is otherwise malformed","error_hint":"Make sure that the various parameters are correct, be aware of case sensitivity and trim you. Re-authorize at /api/auth/whoop.'
- 2026-04-28 15:19:24+00:00 eight_sleep    status=success  records=0
- 2026-04-28 15:19:23+00:00 strava         status=success  records=0 error='enriched=0'
- 2026-04-28 13:19:25+00:00 whoop          status=error    records=0 error='Whoop refresh failed (HTTP 400): {"error":"invalid_request","error_description":"The request is missing a required parameter, includes an invalid parameter value, includes a parameter more than once, or is otherwise malformed","error_hint":"Make sure that the various parameters are correct, be aware of case sensitivity and trim you. Re-authorize at /api/auth/whoop.'
- 2026-04-28 13:19:24+00:00 eight_sleep    status=success  records=1
- 2026-04-28 13:19:23+00:00 strava         status=success  records=0 error='enriched=0'
- 2026-04-28 11:19:25+00:00 whoop          status=error    records=0 error='Whoop refresh failed (HTTP 400): {"error":"invalid_request","error_description":"The request is missing a required parameter, includes an invalid parameter value, includes a parameter more than once, or is otherwise malformed","error_hint":"Make sure that the various parameters are correct, be aware of case sensitivity and trim you. Re-authorize at /api/auth/whoop.'
- 2026-04-28 11:19:24+00:00 eight_sleep    status=success  records=1
- 2026-04-28 11:19:23+00:00 strava         status=success  records=0 error='enriched=0'
- 2026-04-28 09:19:25+00:00 whoop          status=error    records=0 error='Whoop refresh failed (HTTP 400): {"error":"invalid_request","error_description":"The request is missing a required parameter, includes an invalid parameter value, includes a parameter more than once, or is otherwise malformed","error_hint":"Make sure that the various parameters are correct, be aware of case sensitivity and trim you. Re-authorize at /api/auth/whoop.'
- 2026-04-28 09:19:24+00:00 eight_sleep    status=success  records=1
- 2026-04-28 09:19:23+00:00 strava         status=success  records=0 error='enriched=0'
- 2026-04-28 07:19:25+00:00 whoop          status=error    records=0 error='Whoop refresh failed (HTTP 400): {"error":"invalid_request","error_description":"The request is missing a required parameter, includes an invalid parameter value, includes a parameter more than once, or is otherwise malformed","error_hint":"Make sure that the various parameters are correct, be aware of case sensitivity and trim you. Re-authorize at /api/auth/whoop.'
- 2026-04-28 07:19:24+00:00 eight_sleep    status=success  records=1
- 2026-04-28 07:19:23+00:00 strava         status=success  records=0 error='enriched=0'
- 2026-04-28 05:19:25+00:00 whoop          status=error    records=0 error='Whoop refresh failed (HTTP 400): {"error":"invalid_request","error_description":"The request is missing a required parameter, includes an invalid parameter value, includes a parameter more than once, or is otherwise malformed","error_hint":"Make sure that the various parameters are correct, be aware of case sensitivity and trim you. Re-authorize at /api/auth/whoop.'
- 2026-04-28 05:19:24+00:00 eight_sleep    status=success  records=0
- 2026-04-28 05:19:23+00:00 strava         status=success  records=0 error='enriched=0'
- 2026-04-28 03:19:25+00:00 whoop          status=error    records=0 error='Whoop refresh failed (HTTP 400): {"error":"invalid_request","error_description":"The request is missing a required parameter, includes an invalid parameter value, includes a parameter more than once, or is otherwise malformed","error_hint":"Make sure that the various parameters are correct, be aware of case sensitivity and trim you. Re-authorize at /api/auth/whoop.'
- 2026-04-28 03:19:24+00:00 eight_sleep    status=success  records=0
- 2026-04-28 03:19:23+00:00 strava         status=success  records=0 error='enriched=0'

## Data freshness — activities (Strava)

- latest=2026-04-28 19:03:25+00:00 count=1764

## Data freshness — sleep_sessions

- [eight_sleep] latest=2026-04-28 count=622
- [whoop] latest=2026-04-28 count=7

## Data freshness — recovery_records (Whoop)


## Data freshness — recovery_records — ERROR

check raised: ProgrammingError: (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError) <class 'asyncpg.exceptions.UndefinedTableError'>: relation "recovery_records" does not exist
[SQL: SELECT MAX(date) AS latest, COUNT(*) AS n FROM recovery_records]
(Background on this error at: https://sqlalche.me/e/20/f405)
sqlalchemy.exc.ProgrammingError: (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError) <class 'asyncpg.exceptions.UndefinedTableError'>: relation "recovery_records" does not exist
[SQL: SELECT MAX(date) AS latest, COUNT(*) AS n FROM recovery_records]
(Background on this error at: https://sqlalche.me/e/20/f405)

## strength_sets schema (Bug B)

- id: bigint nullable=NO
- activity_id: bigint nullable=YES
- date: date nullable=YES
- exercise_name: text nullable=YES
- set_number: bigint nullable=YES
- reps: bigint nullable=YES
- weight_kg: double precision nullable=YES
- rpe: double precision nullable=YES
- notes: text nullable=YES
- created_at: timestamp with time zone nullable=YES
- updated_at: timestamp with time zone nullable=YES
- performed_at: timestamp with time zone nullable=YES

`performed_at` is present — Bug B is NOT a missing-column issue.

## alembic_version

- version_num=d4f1a8b62c70

## Railway env-var presence (values NOT printed)

- DATABASE_URL: SET (len=94)
- DATABASE_PUBLIC_URL: UNSET
- PUBLIC_BASE_URL: UNSET
- SYNC_ON_STARTUP: UNSET
- SYNC_INTERVAL_HOURS: UNSET
- STRAVA_CLIENT_ID: UNSET
- STRAVA_CLIENT_SECRET: UNSET
- STRAVA_ACCESS_TOKEN: UNSET
- STRAVA_REFRESH_TOKEN: UNSET
- EIGHT_SLEEP_EMAIL: UNSET
- EIGHT_SLEEP_PASSWORD: UNSET
- EIGHT_SLEEP_USER_ID: UNSET
- EIGHT_SLEEP_REFRESH_TOKEN: UNSET
- WHOOP_ENABLED: UNSET
- WHOOP_CLIENT_ID: UNSET
- WHOOP_CLIENT_SECRET: UNSET
- WHOOP_ACCESS_TOKEN: UNSET
- WHOOP_REFRESH_TOKEN: UNSET
- OPENWEATHERMAP_API_KEY: UNSET
- WEATHER_PROVIDER: UNSET
