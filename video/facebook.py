"""Publish a video as a Reel on a Facebook Page (Graph API, Reels publishing)."""
import os
import time

import requests

GRAPH = "https://graph.facebook.com/v25.0"
RUPLOAD = "https://rupload.facebook.com/video-upload/v25.0"


class FacebookError(RuntimeError):
    pass


def _check(r):
    try:
        data = r.json()
    except ValueError:
        raise FacebookError(f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        raise FacebookError(f"{err.get('message', r.text[:300])} (code {err.get('code')})")
    return data


def page_id(token):
    return _check(requests.get(f"{GRAPH}/me", params={"fields": "id,name", "access_token": token}, timeout=30))


def publish_reel(token, video_path, description):
    page = page_id(token)
    pid = page["id"]

    start = _check(requests.post(f"{GRAPH}/{pid}/video_reels",
                                 data={"upload_phase": "start", "access_token": token}, timeout=60))
    video_id = start["video_id"]

    size = os.path.getsize(video_path)
    with open(video_path, "rb") as fh:
        up = _check(requests.post(f"{RUPLOAD}/{video_id}", data=fh, timeout=600, headers={
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(size),
            "Content-Type": "application/octet-stream",
        }))
    if not up.get("success"):
        raise FacebookError(f"upload did not succeed: {up}")

    fin = _check(requests.post(f"{GRAPH}/{pid}/video_reels", timeout=60, data={
        "access_token": token,
        "video_id": video_id,
        "upload_phase": "finish",
        "video_state": "PUBLISHED",
        "description": description,
    }))
    if not fin.get("success"):
        raise FacebookError(f"publish did not succeed: {fin}")

    # Wait (up to ~5 min) for Facebook to finish processing, and surface any processing error.
    status = {}
    for _ in range(30):
        time.sleep(10)
        status = _check(requests.get(f"{GRAPH}/{video_id}",
                                     params={"fields": "status", "access_token": token}, timeout=30)).get("status", {})
        proc = status.get("processing_phase", {})
        if proc.get("status") == "error":
            raise FacebookError(f"processing error: {proc.get('errors') or proc}")
        if status.get("video_status") in ("ready", "published") or \
                status.get("publishing_phase", {}).get("status") == "complete":
            break
    return {"page": page.get("name"), "video_id": video_id, "status": status.get("video_status")}
