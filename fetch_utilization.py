"""
fetch_utilization.py
Pulls Total Fleet Utilization from Tableau Cloud and writes data.json.
Runs via GitHub Actions every Monday 6am MT.
"""

import os
import json
import requests
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────
SERVER   = "https://us-west-2b.online.tableau.com"
SITE     = "lvt"
PAT_NAME = os.environ["TABLEAU_PAT_NAME"]
PAT_SECRET = os.environ["TABLEAU_PAT_SECRET"]

# View path matches the URL: FleetManagementDashboard/FleetOverview
VIEW_NAME = "FleetOverview"

# The exact field name in the Tableau view CSV export
FIELD_NAME = "Total Fleet Utilization"

API = f"{SERVER}/api/3.21"

# ── Step 1: Sign in ───────────────────────────────────────────────────
print("Signing in to Tableau Cloud...")
signin_resp = requests.post(
    f"{API}/auth/signin",
    json={
        "credentials": {
            "personalAccessTokenName":   PAT_NAME,
            "personalAccessTokenSecret": PAT_SECRET,
            "site": {"contentUrl": SITE}
        }
    },
    headers={"Accept": "application/json", "Content-Type": "application/json"}
)
signin_resp.raise_for_status()
auth      = signin_resp.json()["credentials"]
token     = auth["token"]
site_id   = auth["site"]["id"]
print(f"  Signed in. Site ID: {site_id}")

headers = {
    "X-Tableau-Auth": token,
    "Accept": "application/json"
}

# ── Step 2: Find the view ─────────────────────────────────────────────
print(f"Looking up view: {VIEW_NAME}...")
views_resp = requests.get(
    f"{API}/sites/{site_id}/views",
    params={"filter": f"viewUrlName:eq:{VIEW_NAME}"},
    headers=headers
)
views_resp.raise_for_status()
views = views_resp.json().get("views", {}).get("view", [])

if not views:
    raise RuntimeError(f"View '{VIEW_NAME}' not found. Check the view name.")

view_id = views[0]["id"]
print(f"  View ID: {view_id}")

# ── Step 3: Download view CSV data ────────────────────────────────────
print("Downloading view data (CSV)...")
csv_resp = requests.get(
    f"{API}/sites/{site_id}/views/{view_id}/data",
    headers={**headers, "Accept": "text/csv"}
)
csv_resp.raise_for_status()

# ── Step 4: Parse the utilization value ──────────────────────────────
print("Parsing utilization value...")
lines = csv_resp.text.strip().splitlines()

# Find the column index for FIELD_NAME
header = [col.strip().strip("'\"") for col in lines[0].split("\t")]
print(f"  Columns found: {header}")

if FIELD_NAME not in header:
    # Try comma-separated fallback
    header = [col.strip().strip("'\"") for col in lines[0].split(",")]
    print(f"  Retrying with comma separator: {header}")

if FIELD_NAME not in header:
    raise RuntimeError(f"Field '{FIELD_NAME}' not found in columns: {header}")

col_idx = header.index(FIELD_NAME)
raw_val = lines[1].split("\t")[col_idx].strip().strip("'\"")

# Strip % sign and convert to float
utilization = float(raw_val.replace("%", "").strip())
print(f"  Total Fleet Utilization: {utilization}%")

# ── Step 5: Sign out ──────────────────────────────────────────────────
requests.post(f"{API}/auth/signout", headers=headers)

# ── Step 6: Write data.json ───────────────────────────────────────────
now = datetime.now(timezone.utc).isoformat()

# Load existing history if present
try:
    with open("data.json") as f:
        existing = json.load(f)
    history = existing.get("history", [])
except (FileNotFoundError, json.JSONDecodeError):
    history = []

# Append today's reading (deduplicate by date)
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
history = [h for h in history if h["date"] != today]
history.append({"date": today, "value": utilization})
history = history[-12:]  # Keep last 12 weeks

output = {
    "utilization": utilization,
    "target":      92.0,
    "fleet_total": 12399,
    "refreshed_at": now,
    "history":     history
}

with open("data.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"  data.json written: {utilization}% as of {now}")
print("Done.")
