import requests
import json
import os
import time
from bs4 import BeautifulSoup
from datetime import datetime

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
JOBS_URL = "https://www.riotgames.com/en/work-with-us/jobs"
SNAPSHOT_FILE = "mmo_jobs.json"
CHECK_INTERVAL = 3600  # seconds (10 minutes)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def fetch_mmo_jobs():
    """Scrape the Riot jobs page and return MMO jobs as a dict {id: title}."""
    response = requests.get(JOBS_URL, headers=HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    jobs = {}
    for link in soup.select("a[href^='/en/j/']"):
        text = link.get_text(" ", strip=True)
        href = link["href"]
        job_id = href.split("/")[-1]
        # Filter for MMO jobs
        if "MMO" in text:
            jobs[job_id] = {"title": text, "url": f"https://www.riotgames.com{href}"}
    return jobs

def load_snapshot():
    if os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE) as f:
            return json.load(f)
    return {}

def save_snapshot(jobs):
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(jobs, f, indent=2)

def send_discord_alert(message, color):
    payload = {
        "embeds": [{
            "description": message,
            "color": color,  # 0x00ff00 = green (new), 0xff0000 = red (removed)
            "footer": {"text": f"Checked at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"}
        }]
    }
    requests.post(DISCORD_WEBHOOK_URL, json=payload)

def check_for_changes():
    current = fetch_mmo_jobs()
    previous = load_snapshot()

    added = {k: v for k, v in current.items() if k not in previous}
    removed = {k: v for k, v in previous.items() if k not in current}

    for job_id, job in added.items():
        msg = f"🟢 **New Riot MMO Job Posted!**\n[{job['title']}]({job['url']})"
        send_discord_alert(msg, 0x00ff00)
        print(f"NEW: {job['title']}")

    for job_id, job in removed.items():
        msg = f"🔴 **Riot MMO Job Removed**\n~~{job['title']}~~\n(was at `{job['url']}`)"
        send_discord_alert(msg, 0xff0000)
        print(f"REMOVED: {job['title']}")

    if not added and not removed:
        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] No changes.")

    save_snapshot(current)

if __name__ == "__main__":
    print("Starting Riot MMO job watcher...")
    while True:
        try:
            check_for_changes()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(CHECK_INTERVAL)