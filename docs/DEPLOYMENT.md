# Refresh the page, get the new build (Mac)

Paper research only. This changes how code reaches the Mac, not what the platform does.

**Flow:** work lands on `main` through a pull request, then the workflow `Test and promote stable release` runs the
tests and, only if they pass, moves the `stable` branch to that commit. The Mac follows `stable`.

**On the Mac:** run `bash deploy/install_mac.sh` once. It clones `stable` into `~/Applications/OptionsPlatform`, makes a
venv, writes the token to `~/Library/Application Support/OptionsPlatform/config.env` (chmod 600) and registers two
LaunchAgents: the server (restarted by launchd if it stops) and an hourly update check. The paper database lives in the
Application Support folder, outside the checkout, so an update never touches it.

**Connecting the browser (no typing):** the installer ends by opening the dashboard with the token in the URL fragment (never sent to
the server) and leaves `Open Options Dashboard` next to the app folder; double-click it to connect any browser. The page keeps the
token in that browser's local storage for `127.0.0.1`, so new tabs, refreshes and restarts stay connected; a rejected token is
forgotten and the page says so. Since 2026-11-19 (owner decision) a plain URL also connects by itself: the page asks `GET /api/session`, which gives the token only to
a page on the same machine (see CLAUDE.md rule 7 for the limits). `OPTPLAT_REQUIRE_PASTED_TOKEN=1` turns that off. `Install-On-Mac.command` (double-click) runs the installer.

**On refresh:** the dashboard, once per page load, calls `POST /api/deployment/check-on-refresh` (token required). The
server starts `deploy/update.sh`, at most once every 5 minutes, and only when started by the managed wrapper
(`OPTPLAT_MANAGED=1`). The page then polls `/api/health` and reloads itself when `build_id` changes; the build id is
also shown next to "Updated" at the top.

**What the updater does:** refuses if the checkout has local changes; fetches `stable`; refuses anything that is not a
fast-forward; copies the database to `backups/`; installs; compiles; rolls back to the previous commit if that fails;
then restarts the server through launchd. It takes no branch, commit or command from the API. Log: `update.log`.

**Limits:** a pull request or an unmerged branch is not a release and will not appear on refresh. The installer and
updater were written without a Mac, so they are untested on macOS: run `install_mac.sh` and check `update.log`
after the first refresh. Restart means a few seconds of downtime, and the in-memory simulated broker is rebuilt from
saved fills (see `SimBroker.restore`).

## Keeping the server up (watchdog, 2026-11-27)

On 2026-11-27 the server stayed down: its LaunchAgent had been unloaded (most likely by an install that stopped after
unloading it) and nothing loaded it again. Three changes stop that from happening again:

* `deploy/watchdog.sh` runs every 5 minutes as `com.optionsplatform.watchdog`. If the server's LaunchAgent is not loaded,
  it loads it again; if it is loaded but `/api/health` has not answered for about 30 seconds, it restarts it. It logs to
  `watchdog.log` in the data folder and does nothing while an update runs.
* `install_mac.sh` starts the server again on the way out if it stops partway after unloading it.
* `start-platform.command` no longer starts a second, window-bound copy when the background service is installed; it
  makes sure the service runs and opens the dashboard.

To stop the server on purpose and keep it stopped: `touch ~/Library/Application\ Support/OptionsPlatform/server-paused`,
then `launchctl kill TERM gui/$(id -u)/com.optionsplatform.server`. Delete the file (or run the installer or
`start-platform.command`) to resume. The kill switch on the System page is still the way to stop new trades.

## Account size (2026-11-27)

To run the paper options account at the size you plan to trade, add to `config.env` and restart the server:

```
OPTPLAT_PAPER_START_CASH=1000
OPTPLAT_MAX_POSITION_PCT=35
OPTPLAT_MAX_TOTAL_PREMIUM_PCT=70
```

A new size starts a new paper account from that moment (see `src/optplat/account.py`); earlier trades stay in the database
and the export. Removing the lines and restarting starts another new account at $100,000.

## Turning on the private data export (one time)

Scheduled research runs run in the cloud and cannot see the Mac's database. The nightly export (installed by `install_mac.sh`, 21:15) sends a secret-free copy to a PRIVATE repo, but only once `OPTPLAT_EXPORT_REPO` is set. On the Mac, after `gh auth login`, run `bash ~/options-platform/deploy/setup_export.sh` (or `bash deploy/setup_export.sh owner/name` for another repo name). It creates the private repo, writes the setting and runs one export. Then give the scheduled task access to that repo. The script refuses a repo that is not private.

## config.env lines reach the server (2026-11-28)

`deploy/server-wrapper.sh` used to load `config.env` without exporting it, so only lines written as `export KEY=value`
reached the server; a plain `KEY=value` (the installer's token line, `OPTPLAT_PAPER_START_CASH`, `OPTPLAT_MAX_POSITION_PCT`,
`OPTPLAT_MAX_TOTAL_PREMIUM_PCT`) stayed a shell variable. The wrapper now loads it with `set -a`, so both forms work. Effect on
the owner's Mac: the sizes in config.env now apply, and a changed `OPTPLAT_PAPER_START_CASH` starts a new paper account (account.py).
