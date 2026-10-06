"""Post one APPROVED Kindled Iron render to TikTok, YouTube Shorts, Instagram Reels, Threads and Facebook Reels.

Only .github/workflows/kindled_iron_publish.yml runs this (the test workflow never publishes). It refuses a
render that used the fallback voice or failed a check, checks each platform's credentials first, never
posts to a platform whose check fails, and one platform failing never stops the others.

    python -m kindled_iron.publish --video v.mp4 --meta v.meta.json --post v.post.txt [--public-url URL]
    python -m kindled_iron.publish --refresh-only          # refresh tokens + expiry alerts (weekly)

Secrets (env): TIKTOK_CLIENT_KEY/_SECRET/_ACCESS_TOKEN/_REFRESH_TOKEN/_OPEN_ID, YOUTUBE_CLIENT_ID/_SECRET/
_REFRESH_TOKEN, INSTAGRAM_ACCESS_TOKEN, THREADS_ACCESS_TOKEN, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN,
GH_SECRETS_WRITE_TOKEN (to save refreshed tokens), NTFY_TOPIC. Nothing is ever printed.
Config: kindled_iron/publish_config.json (publish_mode per platform: live | draft | off).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "publish_config.json").read_text())
GRAPH_V = CONFIG.get("graph_version", "v23.0")


def log(msg: str) -> None:
    print(f"[publish] {msg}", flush=True)


class Fail(Exception):
    pass


def http(url: str, method: str = "GET", data=None, headers: dict | None = None, form: dict | None = None,
         timeout: int = 120) -> dict:
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers = {**(headers or {}), "Content-Type": "application/x-www-form-urlencoded"}
    elif isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
        headers = {**(headers or {}), "Content-Type": "application/json; charset=UTF-8"}
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            out = json.loads(body) if body.strip().startswith(("{", "[")) else {"_body": body[:300]}
            if isinstance(out, dict):
                out["_headers"] = dict(r.headers)
            return out
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body)
            detail = detail.get("error", detail)
        except ValueError:
            detail = body[:300]
        raise Fail(f"HTTP {e.code}: {json.dumps(detail)[:400] if not isinstance(detail, str) else detail}") from None
    except Exception as e:  # noqa: BLE001
        raise Fail(f"{type(e).__name__}: {str(e)[:200]}") from None


def env(*names: str) -> list[str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise Fail(f"secret(s) missing: {', '.join(missing)}")
    return [os.environ[n] for n in names]


def save_secret(name: str, value: str) -> bool:
    """Refreshed tokens go straight back into the repo's Actions secrets (GH_SECRETS_WRITE_TOKEN)."""
    os.environ[name] = value
    tok, repo = os.environ.get("GH_SECRETS_WRITE_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not tok or not repo:
        log(f"WARNING: {name} refreshed but not saved (no GH_SECRETS_WRITE_TOKEN): this run only")
        return False
    r = subprocess.run(["gh", "secret", "set", name, "--repo", repo, "--body", value],
                       env={**os.environ, "GH_TOKEN": tok}, capture_output=True, text=True)
    if r.returncode:
        log(f"WARNING: could not save {name}: {r.stderr.strip()[:160]}")
        return False
    log(f"{name} refreshed and saved")
    return True


# ------------------------------------------------------------------ post text
def read_post(path: Path) -> dict:
    """<video>.post.txt: 'key: value' lines (title, caption, threads, description); continuation lines join."""
    post, key = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        head = line.split(":", 1)[0].strip().lower()
        if ":" in line and head in ("title", "caption", "threads", "description", "hashtags"):
            key = head
            post[key] = line.split(":", 1)[1].strip()
        elif key and line.strip():
            post[key] += "\n" + line.strip()
    post.setdefault("title", "Kindled Iron")
    post.setdefault("caption", post["title"])
    if not post.get("threads"):
        first = post["caption"].split("\n")[0]
        tags = [w for w in post["caption"].split() if w.startswith("#")][:2]
        post["threads"] = (first.split(" #")[0] + " " + " ".join(tags)).strip()
    return post


def gate(meta: dict) -> None:
    """Never post a render that used the fallback voice or failed a check."""
    v = meta.get("voice", {})
    problems = []
    if v.get("fallback") or v.get("provider_used") not in ("elevenlabs",):
        problems.append(f"voice is {v.get('provider_used')} (fallback voice)")
    if any(not r.get("ok") for r in meta.get("verse_check", [])) or not meta.get("verse_check"):
        problems.append("scripture check failed or missing")
    a = meta.get("audio", {})
    if a.get("true_peak") is None or a["true_peak"] > -1.0 or a.get("lf_burst", 99) > 10:
        problems.append(f"audio check failed or missing ({a})")
    if meta.get("checks_failed"):
        problems.append(f"failed checks: {meta['checks_failed']}")
    if problems:
        raise SystemExit("REFUSED: " + "; ".join(problems))


# ------------------------------------------------------------------ TikTok
TT = "https://open.tiktokapis.com/v2"


def tiktok_refresh() -> dict:
    key, secret, refresh = env("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")
    d = http(f"{TT}/oauth/token/", "POST", form={"client_key": key, "client_secret": secret,
                                                 "grant_type": "refresh_token", "refresh_token": refresh})
    if not d.get("access_token"):
        raise Fail(f"TikTok token refresh failed: {d.get('error_description') or d.get('error') or d}")
    save_secret("TIKTOK_ACCESS_TOKEN", d["access_token"])
    if d.get("refresh_token") and d["refresh_token"] != refresh:
        save_secret("TIKTOK_REFRESH_TOKEN", d["refresh_token"])
    return {"refresh_expires_days": round(int(d.get("refresh_expires_in", 0)) / 86400, 1), "scope": d.get("scope", "")}


def tiktok_check() -> dict:
    info = tiktok_refresh()
    tok, = env("TIKTOK_ACCESS_TOKEN")
    d = http(f"{TT}/post/publish/creator_info/query/", "POST", data={}, headers={"Authorization": f"Bearer {tok}"})
    if d.get("error", {}).get("code") not in (None, "ok"):
        raise Fail(f"TikTok creator info: {d['error']}")
    info.update(d.get("data", {}))
    return info


def tiktok_post(video: Path, post: dict, mode: str, chk: dict) -> dict:
    tok, = env("TIKTOK_ACCESS_TOKEN")
    size = video.stat().st_size
    src = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}
    h = {"Authorization": f"Bearer {tok}"}
    used, note = "draft", ""
    init = None
    if mode == "live" and "video.publish" in chk.get("scope", ""):
        levels = chk.get("privacy_level_options") or []
        level = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in levels else (levels[0] if levels else "SELF_ONLY")
        try:
            init = http(f"{TT}/post/publish/video/init/", "POST", headers=h, data={
                "post_info": {"title": post["caption"][:2200], "privacy_level": level, "disable_duet": False,
                              "disable_comment": False, "disable_stitch": False, "video_cover_timestamp_ms": 1000},
                "source_info": src})
            if init.get("error", {}).get("code") not in (None, "ok"):
                raise Fail(str(init["error"]))
            used = "direct post" + ("" if level == "PUBLIC_TO_EVERYONE" else f" ({level}: the app is not audited for public posts)")
        except Fail as e:
            note = f"direct post refused ({str(e)[:160]}); sent to drafts instead"
            init = None
    elif mode == "live":
        note = "the app has no video.publish scope (direct post not allowed): sent to drafts"
    if init is None:
        init = http(f"{TT}/post/publish/inbox/video/init/", "POST", headers=h, data={"source_info": src})
        if init.get("error", {}).get("code") not in (None, "ok"):
            raise Fail(f"TikTok draft init: {init['error']}")
        used = "draft (TikTok inbox: open TikTok to finish the post)"
    data = init["data"]
    req = urllib.request.Request(data["upload_url"], data=video.read_bytes(), method="PUT",
                                 headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                                          "Content-Range": f"bytes 0-{size - 1}/{size}"})
    with urllib.request.urlopen(req, timeout=600):
        pass
    status = ""
    for _ in range(30):
        st = http(f"{TT}/post/publish/status/fetch/", "POST", headers=h, data={"publish_id": data["publish_id"]})
        status = st.get("data", {}).get("status", "")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"):
            break
        time.sleep(5)
    if status == "FAILED":
        raise Fail(f"TikTok processing failed: {st.get('data', {}).get('fail_reason')}")
    user = chk.get("creator_username", "")
    return {"mode": used, "id": data["publish_id"], "status": status, "note": note,
            "url": f"https://www.tiktok.com/@{user}" if user else ""}


