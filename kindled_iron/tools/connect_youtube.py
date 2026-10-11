"""One-time, on YOUR computer (it opens a browser): a new YouTube refresh token for YOUTUBE_REFRESH_TOKEN.

    pip install google-auth-oauthlib
    python kindled_iron/tools/connect_youtube.py path/to/client_secret.json

client_secret.json = Google Cloud Console -> APIs & Services -> Credentials -> OAuth client ID (Desktop app),
same project as YOUTUBE_CLIENT_ID. Sign in with the Google account that owns the Kindled Iron channel.
FIRST set APIs & Services -> OAuth consent screen -> Publishing status to "In production": in "Testing"
Google kills the refresh token after 7 days (that is the 'invalid_grant' the publisher reports).
With the GitHub CLI (gh) logged in, the three secrets are written straight into Venloud/MoneyPrinterTurbo and
nothing is shown; without gh they are printed once for you to paste into the repo secrets (never into a chat).
"""
import json
import shutil
import subprocess
import sys

REPO = "Venloud/MoneyPrinterTurbo"


def main() -> int:
    from google_auth_oauthlib.flow import InstalledAppFlow
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], ["https://www.googleapis.com/auth/youtube.upload"])
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    info = json.load(open(sys.argv[1]))
    client = info.get("installed") or info.get("web") or {}
    values = {"YOUTUBE_CLIENT_ID": client.get("client_id"), "YOUTUBE_CLIENT_SECRET": client.get("client_secret"),
              "YOUTUBE_REFRESH_TOKEN": creds.refresh_token}
    if shutil.which("gh"):
        for name, value in values.items():
            subprocess.run(["gh", "secret", "set", name, "--repo", REPO, "--body", value], check=True)
            print(f"{name}: saved to {REPO}")
        print("Done. Run 'Platform Connection Check' to confirm YouTube: OK.")
    else:
        print("\nNo gh CLI: add these as repo secrets (Settings -> Secrets and variables -> Actions):\n")
        for name, value in values.items():
            print(f"{name} = {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
