# Contributing to Coda

Thanks for wanting to help. Coda is a small, friendly project — these few rules
keep it that way.

## Quick start
```bash
git clone https://github.com/haziqcodes/coda-play.git
cd coda-play
make install      # venv + deps
make test         # run the test suite
make run          # start on http://127.0.0.1:8000
```

## How to contribute
1. **Find or open an issue** first — big features get discussed before code.
2. **Fork → branch → commit** — branch names like `fix/audio-seek` or `feat/shuffle`.
3. **Conventional commits**: `feat: …`, `fix: …`, `docs: …`, `test: …`, `chore: …`.
4. Keep CI green: `make lint` and `make test` must pass before you open a PR.
5. Fill in the PR template — reviewers (and future you) will thank you.
6. Before coding, read `ai/handoff.md` (live at the hidden `/ai` route) for current project state,
   and update it + the SKILL.md log before finishing your task.

## Ground rules
- **Personal-use tool.** We do not add features that facilitate redistribution,
  mass-ripping, or circumventing platform ToS. See the Legal section in README.
- No audio files, no `data/` contents, no secrets in commits.
- Light theme only, zero emojis, English UI (project style rules).
- Code style: 4-space indent, keep lines ≤ 140 chars (flake8 enforces it).

## Good first issues
Look for the `good first issue` label — perfect for your first PR.