# ------------------------------------------------------------------ YouTube
def youtube_token() -> str:
    cid, sec, ref = env("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    d = http("https://oauth2.googleapis.com/token", "POST",
             form={"client_id": cid, "client_secret": sec, "refresh_token": ref, "grant_type": "refresh_token"})
    if "youtube.upload" not in d.get("scope", "") and "youtube" not in d.get("scope", ""):
        raise Fail("refresh token does not grant youtube.upload")
    return d["access_token"]


def youtube_check() -> dict:
    tok = youtube_token()
    d = http("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true", headers={"Authorization": f"Bearer {tok}"})
    items = d.get("items") or []
    return {"channel": items[0]["snippet"]["title"] if items else "?"}


def youtube_post(video: Path, post: dict, mode: str, chk: dict) -> dict:
    tok = youtube_token()
    title = post["title"][:90]
    if "#shorts" not in title.lower():
        title = (title + " #Shorts")[:100]
    privacy = "public" if mode == "live" else "private"
    body = {"snippet": {"title": title, "description": (post["caption"] + "\n\n" + post.get("description", "")).strip()[:4900],
                        "tags": [w.strip("#") for w in post["caption"].split() if w.startswith("#")][:15],
                        "categoryId": str(CONFIG.get("youtube_category", "27"))},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}
    init = http("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status", "POST",
                data=body, headers={"Authorization": f"Bearer {tok}", "X-Upload-Content-Type": "video/mp4",
                                    "X-Upload-Content-Length": str(video.stat().st_size)})
    loc = init["_headers"].get("Location") or init["_headers"].get("location")
    req = urllib.request.Request(loc, data=video.read_bytes(), method="PUT",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4"})
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read().decode())
    return {"mode": f"{privacy} Short, not made for kids", "id": d["id"], "url": f"https://youtube.com/shorts/{d['id']}"}


