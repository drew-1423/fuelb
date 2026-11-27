"""Check the public Streamlit-rendered snapshot after a deployment sync."""
import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import time

from playwright.sync_api import Error, sync_playwright


def inspect(public_url, expected, seconds):
    deadline = time.monotonic() + seconds
    result = {"status": "unreachable", "expected_release": expected["tag"]}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        while time.monotonic() < deadline:
            try:
                page.goto(public_url, wait_until="domcontentloaded", timeout=12000)
                wait = min(deadline, time.monotonic() + 24)
                while time.monotonic() < wait:
                    for frame in page.frames:
                        marker = frame.locator("#fuel-publication")
                        if marker.count():
                            loaded = marker.get_attribute("data-served-release")
                            identity = marker.get_attribute("data-snapshot-id")
                            status = marker.get_attribute("data-publication-state")
                            created = marker.get_attribute("data-served-at")
                            result.update(status=status, served_release=loaded, snapshot_id=identity)
                            forecast = frame.get_by_text("Predicted price", exact=True).count() > 0
                            observed = frame.get_by_text("Current recorded price", exact=True).count() > 0
                            if (loaded and identity and created and observed and forecast
                                    and ((loaded == expected["tag"] and identity == expected["identity"]) or
                                         (loaded == marker.get_attribute("data-latest-release") and
                                          datetime.fromisoformat(created) > datetime.fromisoformat(expected["created_at"])))):
                                result["status"] = "verified"
                                return result
                        elif frame.get_by_text("Yes, get this app back up!", exact=True).count():
                            result["status"] = "hosting_sleep"
                            return result
                        elif frame.get_by_text("Your app is in the oven", exact=True).count():
                            result["status"] = "hosting_startup"
                        elif frame.get_by_role("heading", name="Lebanon gasoline 95").count():
                            result["status"] = "app_snapshot_identity_unavailable"
                    page.wait_for_timeout(2000)
            except Error:
                continue
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("reports/operations/published_storage.json"))
    parser.add_argument("--seconds", type=int, default=220)
    args = parser.parse_args()
    content = args.manifest.read_bytes()
    expected = json.loads(content)
    expected["identity"] = sha256(content).hexdigest()
    result = inspect("https://fuelb95.streamlit.app/", expected, args.seconds)
    print(json.dumps(result))
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
