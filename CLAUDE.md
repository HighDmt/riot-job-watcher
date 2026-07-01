# CLAUDE.md

Single-file Python watcher that scrapes Riot's careers page for **MMO** jobs and posts
adds/removes to Discord. Runs on a **GitHub Actions cron every 6 hours** — it is not a
long-running service.

## Commands

```bash
# Run once (this is the ONLY mode — see Gotchas). Use a dummy webhook locally so
# any alerts fail harmlessly instead of spamming the real Discord:
DISCORD_WEBHOOK_URL="https://invalid.example.invalid/webhook" python riot_watcher.py --once

pip install -r requirements.txt      # requests + beautifulsoup4 (unpinned)
python -m py_compile riot_watcher.py # quick syntax check (no test suite)
```

Manual production run: GitHub → **Actions → Check Riot MMO Jobs → Run workflow**
(`workflow_dispatch`).

## Architecture

- `riot_watcher.py` — everything: scrape → diff against snapshot → post to Discord → save.
- `.github/workflows/check-jobs.yml` — the cron + the commit-back step.
- `mmo_jobs.json` — the state snapshot, **tracked in git** (see State model).

Flow: `fetch_mmo_jobs()` (retry-wrapped scrape) → `check_for_changes()` diffs current vs
`load_snapshot()` → `send_discord_alert()` per add/remove → `save_snapshot()`.

## State model (important)

State lives in **git-tracked `mmo_jobs.json`**, not `actions/cache`. After each run the
workflow commits the updated snapshot back as `github-actions[bot]` and pushes it.

- **`git pull` before doing local work** — the bot moves `main` forward on its own between
  your sessions.
- The workflow needs repo setting **Settings → Actions → General → Workflow permissions =
  "Read and write"**, plus `permissions: contents: write` in the YAML. Pushes use
  `GITHUB_TOKEN`, which does **not** retrigger the workflow (no loop).
- **Cold-start guard**: if the snapshot is empty/missing, `check_for_changes()` seeds it
  silently and sends no alerts. This is why regenerating state locally is safe.

## Gotchas

- **Run mode**: the script always runs once and exits. There is no daemon loop; the
  `--once` flag is accepted but a no-op. Don't reintroduce `while True` / `CHECK_INTERVAL`.
- **Logging is stdout only** (GitHub Actions captures it). Don't add file handlers — a log
  file on the runner is discarded.
- **Scraper is fragile by nature**: it matches `a[href^='/en/j/']` and filters by the
  substring `"MMO" in text`. If Riot changes their HTML, `fetch_mmo_jobs()` returns `None`
  and fires one ⚠️ Discord alert. There is **no public JSON API** (verified) — keep
  BeautifulSoup.
- **Secret**: `DISCORD_WEBHOOK_URL` is a GitHub Actions secret and is required; the script
  exits 1 without it.
- `tests/` is gitignored and not part of CI.

## Design stance

Keep it lean (YAGNI). No database, no container, no daemon, no web framework. The retry/
backoff in `fetch_mmo_jobs`/`send_discord_alert` exists but is arguably overkill for a
6-hourly job — don't expand it.

Known easy extensions if asked: parameterize the hardcoded `"MMO"` keyword via env var;
add a self-healing agent triggered by the scraper-broke ⚠️ alert.