# ------------------------------------------------------------------ Instagram (Instagram Login API)
IG = f"https://graph.instagram.com/{GRAPH_V}"


def instagram_check() -> dict:
    tok, = env("INSTAGRAM_ACCESS_TOKEN")
    d = http(f"{IG}/me?fields=user_id,username", headers={"Authorization": f"Bearer {tok}"})
    return {"id": d.get("user_id") or d.get("id"), "username": d.get("username")}


def _wait_container(url: str, tok: str, field: str = "status_code") -> None:
    for _ in range(60):
        d = http(f"{url}?fields={field}", headers={"Authorization": f"Bearer {tok}"})
        st = d.get(field) or d.get("status")
        if st in ("FINISHED", "PUBLISHED"):
            return
        if st in ("ERROR", "EXPIRED"):
            raise Fail(f"processing {st}: {d}")
        time.sleep(5)
    raise Fail("processing timed out")


def instagram_post(video: Path, post: dict, mode: str, chk: dict, public_url: str | None) -> dict:
    tok, = env("INSTAGRAM_ACCESS_TOKEN")
    h = {"Authorization": f"Bearer {tok}"}
    uid = chk["id"]
    try:      # resumable upload: the bytes go straight to Instagram, no public URL needed
        c = http(f"{IG}/{uid}/media", "POST", headers=h, form={"media_type": "REELS", "upload_type": "resumable",
                                                               "caption": post["caption"], "share_to_feed": "true"})
        size = video.stat().st_size
        req = urllib.request.Request(f"https://rupload.facebook.com/ig-api-upload/{GRAPH_V}/{c['id']}", data=video.read_bytes(),
                                     method="POST", headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)})
        with urllib.request.urlopen(req, timeout=600):
            pass
        how = "resumable upload"
    except Exception as e:  # noqa: BLE001
        if not public_url:
            raise Fail(f"resumable upload failed ({str(e)[:160]}) and no public URL")
        c = http(f"{IG}/{uid}/media", "POST", headers=h, form={"media_type": "REELS", "video_url": public_url,
                                                               "caption": post["caption"], "share_to_feed": "true"})
        how = "temporary public URL"
    _wait_container(f"{IG}/{c['id']}", tok)
    p = http(f"{IG}/{uid}/media_publish", "POST", headers=h, form={"creation_id": c["id"]})
    link = http(f"{IG}/{p['id']}?fields=permalink", headers=h).get("permalink", "")
    return {"mode": f"live Reel ({how})", "id": p["id"], "url": link}


# ------------------------------------------------------------------ Threads
TH = "https://graph.threads.net/v1.0"


