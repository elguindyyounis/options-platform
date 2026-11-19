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
forgotten and the page says so. A plain URL in a browser that has never been given the token still shows Connect, on purpose: the server
never hands its token to an unauthenticated request. `Install-On-Mac.command` (double-click) runs the installer.

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
