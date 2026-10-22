"""Download the Delhi static GTFS files from the Open Transit Data portal.

The portal asks for a name, email, usage type and purpose before each download,
and submitting the form accepts its terms: https://otd.delhi.gov.in/terms

Usage:
    set OTD_NAME=Your Name
    set OTD_EMAIL=you@example.com
    python scripts/download_static.py
"""

import os
import re
import sys
from pathlib import Path

import requests

BASE = "https://otd.delhi.gov.in"
OUT = Path(__file__).resolve().parent.parent / "data" / "raw"
SOURCES = {"bus": "/data/static/", "metro": "/data/staticDMRC/"}


def form_files(html):
    return sorted(set(re.findall(r"name='dataDownloaded' value='([^']+)'", html)))


def download(session, page, name, folder, details):
    url = BASE + page
    html = session.get(url, timeout=60).text
    token = re.search(r"name='csrfmiddlewaretoken' value='([^']+)'", html).group(1)
    form = {"csrfmiddlewaretoken": token, "dataDownloaded": name, **details}
    response = session.post(url, data=form, headers={"Referer": url}, timeout=300)
    response.raise_for_status()
    kind = response.headers.get("Content-Type", "")
    if "text/html" in kind:
        raise RuntimeError(f"{name}: portal returned a web page instead of a file")
    disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r'filename="?([^";]+)', disposition)
    path = folder / (match.group(1) if match else f"{name}.txt")
    path.write_bytes(response.content)
    return path


def main():
    name, email = os.environ.get("OTD_NAME"), os.environ.get("OTD_EMAIL")
    if not name or not email:
        sys.exit("Set OTD_NAME and OTD_EMAIL first.")
    details = {"usageType": "NonCommercial", "purpose": "R&D", "name": name, "email": email}
    session = requests.Session()
    session.headers["User-Agent"] = "delhi-bus-research/0.1"
    for label, page in SOURCES.items():
        folder = OUT / f"static_{label}"
        folder.mkdir(parents=True, exist_ok=True)
        files = form_files(session.get(BASE + page, timeout=60).text)
        print(f"{label}: {files}")
        for file in files:
            path = download(session, page, file, folder, details)
            print(f"  saved {path.name}: {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
