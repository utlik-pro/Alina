# Crystal Lab release checks

Production branch: `codex/crystal-v2`. Render service: `srv-d7d1u0reo5us7381mqc0`.
Auto-deploy is disabled; a push is not a deployment.

1. Install `pip install -r requirements.txt`. The checked dependency set is pinned
   in `requirements.lock`, including transitive packages and SQLAlchemy's asyncio extra.
2. Run pytest with dummy API credentials and mocks, then
   `python scripts/check_startup.py` (disposable SQLite DB, mocked Telegram registration).
3. Commit only reviewed files and push. **Bot CI** on that exact commit must pass:
   tests, Linux Docker build, then application startup/health/shutdown with no network.
4. Run `python scripts/deploy_checked.py` for a read-only release check. To release,
   run `python scripts/deploy_checked.py --deploy --key-file /path/to/render.key`.
   Alternatively set `RENDER_API_KEY`; never put the token in a command argument.
   The command rejects a different branch, tracked local edits, an unpushed head,
   missing/pending/failed CI or checks for another revision. It deploys an explicit SHA.
5. Wait for Render `live`, verify `/` reports the exact revision, and replay the
   changed scenarios using reserved smoke subscribers (770099xxx). Their outgoing
   replies stay in the internal smoke sink. Do not create customer appointments.

Use this release command for normal deployments. Render dashboard/API access can
still bypass it; it is not an account-wide restriction. Manual rollback remains possible.

## Updating dependencies

Keep `requirements.txt` as the list of direct requirements. In a clean Python 3.11
venv, install the desired updated set without the old constraints, run the full
suite and startup check, then regenerate `requirements.lock` with `pip freeze`.
Review all version changes and let Linux Docker CI verify the new set before release.
Never regenerate the lock from a general-purpose developer environment.
