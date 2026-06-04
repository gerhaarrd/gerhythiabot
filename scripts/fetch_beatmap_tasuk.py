"""Fetch beatmap 12974 from Rhythia production API and search for "tasuk".

Usage:
    python scripts/fetch_beatmap_tasuk.py

Requires `requests` (in requirements.txt).
"""
import requests
import sys
import json

API_URL = "https://rhythia.com/api/beatmaps/12974"

def fetch():
    # Send an empty session cookie as requested
    headers = {
        "User-Agent": "rhythia-fetch-script/1.0",
    }
    cookies = {"session": ""}
    resp = requests.get(API_URL, headers=headers, cookies=cookies, timeout=15)
    resp.raise_for_status()
    return resp.json()


def search_for_tasuk(obj):
    matches = []
    text = json.dumps(obj, ensure_ascii=False).lower()
    if "tasuk" in text:
        matches.append("Found 'tasuk' substring in JSON dump")

    # Also look for specific fields that may contain difficulty or title
    for key in ("title", "diffName", "difficulty", "beatmapDifficulty", "version", "songName"):
        v = obj.get(key)
        if v and isinstance(v, str) and "tasuk" in v.lower():
            matches.append(f"Field '{key}' contains tasuk: {v}")

    # Nested scan: common nested fields
    def recurse(o, path=""):
        if isinstance(o, dict):
            for k, val in o.items():
                recurse(val, f"{path}.{k}" if path else k)
        elif isinstance(o, list):
            for i, item in enumerate(o):
                recurse(item, f"{path}[{i}]")
        elif isinstance(o, str):
            if "tasuk" in o.lower():
                matches.append(f"{path}: {o}")

    recurse(obj)
    return matches


if __name__ == "__main__":
    try:
        data = fetch()
    except Exception as e:
        print("Failed to fetch beatmap:", e, file=sys.stderr)
        sys.exit(2)

    found = search_for_tasuk(data)
    if not found:
        print("No occurrences of 'tasuk' found in beatmap 12974.")
    else:
        print("Matches:")
        for m in found:
            print("- ", m)

    # Optionally, print the full JSON if user passed --dump
    if "--dump" in sys.argv:
        print(json.dumps(data, ensure_ascii=False, indent=2))
