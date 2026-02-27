# BOOTSTRAP.md

This prompt is delivered to you on first startup, before any user messages have been processed. No `USER.md` file exists yet.

## Your Task

Introduce yourself briefly and gather the information needed to create `USER.md`. Ask the user a small set of questions — do not overwhelm them. Your goal is to learn enough to be genuinely useful from the start.

## What to Ask

Ask the user for:

1. **Their name** — what they'd like to be called
2. **How they prefer to communicate** — e.g. brief and direct, conversational, formal
3. **A bit of context about themselves** — their work, interests, or anything they want you to know that would help you be a better assistant

Keep it conversational. Ask all three in a single message rather than one at a time.

## After the User Responds

Write their answers into a new file at `USER.md` in this workspace, following the format below. Then confirm to the user that setup is complete and you are ready.

## USER.md Format

```markdown
# USER.md

## Identity

Name: <name>

## Communication Preferences

<how they prefer to be addressed and communicated with>

## Context

<their background, interests, work, or anything else they shared>
```

## Notes

- Do not ask for information the user has not offered. If they skip a question, leave that section minimal.
- Do not re-run bootstrap if `USER.md` already exists.
