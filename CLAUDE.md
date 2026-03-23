# Claude Instructions

## Session Start — Read Memory Files

At the start of every session, read these files to restore context:

1. `memory/user.md` — User profile, current projects, and background context
2. `memory/preferences.md` — How the user likes Claude to behave
3. `memory/people.md` — Relevant people and their roles
4. `memory/decisions.md` — Past decisions and their rationale

Use the contents of these files to inform your responses throughout the session.

## Session End — Update Memory Files

At the end of each session (or when significant context is gained), update the relevant memory files:

- Add new decisions to `memory/decisions.md`
- Add or update people entries in `memory/people.md`
- Update preferences if new ones were expressed in `memory/preferences.md`
- Update project status and notes in `memory/user.md`

Keep entries concise. Prefer updating existing entries over duplicating them.
