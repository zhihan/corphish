# Cron Jobs

You can schedule recurring or one-shot prompts using the cron job system.
Jobs are stored in the SQLite database and executed by the cron scheduler daemon.

## Schema

**cron_jobs**
- `id` — auto-incremented primary key
- `name` — unique human-readable label
- `prompt` — the prompt sent to Claude when the job fires
- `cron_expr` — 5-field cron expression (minute hour dom month dow)
- `schedule_type` — `'recurring'` (default) or `'once'`
- `next_run_epoch` — unix timestamp of next fire; the scheduler computes the real next occurrence from `cron_expr` automatically, so set to `unixepoch()` on insert
- `enabled` — `1` = active, `0` = disabled

**cron_job_runs** — execution history
- `job_id`, `ran_at`, `status` (completed/error/skipped), `delivered` (delivered/suppressed)

## Cron expression syntax

Standard 5-field: `minute hour day-of-month month day-of-week`

Examples:
- `0 9 * * 1-5` — weekdays at 9am
- `*/30 * * * *` — every 30 minutes
- `0 8 * * 1` — every Monday at 8am
- `0 9 15 * *` — 15th of each month at 9am

## Creating a job

```bash
sqlite3 ~/.config/corphish/corphish.db "
INSERT INTO cron_jobs (name, prompt, cron_expr, schedule_type, next_run_epoch, created_at)
VALUES (
  'morning-standup',
  'It is standup time. Remind the user to post their standup update.',
  '0 9 * * 1-5',
  'recurring',
  unixepoch(),
  datetime('now')
);"
```

## Listing jobs

```bash
sqlite3 ~/.config/corphish/corphish.db "SELECT id, name, cron_expr, schedule_type, enabled, datetime(next_run_epoch, 'unixepoch', 'localtime') as next_run FROM cron_jobs;"
```

## Deleting a job

```bash
sqlite3 ~/.config/corphish/corphish.db "DELETE FROM cron_jobs WHERE name = 'morning-standup';"
```

## Disabling / re-enabling a job

```bash
sqlite3 ~/.config/corphish/corphish.db "UPDATE cron_jobs SET enabled = 0 WHERE name = 'morning-standup';"
sqlite3 ~/.config/corphish/corphish.db "UPDATE cron_jobs SET enabled = 1 WHERE name = 'morning-standup';"
```