def threads_check() -> dict:
    tok, = env("THREADS_ACCESS_TOKEN")
    d = http(f"{TH}/me?fields=id,username", headers={"Authorization": f"Bearer {tok}"})
    return {"id": d.get("id"), "username": d.get("username")}


def threads_post(video: Path, post: dict, mode: str, chk: dict, public_url: str | None) -> dict:
    if not public_url:
        raise Fail("Threads needs a public video URL (none was made)")
    tok, = env("THREADS_ACCESS_TOKEN")
    h = {"Authorization": f"Bearer {tok}"}
    c = http(f"{TH}/me/threads", "POST", headers=h, form={"media_type": "VIDEO", "video_url": public_url, "text": post["threads"][:500]})
    _wait_container(f"{TH}/{c['id']}", tok, "status")
    p = http(f"{TH}/me/threads_publish", "POST", headers=h, form={"creation_id": c["id"]})
    link = http(f"{TH}/{p['id']}?fields=permalink", headers=h).get("permalink", "")
    return {"mode": "live post (video fetched from a temporary public URL)", "id": p["id"], "url": link}


# ------------------------------------------------------------------ Facebook Page Reels
FB = f"https://graph.facebook.com/{GRAPH_V}"


def facebook_check() -> dict:
    pid, tok = env("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_ACCESS_TOKEN")
    d = http(f"{FB}/{urllib.parse.quote(pid)}?fields=id,name", headers={"Authorization": f"Bearer {tok}"})
    return {"id": d.get("id"), "name": d.get("name")}


def facebook_post(video: Path, post: dict, mode: str, chk: dict) -> dict:
    pid, tok = env("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_ACCESS_TOKEN")
    h = {"Authorization": f"Bearer {tok}"}
    s = http(f"{FB}/{pid}/video_reels", "POST", headers=h, form={"upload_phase": "start"})
    size = video.stat().st_size
    req = urllib.request.Request(f"https://rupload.facebook.com/video-upload/{GRAPH_V}/{s['video_id']}", data=video.read_bytes(),
                                 method="POST", headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)})
    with urllib.request.urlopen(req, timeout=600):
        pass
    state = "PUBLISHED" if mode == "live" else "DRAFT"
    http(f"{FB}/{pid}/video_reels", "POST", headers=h, form={"upload_phase": "finish", "video_id": s["video_id"],
                                                             "video_state": state, "description": post["caption"]})
    return {"mode": f"Page Reel ({state.lower()})", "id": s["video_id"], "url": f"https://www.facebook.com/reel/{s['video_id']}"}


PLATFORMS = {
    "tiktok": (tiktok_check, lambda v, p, m, c, u: tiktok_post(v, p, m, c)),
    "youtube": (youtube_check, lambda v, p, m, c, u: youtube_post(v, p, m, c)),
    "instagram": (instagram_check, instagram_post),
    "threads": (threads_check, threads_post),
    "facebook": (facebook_check, lambda v, p, m, c, u: facebook_post(v, p, m, c)),
}


# ------------------------------------------------------------------ token upkeep
def refresh_tokens() -> list[str]:
    """Refresh what can be refreshed; return alerts for anything close to expiring or already dead."""
    alerts, warn = [], int(CONFIG.get("token_warn_days", 7))
    try:
        info = tiktok_refresh()
        if info["refresh_expires_days"] and info["refresh_expires_days"] < max(warn, 14):
            alerts.append(f"TikTok refresh token expires in {info['refresh_expires_days']} days: run TikTok OAuth Connect")
    except Fail as e:
        alerts.append(f"TikTok: {e} (run TikTok OAuth Connect)")
    for name, url, grant in (("INSTAGRAM_ACCESS_TOKEN", "https://graph.instagram.com/refresh_access_token", "ig_refresh_token"),
                             ("THREADS_ACCESS_TOKEN", "https://graph.threads.net/refresh_access_token", "th_refresh_token")):
        tok = os.environ.get(name)
        if not tok:
            alerts.append(f"{name} missing")
            continue
        try:
            d = http(f"{url}?grant_type={grant}&access_token={urllib.parse.quote(tok)}")
            if d.get("access_token"):
                save_secret(name, d["access_token"])
                days = int(d.get("expires_in", 0)) / 86400
                if days and days < warn:
                    alerts.append(f"{name} expires in {days:.0f} days")
        except Fail as e:
            alerts.append(f"{name} could not be refreshed: {e}")
    tok, pid = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN"), os.environ.get("FACEBOOK_PAGE_ID")
    if tok:
        try:
            d = http(f"{FB}/debug_token?input_token={urllib.parse.quote(tok)}", headers={"Authorization": f"Bearer {tok}"})
            exp = int(d.get("data", {}).get("expires_at") or 0)
            if exp and exp - time.time() < warn * 86400:
                alerts.append(f"FACEBOOK_PAGE_ACCESS_TOKEN expires {time.strftime('%Y-%m-%d', time.gmtime(exp))}: "
                              "make a never-expiring Page token from a long-lived user token")
        except Fail as e:
            alerts.append(f"FACEBOOK_PAGE_ACCESS_TOKEN: {e}")
    return alerts


