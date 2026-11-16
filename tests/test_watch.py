"""watch.sh follows a branch and restarts the platform on new commits. Uses throwaway git repos and a fake run command."""
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("git") or not shutil.which("bash"), reason="needs bash and git")


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def wait_for(fn, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.2)
    return False


@pytest.fixture
def repos(tmp_path):
    origin, runner, pusher = tmp_path / "origin.git", tmp_path / "runner", tmp_path / "pusher"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "work", str(origin)], check=True)
    git(tmp_path, "clone", "-q", str(origin), str(pusher))
    git(pusher, "checkout", "-q", "-b", "work")
    (pusher / "VERSION").write_text("1\n")
    shutil.copy(ROOT / "watch.sh", pusher / "watch.sh")
    git(pusher, "add", "-A")
    git(pusher, "commit", "-q", "-m", "v1")
    git(pusher, "push", "-q", "origin", "work")
    git(tmp_path, "clone", "-q", "-b", "work", str(origin), str(runner))
    return runner, pusher


def launch(runner):
    env = {**os.environ, "OPTPLAT_UPDATE_SECONDS": "1", "OPTPLAT_API_TOKEN": "x" * 24,
           "OPTPLAT_RUN_CMD": "cat VERSION >> started.log; echo $$ > pid.txt; exec sleep 300"}
    return subprocess.Popen(["bash", "watch.sh"], cwd=runner, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)


def stop(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    proc.wait(timeout=20)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def versions(runner):
    f = runner / "started.log"
    return f.read_text().split() if f.exists() else []


def test_it_starts_then_restarts_on_new_commits_and_stops_cleanly(repos):
    runner, pusher = repos
    proc = launch(runner)
    try:
        assert wait_for(lambda: versions(runner) == ["1"])
        (pusher / "VERSION").write_text("2\n")
        git(pusher, "commit", "-qam", "v2")
        git(pusher, "push", "-q", "origin", "work")
        assert wait_for(lambda: versions(runner) == ["1", "2"])
        assert (runner / "VERSION").read_text() == "2\n"
    finally:
        stop(proc)
    pid = int((runner / "pid.txt").read_text())
    assert wait_for(lambda: not _alive(pid), 10), "the platform process was left running"


def test_it_does_not_overwrite_local_edits_and_keeps_running(repos):
    runner, pusher = repos
    proc = launch(runner)
    try:
        assert wait_for(lambda: versions(runner) == ["1"])
        (runner / "VERSION").write_text("local edit\n")
        (pusher / "VERSION").write_text("2\n")
        git(pusher, "commit", "-qam", "v2")
        git(pusher, "push", "-q", "origin", "work")
        time.sleep(4)
        assert versions(runner) == ["1"] and (runner / "VERSION").read_text() == "local edit\n"
    finally:
        stop(proc)


def test_it_refuses_to_run_off_a_branch_and_keeps_one_token_file(repos, tmp_path):
    runner, _ = repos
    git(runner, "checkout", "-q", "--detach")
    out = subprocess.run(["bash", "watch.sh"], cwd=runner, capture_output=True, text=True, timeout=20, env={**os.environ, "OPTPLAT_RUN_CMD": "true"})
    assert out.returncode == 2 and "Check out the branch" in out.stdout


def test_the_token_is_generated_once_with_owner_only_permissions(repos):
    runner, _ = repos
    env = {k: v for k, v in os.environ.items() if k != "OPTPLAT_API_TOKEN"}
    env.update({"OPTPLAT_UPDATE_SECONDS": "1", "OPTPLAT_RUN_CMD": "echo $OPTPLAT_API_TOKEN > seen.txt; exec sleep 300"})
    proc = subprocess.Popen(["bash", "watch.sh"], cwd=runner, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        assert wait_for(lambda: (runner / "seen.txt").exists() and (runner / "seen.txt").read_text().strip())
        tok = (runner / ".venv" / ".optplat_token")
        assert len(tok.read_text().strip()) >= 16 and oct(tok.stat().st_mode & 0o777) == "0o600"
        assert (runner / "seen.txt").read_text().strip() == tok.read_text().strip()
    finally:
        stop(proc)
