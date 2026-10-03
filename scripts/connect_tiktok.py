#!/usr/bin/env python3
"""One-time TikTok OAuth connection helper for MoneyPrinterTurbo.

Uses TikTok Login Kit desktop OAuth with PKCE, captures the localhost callback,
exchanges the authorization code for access/refresh tokens, and optionally
stores the tokens as GitHub Actions repository secrets through the GitHub CLI.

Run from the repository root:
    python scripts/connect_tiktok.py --client-key YOUR_KEY --client-secret YOUR_SECRET

The TikTok app must have this redirect URI registered:
    http://localhost:8765/callback/
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser


DEFAULT_REDIRECT_URI = "http://localhost:8765/callback/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"


def pkce_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()


def pkce_challenge(verifier: str) -> str:
    # TikTok's desktop Login Kit currently specifies SHA256 hex encoding.
    return hashlib.sha256(verifier.encode()).hexdigest()


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict[str, str] = {}

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback/":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        CallbackHandler.result = {
            key: values[0] for key, values in params.items() if values
        }

        body = (
            "<html><body style='font-family:sans-serif'>"
            "<h2>TikTok authorization received.</h2>"
            "<p>You can close this window and return to the terminal.</p>"
            "</body></html>"
        ).encode()

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, _format: str, *_args) -> None:
        pass


def exchange_code(
    client_key: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    verifier: str,
) -> dict:
    payload = urllib.parse.urlencode(
        {
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
    ).encode()

    request = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-cache",
        },
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
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    parser.add_argument(
        "--scope",
        default="user.info.basic,video.publish,video.upload",
        help="Comma-separated TikTok scopes.",
    )
    parser.add_argument(
        "--set-github-secrets",
        action="store_true",
        help="Store the returned tokens as repository Actions secrets using gh.",
    )
    args = parser.parse_args()

    if not args.client_key or not args.client_secret:
        print(
            "Missing TikTok client key/secret. Pass --client-key and "
            "--client-secret, or set TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET.",
            file=sys.stderr,
        )
        return 2

    parsed_redirect = urllib.parse.urlparse(args.redirect_uri)
    if parsed_redirect.hostname not in {"localhost", "127.0.0.1"}:
        print("This helper requires a localhost/127.0.0.1 redirect URI.", file=sys.stderr)
        return 2

    verifier = pkce_verifier()
    challenge = pkce_challenge(verifier)
    state = secrets.token_urlsafe(24)

    query = urllib.parse.urlencode(
        {
            "client_key": args.client_key,
            "response_type": "code",
            "scope": args.scope,
            "redirect_uri": args.redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    authorize_url = f"{AUTHORIZE_URL}?{query}"

    callback_url = urllib.parse.urlparse(args.redirect_uri)
    server = http.server.ThreadingHTTPServer(
        (callback_url.hostname or "127.0.0.1", callback_url.port or 8765),
        CallbackHandler,
    )

    print("Opening TikTok authorization in your browser...")
    print(authorize_url)
    webbrowser.open(authorize_url)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    server_thread.join(timeout=300)
    server.server_close()

    result = CallbackHandler.result
    if not result:
        print("Timed out waiting for the TikTok callback.", file=sys.stderr)
        return 1

    if result.get("state") != state:
        print("OAuth state mismatch. Refusing to continue.", file=sys.stderr)
        return 1

    if result.get("error"):
        print(
            f"TikTok authorization failed: {result.get('error')}: "
            f"{result.get('error_description', '')}",
            file=sys.stderr,
        )
        return 1

    code = result.get("code")
    if not code:
        print("TikTok callback did not contain an authorization code.", file=sys.stderr)
        return 1

    tokens = exchange_code(
        args.client_key,
        args.client_secret,
        code,
        args.redirect_uri,
        verifier,
    )

    if tokens.get("error"):
        print(json.dumps(tokens, indent=2))
        return 1

    required = ("access_token", "refresh_token", "open_id")
    missing = [key for key in required if not tokens.get(key)]
    if missing:
        print(f"TikTok response is missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    print("TikTok OAuth succeeded.")
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
                print(
                    f"Could not set {name} with gh. Run: gh secret set {name}",
                    file=sys.stderr,
                )
                return 1
        print("GitHub Actions TikTok secrets were updated.")
    else:
        print(
            "Tokens were not printed. Re-run with --set-github-secrets "
            "after authenticating GitHub CLI if you want them stored in Actions."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
