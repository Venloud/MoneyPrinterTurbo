#!/usr/bin/env python3
"""One-time TikTok OAuth connection helper for MoneyPrinterTurbo.

Uses the existing GitHub Pages callback registered in the user's TikTok app.
The browser handles authorization, the callback page displays the full callback
URL, and this script exchanges the one-time authorization code for tokens.

Registered redirect URI:
https://venloud.github.io/nightfiles/tiktok-callback.html
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

REDIRECT_URI = "https://venloud.github.io/nightfiles/tiktok-callback.html"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
DEFAULT_SCOPE = "user.info.basic,video.upload,video.publish"


def exchange_code(client_key: str, client_secret: str, code: str) -> dict:
    payload = urllib.parse.urlencode(
        {
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        }
    ).encode()

    request = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"TikTok token exchange failed: {detail}") from exc


def set_github_secret(name: str, value: str) -> bool:
    try:
        subprocess.run(
            ["gh", "secret", "set", name, "--body", value],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-key", default=os.getenv("TIKTOK_CLIENT_KEY"))
    parser.add_argument("--client-secret", default=os.getenv("TIKTOK_CLIENT_SECRET"))
    parser.add_argument("--scope", default=DEFAULT_SCOPE)
    parser.add_argument("--set-github-secrets", action="store_true")
    args = parser.parse_args()

    if not args.client_key or not args.client_secret:
        print(
            "Missing TikTok client key/secret. Pass --client-key and "
            "--client-secret, or set TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET.",
            file=sys.stderr,
        )
        return 2

    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode(
        {
            "client_key": args.client_key,
            "scope": args.scope,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "state": state,
        }
    )
    authorize_url = f"{AUTHORIZE_URL}?{query}"

    print("\nOpen this TikTok connection URL in your browser:\n")
    print(authorize_url)
    print("\nAfter authorization, the existing callback page will open.")
    print("Copy the FULL callback URL from the browser and paste it below.\n")

    try:
        webbrowser.open(authorize_url)
    except Exception:
        pass

    callback = input("Callback URL: ").strip()
    if not callback:
        print("No callback URL supplied.", file=sys.stderr)
        return 1

    parsed = urllib.parse.urlparse(callback)
    callback_base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if callback_base != REDIRECT_URI:
        print("Callback URL does not match the registered TikTok redirect URI.", file=sys.stderr)
        return 1

    params = urllib.parse.parse_qs(parsed.query)
    if params.get("state", [None])[0] != state:
        print("OAuth state mismatch. Refusing to continue.", file=sys.stderr)
        return 1

    error = params.get("error", [None])[0]
    if error:
        print(
            f"TikTok authorization failed: {error}: "
            f"{params.get('error_description', [''])[0]}",
            file=sys.stderr,
        )
        return 1

    code = params.get("code", [None])[0]
    if not code:
        print("Callback URL does not contain an authorization code.", file=sys.stderr)
        return 1

    tokens = exchange_code(args.client_key, args.client_secret, code)

    if tokens.get("error"):
        print(json.dumps(tokens, indent=2))
        return 1

    required = ("access_token", "refresh_token", "open_id")
    missing = [key for key in required if not tokens.get(key)]
    if missing:
        print(f"TikTok response is missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    print("\nTikTok OAuth succeeded.")
    print(f"open_id: {tokens['open_id']}")
    print(f"scopes: {tokens.get('scope', '')}")
    print(f"access token expires in: {tokens.get('expires_in')} seconds")
    print(f"refresh token expires in: {tokens.get('refresh_expires_in')} seconds")

    if args.set_github_secrets:
        values = {
            "TIKTOK_ACCESS_TOKEN": tokens["access_token"],
            "TIKTOK_REFRESH_TOKEN": tokens["refresh_token"],
            "TIKTOK_OPEN_ID": tokens["open_id"],
        }
        for name, value in values.items():
            if not set_github_secret(name, value):
                print(f"Could not set {name} with gh.", file=sys.stderr)
                return 1
        print("GitHub Actions TikTok secrets were updated.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
