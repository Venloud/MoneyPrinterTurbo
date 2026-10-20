# Reconnect YouTube without uploading a video

The earlier upload failed with OAuth `invalid_grant`; no successful upload was established. The owner must sign in interactively to replace the refresh token.

1. Open the existing Google Cloud project used by the channel's OAuth client. If Google still restricts that project, resolve the restriction/appeal first; do not create another project to bypass it.
2. In Google Auth Platform, check the app's audience/publishing status. External apps left in **Testing** normally have seven-day refresh tokens for these scopes. Complete Google's applicable production/verification requirements before switching status.
3. Under Clients/Credentials, use the existing **Desktop app** OAuth client and download its client-secret JSON onto your own computer. Keep it out of Git and chat.
4. Install the GitHub CLI, sign in with access to `Venloud/MoneyPrinterTurbo`, and install `google-auth-oauthlib`. From your checkout run:

   ```bash
   python -m pip install google-auth-oauthlib
   gh auth login
   python kindled_iron/tools/connect_youtube.py /path/to/client_secret.json
   ```

   Sign in to the Google account that owns the intended Kindled Iron channel. With `gh` available, the helper saves `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` directly to repository secrets without printing their values. Do not run the helper without `gh`, because its fallback prints the secrets.
5. Run **Platform Connection Check** in GitHub Actions and confirm YouTube is OK and the intended channel is selected. This connection check is separate from a video upload. Keep publishing disabled until a particular finished video is approved.

No credentials or account configuration were changed by preparing these instructions.
