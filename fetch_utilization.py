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
SERVER     = "https://us-west-2b.online.tableau.com"
SITE       = "lvt"
PAT_NAME   = os.environ["TABLEAU_PAT_NAME"]
PAT_SECRET = os.environ["TABLEAU_PAT_SECRET"]
VIEW_NAME  = "FleetOverview"
FIELD_NAME = "Total Fleet Utilization"

# Try multiple API versions — Tableau Cloud varies by pod
API_VERSIONS = ["3.21", "3.20", "3.19", "3.18", "3.16"]

def signin(api_version):
    url  = f"{SERVER}/api/{api_version}/auth/signin"
    body = {
        "credentials": {
            "personalAccessTokenName":   PAT_NAME,
            "personalAccessTokenSecret": PAT_SECRET,
            "site": {"contentUrl": SITE}
        }
    }
    headers = {
        "Accept":       "application/json",
        "Content-Type": "application/json"
    }
    print(f"  Trying API version {api_version} ...")
    print(f"  POST {url}")
    print(f"  PAT name length: {len(PAT_NAME)}, secret length: {len(PAT_SECRET)}")

    resp = requests.post(url, json=body, headers=headers)
    print(f"  Response status: {resp.status_code}")

    if resp.status_code != 200:
        print(f"  Response body: {resp.text[:500]}")
        return None, None, None

    auth    = resp.json()["credentials"]
    token   = auth["token"]
    site_id = auth["site"]["id"]
    print(f"  SUCCESS — site_id: {site_id}")
    return token, site_id, api_version

# ── Step 1: Sign in (try multiple API versions) ───────────────────────
print("=" * 60)
print("Signing in to Tableau Cloud...")
print(f"Server: {SERVER}")
print(f"Site:   {SITE}")
print(f"PAT name (first 3 chars): {PAT_NAME[:3]}...")

token, site_id, api_version = None, None, None
for v in API_VERSIONS:
    token, site_id, api_version = signin(v)
    if token:
        break

if not token:
    raise RuntimeError(
        "Authentication failed on all API versions. "
        "Please verify: (1) PAT is not expired/revoked in Tableau Cloud, "
        "(2) PAT name matches exactly as shown in Tableau Account Settings, "
        "(3) Site content URL is 'lvt' (check your Tableau URL)."
    )

API     = f"{SERVER}/api/{api_version}"
headers = {"X-Tableau-Auth": token, "Accept": "application/json"}

# ── Step 2: Find the view ─────────────────────────────────────────────
print(f"\nLooking up view: {VIEW_NAME} ...")
views_resp = requests.get(
    f"{API}/sites/{site_id}/views",
    params={"filter": f"viewUrlName:eq:{VIEW_NAME}"},
    headers=headers
)
print(f"  Views response status: {views_resp.status_code}")

if views_resp.status_code != 200:
    print(f"  Response: {views_resp.text[:500]}")
    views_resp.raise_for_status()

views_data = views_resp.json()
views      = views_data.get("views", {}).get("view", [])
print(f"  Views found: {len(views)}")

if not views:
    # List all views to help diagnose
    print("  No matching view — listing all available views...")
    all_views = requests.get(
        f"{API}/sites/{site_id}/views",
        headers=headers
    ).json()
    for v in all_views.get("views", {}).get("view", [])[:20]:
        print(f"    - name: {v.get('name')} | urlName: {v.get('viewUrlName')} | id: {v.get('id')}")
    raise RuntimeError(
        f"View '{VIEW_NAME}' not found. Check the urlName values printed above."
    )

view_id   = views[0]["id"]
view_name = views[0].get("name")
print(f"  View ID: {view_id}  name: {view_name}")

# ── Step 3: Download view CSV data ────────────────────────────────────
print(f"\nDownloading view data (CSV)...")
csv_resp = requests.get(
    f"{API}/sites/{site_id}/views/{view_id}/data",
    headers={**headers, "Accept": "text/csv"}
)
print(f"  CSV response status: {csv_resp.status_code}")
print(f"  First 300 chars: {repr(csv_resp.text[:300])}")

if csv_resp.status_code != 200:
    raise RuntimeError(f"Failed to download CSV: {csv_resp.status_code} {csv_resp.text[:300]}")

# ── Step 4: Parse the utilization value ──────────────────────────────
print("\nParsing utilization value...")
lines = csv_resp.text.strip().splitlines()
print(f"  Lines in response: {len(lines)}")

if len(lines) < 2:
    raise RuntimeError(f"CSV has fewer than 2 lines. Raw content: {repr(csv_resp.text[:500])}")

# Try tab-separated first, then comma
for sep in ["\t", ","]:
    header = [c.strip().strip("'\"") for c in lines[0].split(sep)]
    if FIELD_NAME in header:
        print(f"  Found field using separator: {repr(sep)}")
        col_idx = header.index(FIELD_NAME)
        raw_val = lines[1].split(sep)[col_idx].strip().strip("'\"")
        break
else:
    print(f"  Header columns: {header}")
    raise RuntimeError(
        f"Field '{FIELD_NAME}' not found. "
        f"Available columns: {header}"
    )

utilization = float(raw_val.replace("%", "").strip())
print(f"  Total Fleet Utilization: {utilization}%")

# ── Step 5: Sign out ──────────────────────────────────────────────────
requests.post(f"{API}/auth/signout", headers=headers)
print("\nSigned out of Tableau.")

# ── Step 6: Write data.json ───────────────────────────────────────────
now   = datetime.now(timezone.utc).isoformat()
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

try:
    with open("data.json") as f:
        existing = json.load(f)
    history = existing.get("history", [])
except (FileNotFoundError, json.JSONDecodeError):
    history = []

history = [h for h in history if h["date"] != today]
history.append({"date": today, "value": utilization})
history = history[-12:]

output = {
    "utilization":  utilization,
    "target":       92.0,
    "fleet_total":  12399,
    "refreshed_at": now,
    "history":      history
}

with open("data.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\ndata.json written: {utilization}% as of {now}")
print("=" * 60)
print("Done.")
