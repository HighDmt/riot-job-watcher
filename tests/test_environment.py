"""
Riot Watcher Test Environment

Usage:
    python test_environment.py                        # Run all logic tests
    python test_environment.py --list                 # List available scenarios
    python test_environment.py --scenario new_jobs    # Run specific logic test
    python test_environment.py --discord new          # Send test Discord alert
    python test_environment.py --discord removed      # Send test Discord alert
    python test_environment.py --discord both         # Send both alert types
    python test_environment.py --discord mixed        # Send new + removed in one batch
    python test_environment.py --live                 # Hit real Riot API, alert to test webhook
    python test_environment.py --notify-test          # Test Windows warning notification
    python test_environment.py --clean                # Clean up snapshot files
"""

import json
import os
import logging
import argparse
import requests
import subprocess
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import sys

test_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(test_dir)
sys.path.insert(0, root_dir)

MAX_LOG_LINES = 750


class PrependFileHandler(logging.FileHandler):
    def emit(self, record):
        msg = self.format(record) + '\n'
        try:
            if os.path.exists(self.baseFilename):
                with open(self.baseFilename, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                existing = ''.join(lines[:MAX_LOG_LINES - 1])
            else:
                existing = ''
            with open(self.baseFilename, 'w', encoding='utf-8') as f:
                f.write(msg + existing)
        except Exception:
            self.handleError(record)


def show_windows_notification(title, message, level=logging.WARNING):
    """Fire a Windows balloon notification. Non-blocking."""
    safe_title = title.replace('"', '').replace("'", '')
    safe_message = message.replace('"', '').replace("'", '')
    icon = 'Error' if level >= logging.ERROR else 'Warning'
    tip_icon = 'Error' if level >= logging.ERROR else 'Warning'
    ps = (
        'Add-Type -AssemblyName System.Windows.Forms; '
        '$n = New-Object System.Windows.Forms.NotifyIcon; '
        f'$n.Icon = [System.Drawing.SystemIcons]::{icon}; '
        '$n.Visible = $true; '
        f'$n.ShowBalloonTip(8000, "{safe_title}", "{safe_message}", '
        f'[System.Windows.Forms.ToolTipIcon]::{tip_icon}); '
        'Start-Sleep 9; '
        '$n.Dispose()'
    )
    subprocess.Popen(
        ['powershell', '-WindowStyle', 'Hidden', '-NonInteractive', '-Command', ps],
        creationflags=subprocess.CREATE_NO_WINDOW
    )


class WindowsWarningHandler(logging.Handler):
    def emit(self, record):
        title = "Riot Watcher — Error" if record.levelno >= logging.ERROR else "Riot Watcher — Warning"
        show_windows_notification(title, self.format(record), level=record.levelno)


test_log_file = os.path.join(test_dir, "test.log")
test_logger = logging.getLogger("riot_watcher")
test_logger.handlers.clear()
test_logger.propagate = False
handler = PrependFileHandler(test_log_file)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
test_logger.addHandler(handler)
notify_handler = WindowsWarningHandler()
notify_handler.setLevel(logging.WARNING)
notify_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
test_logger.addHandler(notify_handler)
test_logger.setLevel(logging.INFO)

TEST_WEBHOOK = "https://discord.com/api/webhooks/1506378975688003713/lGiEaw-T2hXZcPI-5Dz7iBAT-95-w35iOvskE1C7s1mygBa6kE1T5ThtO7WCURJpfczD"
RIOT_ICON = "https://wiki.leagueoflegends.com/en-us/images/Riot_Games_logo_icon.png"

FAKE_JOBS_NEW = [
    {"title": "Senior Backend Engineer - MMO Services, R&D Product Engineering Group MMO Seattle, USA", "url": "https://www.riotgames.com/en/j/7702443"},
    {"title": "Lead Game Designer - MMO Content, R&D Product Design Group MMO Los Angeles, USA", "url": "https://www.riotgames.com/en/j/7702444"},
]

FAKE_JOBS_REMOVED = [
    {"title": "Senior Backend Engineer - MMO Services", "url": "https://www.riotgames.com/en/j/old1", "first_seen": "2026-05-17T08:00:00+00:00"},
    {"title": "Lead Game Designer - MMO Content", "url": "https://www.riotgames.com/en/j/old2", "first_seen": "2026-05-16T14:00:00+00:00"},
]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def cleanup_snapshots():
    """Delete all snapshot files from tests folder."""
    count = 0
    for f in os.listdir(test_dir):
        if f.startswith("snap_") and f.endswith(".json"):
            path = os.path.join(test_dir, f)
            os.remove(path)
            count += 1
    print(f"Cleaned up {count} snapshot file(s)")


def _send(message, color):
    """Send a Discord alert to the test webhook."""
    payload = {
        "embeds": [{
            "description": message,
            "color": color,
            "thumbnail": {"url": RIOT_ICON},
            "footer": {
                "text": f"[TEST] {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                "icon_url": RIOT_ICON
            }
        }]
    }
    try:
        r = requests.post(TEST_WEBHOOK, json=payload, timeout=10)
        return "✅ sent" if r.status_code == 204 else f"⚠️ status {r.status_code}"
    except Exception as e:
        return f"❌ error: {e}"


# ---------------------------------------------------------------------------
# Discord alerts
# ---------------------------------------------------------------------------

def discord_new_alert(jobs=None):
    """Send new job alerts to Discord."""
    if jobs is None:
        jobs = FAKE_JOBS_NEW
    for job in jobs:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        msg = (
            f"🟢 **New Riot MMO Job Posted!**\n\n"
            f"[{job['title']}]({job['url']})\n\n"
            f"Posted: <t:{timestamp}:R>"
        )
        status = _send(msg, 0x00ff00)
        print(f"  New job alert — {status}: {job['title'][:60]}...")
        time.sleep(0.5)  # Rate limiting


def discord_removed_alert(jobs=None):
    """Send removed job alerts to Discord."""
    if jobs is None:
        jobs = FAKE_JOBS_REMOVED
    for job in jobs:
        timestamp = int(datetime.fromisoformat(job["first_seen"]).timestamp())
        msg = (
            f"🔴 **Riot MMO Job Removed**\n\n"
            f"[{job['title']}]({job['url']})\n\n"
            f"Was posted: <t:{timestamp}:R>"
        )
        status = _send(msg, 0xff0000)
        print(f"  Removed job alert — {status}: {job['title'][:60]}...")
        time.sleep(0.5)  # Rate limiting


def discord_mixed_batch():
    """Send a realistic batch: new jobs, then removed jobs."""
    print("  Sending mixed batch (new + removed)...")
    discord_new_alert(FAKE_JOBS_NEW)
    discord_removed_alert(FAKE_JOBS_REMOVED)
    print("  Batch complete")


# ---------------------------------------------------------------------------
# Logic tests
# ---------------------------------------------------------------------------

class FakeRiotAPI:
    SCENARIO_NORMAL       = "normal"
    SCENARIO_NEW_JOBS     = "new_jobs"
    SCENARIO_NO_JOBS      = "no_jobs"

    SCENARIO_MALFORMED    = "malformed"
    SCENARIO_TIMEOUT      = "timeout"
    SCENARIO_ERROR        = "error"

    def __init__(self, scenario):
        self.scenario = scenario

    def get_response(self):
        if self.scenario == self.SCENARIO_TIMEOUT:
            raise TimeoutError("Simulated timeout")
        if self.scenario == self.SCENARIO_ERROR:
            raise Exception("HTTP 500: Server Error")
        if self.scenario == self.SCENARIO_MALFORMED:
            return "<html><body>No job links here</body></html>"
        if self.scenario == self.SCENARIO_NO_JOBS:
            return "<html><body>No MMO jobs currently available</body></html>"

        html = """<html><body>
            <a href="/en/j/7702439">Manager, Software Engineering – Automation MMO Sydney, Australia</a>
            <a href="/en/j/7702440">Manager, Technical Art - Rendering MMO Sydney, Australia</a>
            <a href="/en/j/7702441">Senior Technical Artist, Animation MMO Los Angeles, USA</a>
            <a href="/en/j/7702442">Technical Producer MMO Sydney, Australia</a>
        """
        if self.scenario == self.SCENARIO_NEW_JOBS:
            html += """
            <a href="/en/j/7702443">Senior Backend Engineer - MMO Services MMO Seattle, USA</a>
            <a href="/en/j/7702444">Lead Game Designer - MMO Content MMO Los Angeles, USA</a>
            """
        return html + "</body></html>"


class LogicTest:
    def __init__(self, name, scenario, pre_snapshot=None,
                 expect_alerts=None, expect_errors=False, expect_snapshot=None):
        self.name = name
        self.scenario = scenario
        self.snapshot_file = os.path.join(test_dir, f"snap_{name.lower().replace(' ', '_')}.json")
        self.pre_snapshot = pre_snapshot
        self.expect_alerts = expect_alerts
        self.expect_errors = expect_errors
        self.expect_snapshot = expect_snapshot  # dict: {job_count, all_have_first_seen, ids_present, ids_absent}
        self.captured_alerts = []
        self.errors = []
        self.assertions = []

    def setup(self):
        if self.pre_snapshot:
            with open(self.snapshot_file, 'w') as f:
                json.dump(self.pre_snapshot, f, indent=2)
        elif os.path.exists(self.snapshot_file):
            os.remove(self.snapshot_file)

    def capture_alert(self, message, color):
        self.captured_alerts.append({"message": message, "color": color})

    def verify_snapshot_state(self):
        """Assert the final snapshot file matches expected state."""
        if self.expect_snapshot is None:
            return

        exp = self.expect_snapshot

        if not os.path.exists(self.snapshot_file):
            self.assertions.append(("Snapshot file exists after run", False))
            return

        try:
            with open(self.snapshot_file) as f:
                snap = json.load(f)
        except Exception as e:
            self.assertions.append((f"Snapshot file is valid JSON: {e}", False))
            return

        if "job_count" in exp:
            passed = len(snap) == exp["job_count"]
            self.assertions.append((
                f"Snapshot has {exp['job_count']} job(s) (got {len(snap)})", passed
            ))

        if exp.get("all_have_first_seen"):
            missing = [k for k, v in snap.items() if "first_seen" not in v]
            passed = len(missing) == 0
            self.assertions.append((
                f"All snapshot jobs have 'first_seen' field" +
                (f" (missing: {missing})" if missing else ""), passed
            ))

        for id_ in exp.get("ids_present", []):
            passed = id_ in snap
            self.assertions.append((f"Snapshot contains job ID '{id_}'", passed))

        for id_ in exp.get("ids_absent", []):
            passed = id_ not in snap
            self.assertions.append((f"Snapshot excludes job ID '{id_}'", passed))

    def run(self):
        print(f"\n{'='*70}")
        print(f"LOGIC TEST: {self.name}")
        print(f"{'='*70}")

        self.setup()

        try:
            import riot_watcher
            fake_api = FakeRiotAPI(self.scenario)

            with patch('riot_watcher.requests.get') as mock_get, \
                 patch('riot_watcher.send_discord_alert', side_effect=self.capture_alert), \
                 patch('riot_watcher.SNAPSHOT_FILE', self.snapshot_file), \
                 patch('test_environment.show_windows_notification'):

                mock_response = MagicMock()
                mock_response.text = fake_api.get_response()
                mock_response.raise_for_status = MagicMock()
                mock_get.return_value = mock_response

                riot_watcher.check_for_changes()

        except Exception as e:
            self.errors.append(str(e))

        if self.expect_alerts is not None:
            passed = len(self.captured_alerts) == self.expect_alerts
            self.assertions.append((f"Expected {self.expect_alerts} alert(s), got {len(self.captured_alerts)}", passed))

        self.assertions.append((
            f"Expected {'errors' if self.expect_errors else 'no errors'}",
            bool(self.errors) == self.expect_errors
        ))

        self.verify_snapshot_state()

        print(f"  Alerts captured: {len(self.captured_alerts)}")
        if self.errors:
            for e in self.errors:
                print(f"  ⚠️  {e}")
        for description, passed in self.assertions:
            print(f"  {'✅' if passed else '❌'} {description}")

        if os.path.exists(self.snapshot_file):
            os.remove(self.snapshot_file)

        return all(p for _, p in self.assertions)


class TestSuite:
    def __init__(self):
        self.tests = []

    def add(self, *args, **kwargs):
        self.tests.append(LogicTest(*args, **kwargs))

    def run_all(self):
        print("\n" + "="*70)
        print("LOGIC TEST SUITE")
        print("="*70)

        passed = failed = 0
        for test in self.tests:
            if test.run():
                passed += 1
            else:
                failed += 1

        print(f"\n{'='*70}")
        print(f"COMPLETE — ✅ {passed} passed  ❌ {failed} failed")
        print("="*70 + "\n")

    def run_one(self, name):
        match = next((t for t in self.tests if t.name.lower() == name.lower()), None)
        if not match:
            print(f"Test '{name}' not found. Available: {[t.name for t in self.tests]}")
            return
        match.run()

    def list_all(self):
        print("\n" + "="*70)
        print("AVAILABLE LOGIC TESTS")
        print("="*70)
        for i, test in enumerate(self.tests, 1):
            print(f"{i}. {test.name}")
        print("="*70 + "\n")


def run_live():
    """Run check_for_changes() against the real Riot API using the test webhook and a separate snapshot."""
    import riot_watcher

    live_snapshot = os.path.join(test_dir, "live_snap.json")
    captured = []

    def capture_and_send(message, color):
        captured.append({"message": message, "color": color})
        _send(message, color)

    print("\n" + "="*70)
    print("LIVE TEST — Real Riot API → Test Webhook")
    print(f"Snapshot: {live_snapshot}")
    print("="*70)

    with patch('riot_watcher.DISCORD_WEBHOOK_URL', TEST_WEBHOOK), \
         patch('riot_watcher.SNAPSHOT_FILE', live_snapshot), \
         patch('riot_watcher.send_discord_alert', side_effect=capture_and_send):
        riot_watcher.check_for_changes()

    print(f"\n  Alerts sent: {len(captured)}")
    for i, a in enumerate(captured, 1):
        color_label = "🟢 NEW" if a["color"] == 0x00ff00 else "🔴 REMOVED"
        print(f"  {i}. {color_label}")
    print("="*70 + "\n")


def build_suite():
    suite = TestSuite()

    suite.add("No Changes", FakeRiotAPI.SCENARIO_NORMAL,
              pre_snapshot={
                  "7702439": {"title": "Job 1 MMO", "url": "url1", "first_seen": "2026-05-19T10:00:00+00:00"},
                  "7702440": {"title": "Job 2 MMO", "url": "url2", "first_seen": "2026-05-19T10:00:00+00:00"},
                  "7702441": {"title": "Job 3 MMO", "url": "url3", "first_seen": "2026-05-19T10:00:00+00:00"},
                  "7702442": {"title": "Job 4 MMO", "url": "url4", "first_seen": "2026-05-19T10:00:00+00:00"},
              },
              expect_alerts=0, expect_errors=False,
              expect_snapshot={"job_count": 4, "all_have_first_seen": True})

    suite.add("New Jobs", FakeRiotAPI.SCENARIO_NEW_JOBS,
              expect_alerts=6, expect_errors=False,
              expect_snapshot={"job_count": 6, "all_have_first_seen": True})

    suite.add("Removed Jobs", FakeRiotAPI.SCENARIO_NORMAL,
              pre_snapshot={
                  "7702439": {"title": "Job 1 MMO", "url": "url1", "first_seen": "2026-05-19T10:00:00+00:00"},
                  "7702440": {"title": "Job 2 MMO", "url": "url2", "first_seen": "2026-05-19T10:00:00+00:00"},
                  "7702441": {"title": "Job 3 MMO", "url": "url3", "first_seen": "2026-05-19T10:00:00+00:00"},
                  "7702442": {"title": "Job 4 MMO", "url": "url4", "first_seen": "2026-05-19T10:00:00+00:00"},
                  "old_1":   {"title": "Old Job 1 MMO", "url": "url5", "first_seen": "2026-05-17T08:00:00+00:00"},
                  "old_2":   {"title": "Old Job 2 MMO", "url": "url6", "first_seen": "2026-05-16T14:00:00+00:00"},
              },
              expect_alerts=2, expect_errors=False,
              expect_snapshot={"job_count": 4, "all_have_first_seen": True,
                               "ids_present": ["7702439", "7702440", "7702441", "7702442"],
                               "ids_absent": ["old_1", "old_2"]})

    suite.add("No MMO Jobs", FakeRiotAPI.SCENARIO_NO_JOBS,
              expect_alerts=0, expect_errors=False)



    suite.add("Page Structure Changed", FakeRiotAPI.SCENARIO_MALFORMED,
              expect_alerts=0, expect_errors=False)

    suite.add("Network Timeout", FakeRiotAPI.SCENARIO_TIMEOUT,
              expect_alerts=0, expect_errors=True)

    suite.add("Server Error", FakeRiotAPI.SCENARIO_ERROR,
              expect_alerts=0, expect_errors=True)

    return suite


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Riot Watcher Test Environment")
    parser.add_argument("--scenario", type=str, help="Run a specific logic test by name")
    parser.add_argument("--list", action="store_true", help="List all available logic tests")
    parser.add_argument("--discord", choices=["new", "removed", "both", "mixed"],
                        help="Send test Discord alert(s) to the test webhook")
    parser.add_argument("--live", action="store_true",
                        help="Run against the real Riot API using the test webhook")
    parser.add_argument("--notify-test", action="store_true",
                        help="Fire a test Windows warning notification")
    parser.add_argument("--clean", action="store_true", help="Clean up snapshot files")
    args = parser.parse_args()

    if args.notify_test:
        print("Firing test notifications (warning + error)...")
        show_windows_notification("Riot Watcher — Warning", "WARNING - No MMO jobs found in current listings", level=logging.WARNING)
        time.sleep(1)
        show_windows_notification("Riot Watcher — Error", "ERROR - Failed to fetch jobs after 3 attempts", level=logging.ERROR)
        print("Notifications sent (should appear in system tray)")
        return

    if args.live:
        run_live()
        return

    if args.clean:
        cleanup_snapshots()
        return

    if args.list:
        suite = build_suite()
        suite.list_all()
        return

    if args.discord:
        print(f"\nSending Discord alert(s) to test webhook...")
        if args.discord == "new":
            discord_new_alert()
        elif args.discord == "removed":
            discord_removed_alert()
        elif args.discord == "both":
            discord_new_alert()
            discord_removed_alert()
        elif args.discord == "mixed":
            discord_mixed_batch()
        return

    suite = build_suite()
    if args.scenario:
        suite.run_one(args.scenario)
    else:
        suite.run_all()


if __name__ == "__main__":
    main()
