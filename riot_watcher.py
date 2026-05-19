import requests
import json
import os
import subprocess
import time
import sys
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

log_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(log_dir, "watcher.log")


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


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        PrependFileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
_notify_handler = WindowsWarningHandler()
_notify_handler.setLevel(logging.WARNING)
_notify_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
logger.addHandler(_notify_handler)

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1506305530761576478/4vRRQOyCjYp2uAhge-kjSNzCa768QkMZTPN9qAV078On_4UontRWdcXtVjOldjgRlVmM"
JOBS_URL = "https://www.riotgames.com/en/work-with-us/jobs"
SNAPSHOT_FILE = os.path.join(log_dir, "mmo_jobs.json")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 3600))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

RIOT_ICON = "https://wiki.leagueoflegends.com/en-us/images/Riot_Games_logo_icon.png"

def fetch_mmo_jobs(max_retries=3):
    """Scrape the Riot jobs page with retry logic. Returns dict {id: data} or None on failure."""
    for attempt in range(max_retries):
        try:
            response = requests.get(JOBS_URL, headers=HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            jobs = {}
            job_links = soup.select("a[href^='/en/j/']")

            if not job_links:
                logger.warning("No job links found. Page structure may have changed.")
                return None

            for link in job_links:
                text = link.get_text(" ", strip=True)
                href = link.get("href")
                if not href:
                    continue
                url_id = href.split("/")[-1]
                if "MMO" in text:
                    jobs[url_id] = {
                        "title": text,
                        "url": f"https://www.riotgames.com{href}"
                    }

            if jobs:
                logger.info(f"Found {len(jobs)} MMO job(s)")
            else:
                logger.warning("No MMO jobs found in current listings")

            return jobs
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching jobs (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 2
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e} (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 2
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
        except Exception as e:
            logger.error(f"Unexpected error fetching jobs: {e}")
            return None

    logger.error(f"Failed to fetch jobs after {max_retries} attempts")
    return None

def load_snapshot():
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading snapshot: {e}")
    return {}

def save_snapshot(jobs):
    try:
        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(jobs, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving snapshot: {e}")

def send_discord_alert(message, color, max_retries=2):
    for attempt in range(max_retries):
        try:
            payload = {
                "embeds": [{
                    "description": message,
                    "color": color,
                    "thumbnail": {
                        "url": RIOT_ICON
                    },
                    "footer": {
                        "text": f"Checked at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                        "icon_url": RIOT_ICON
                    }
                }]
            }
            r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            if r.status_code == 204:
                logger.info(f"Discord alert sent successfully")
            else:
                logger.warning(f"Discord returned status {r.status_code}")
            return
        except requests.exceptions.RequestException as e:
            logger.error(f"Discord send error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"Unexpected error sending Discord alert: {e}")
            return

def check_for_changes():
    current = fetch_mmo_jobs()
    if current is None:
        logger.warning("Skipping this check due to fetch failure")
        return

    previous = load_snapshot()

    added = {k: v for k, v in current.items() if k not in previous}
    removed = {k: v for k, v in previous.items() if k not in current}

    now = datetime.now(timezone.utc).isoformat()

    for url_id, job in added.items():
        current[url_id]["first_seen"] = now
        timestamp = int(datetime.fromisoformat(now).timestamp())
        msg = (
            f"🟢 **New Riot MMO Job Posted!**\n\n"
            f"[{job['title']}]({job['url']})\n\n"
            f"Posted: <t:{timestamp}:R>"
        )
        send_discord_alert(msg, 0x00ff00)
        logger.info(f"NEW: {job['title']}")
        time.sleep(0.5)

    for url_id, job in removed.items():
        first_seen_str = job.get("first_seen", now)
        timestamp = int(datetime.fromisoformat(first_seen_str).timestamp())
        msg = (
            f"🔴 **Riot MMO Job Removed**\n\n"
            f"[{job['title']}]({job['url']})\n\n"
            f"Was posted: <t:{timestamp}:R>"
        )
        send_discord_alert(msg, 0xff0000)
        logger.info(f"REMOVED: {job['title']}")
        time.sleep(0.5)

    for url_id in current:
        if url_id not in added and url_id in previous:
            current[url_id]["first_seen"] = previous[url_id].get("first_seen", now)

    if not added and not removed:
        logger.info("No changes detected")

    next_time = (datetime.now(timezone.utc) + timedelta(seconds=CHECK_INTERVAL)).strftime('%H:%M:%S UTC')
    logger.info(f"Next check at: {next_time}")

    save_snapshot(current)

if __name__ == "__main__":
    logger.info(f"Starting Riot MMO job watcher (check interval: {CHECK_INTERVAL}s)")

    while True:
        try:
            check_for_changes()
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)

        time.sleep(CHECK_INTERVAL)