def ntfy(title: str, body: str, click: str = "") -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        log("NTFY_TOPIC not set: no phone alert")
        return
    h = {"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Tags": "outbox_tray"}
    if click:
        h["Click"] = click
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode(), method="POST", headers=h), timeout=20)
    except Exception as e:  # noqa: BLE001
        log(f"ntfy failed: {type(e).__name__}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video")
    ap.add_argument("--meta")
    ap.add_argument("--post")
    ap.add_argument("--public-url", default=None, help="short-lived public URL of the same MP4 (Threads, Instagram fallback)")
    ap.add_argument("--only", default="", help="comma list of platforms (default: all with publish_mode live|draft)")
    ap.add_argument("--check-only", action="store_true", help="check every platform, post nothing")
    ap.add_argument("--refresh-only", action="store_true")
    ap.add_argument("--out", default="publish_results.json")
    a = ap.parse_args()

    if a.refresh_only:
        alerts = refresh_tokens()
        for x in alerts:
            log(f"ALERT: {x}")
        if alerts:
            ntfy("Kindled Iron: tokens need attention", "\n".join(alerts))
        Path(a.out).write_text(json.dumps({"alerts": alerts}, indent=1))
        return

    modes = CONFIG["publish_mode"]
    wanted = [p for p in (a.only.split(",") if a.only else PLATFORMS) if p and modes.get(p, "off") != "off"]
    video = Path(a.video) if a.video else None
    meta = json.loads(Path(a.meta).read_text()) if a.meta else {}
    post = read_post(Path(a.post)) if a.post else {}
    if not a.check_only:
        gate(meta)
        log(f"render passed the gate: voice {meta['voice'].get('provider_used')}, verses OK, "
            f"true peak {meta['audio']['true_peak']:.1f} dBTP")
    results = []
    for name in wanted:
        check, poster = PLATFORMS[name]
        r = {"platform": name, "publish_mode": modes[name]}
        try:
            chk = check()
            r["check"] = "OK"
            log(f"{name}: connection OK ({', '.join(f'{k}={v}' for k, v in chk.items() if k in ('username', 'creator_username', 'channel', 'name'))})")
        except Fail as e:
            r.update({"check": "FAILED", "ok": False, "error": str(e)})
            log(f"{name}: connection FAILED: {e} -> not posting there")
            results.append(r)
            continue
        if a.check_only:
            r["ok"] = True
            results.append(r)
            continue
        try:
            r.update(poster(video, post, modes[name], chk, a.public_url))
            r["ok"] = True
            log(f"{name}: posted ({r['mode']}) {r.get('url', '')} {r.get('note', '')}")
        except Exception as e:  # noqa: BLE001 - one platform failing never stops the others
            r.update({"ok": False, "error": str(e)[:300]})
            log(f"{name}: post FAILED: {str(e)[:300]}")
        results.append(r)
    Path(a.out).write_text(json.dumps(results, indent=1))
    lines = [f"{r['platform']}: " + (("OK " + r.get("mode", "") + " " + r.get("url", "")) if r.get("ok") else ("FAILED " + r.get("error", "")[:140]))
             for r in results]
    title = ("Kindled Iron connection check" if a.check_only else f"Kindled Iron posted: {post.get('title', '')}")
    ntfy(title, "\n".join(lines), next((r.get("url") for r in results if r.get("url")), ""))
    if not any(r.get("ok") for r in results):
        raise SystemExit("nothing was posted" if not a.check_only else "no platform passed the check")


if __name__ == "__main__":
    main()
