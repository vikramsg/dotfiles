# ngrok For Slack Events

ngrok gives Slack a public HTTPS route to an ocint Slack Events endpoint on
the GCP VM. The tunnel makes an outbound connection, so the VM does not need an
inbound GCP firewall rule for the local service port.

```text
Slack -> public ngrok HTTPS URL -> 127.0.0.1:8733
```

Port `8733` is reserved here for the dedicated Slack ingress. Do not point the
tunnel at the daemon control API on port `8732`.

## Dashboard Walkthrough

Create an account or sign in at the [ngrok dashboard](https://dashboard.ngrok.com/).
The first-login product screen says **Select a product to get started**. Choose
**Share Localhost**, then select **Get started**. This is the product that puts a
local HTTP service behind a public HTTPS URL.

On the setup screen:

1. Select **Linux** as the operating system.
2. Follow the package installation section, or open the direct
   [Linux setup page](https://dashboard.ngrok.com/get-started/setup/linux).
3. Open **Getting Started > Your Authtoken**, or use the direct
   [authtoken page](https://dashboard.ngrok.com/get-started/your-authtoken).
4. Copy the `ngrok config add-authtoken` command shown for the account.

Reserve a static HTTPS domain on the account's
[Domains page](https://dashboard.ngrok.com/domains). Slack keeps one verified
Request URL, so a changing development URL is not suitable for the always-on
service. Keep the actual domain out of tracked documentation and store its base
URL only in the private daemon environment file.

## Install

The Linux setup page provides one multiline APT command. The following commands
are the same dashboard instructions split into separate steps, which avoids
shell line-continuation and trailing-whitespace errors.

Add ngrok's signing key:

```bash
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
```

```bash
echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | sudo tee /etc/apt/sources.list.d/ngrok.list
```

Update APT, install ngrok, and verify the installed version:

```bash
sudo apt-get update
sudo apt-get install ngrok
ngrok version
```

## Authenticate

The [authtoken page](https://dashboard.ngrok.com/get-started/your-authtoken)
shows both the credential and an account-specific setup command. Put the token
in the shell environment temporarily, then run the displayed command without
writing the token to this repository:

```bash
ngrok config add-authtoken "$NGROK_AUTHTOKEN"
ngrok config check
```

ngrok stores the credential in `~/.config/ngrok/ngrok.yml`. Keep that file
private and never commit it. Do not copy the authtoken into `daemon.env`; the
managed ngrok process reads its own isolated configuration.

## Configure The Static URL

Put the assigned static base URL, without `/slack/events`, in the user-owned
mode-0600 daemon environment file:

```bash
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
vi "$CONFIG_HOME/ocint/daemon.env"
# Set exactly one line:
# OCINT_NGROK_URL=https://YOUR_STATIC_NGROK_DOMAIN
chmod 600 "$CONFIG_HOME/ocint/daemon.env"
```

Keep exactly one non-empty `OCINT_NGROK_URL` assignment. LCH rejects a URL with
userinfo, a port, query, fragment, non-root path, localhost, or an IP address.
The Slack Events Request URL is that base plus `/slack/events`:

```bash
set -a
. "$CONFIG_HOME/ocint/daemon.env"
set +a
printf '%s/slack/events\n' "$OCINT_NGROK_URL"
```

Configure that URL in Slack Event Subscriptions and subscribe the bot to
`message.channels`. Slack verifies it with a signed challenge handled by the same
ingress route.

The separate **ocint E2E actor** app does not use this URL and has no event
subscription. During the explicit live test its User OAuth client posts one
marked root. Slack delivers an app-authored public-channel event containing the
authorized user plus actor `bot_id`, `app_id`, and exact `client_msg_id` through
this signed route. Test composition accepts only that exact probe. The xoxp
token stays in mode-0600
`live-e2e.env`, not the ngrok or daemon systemd environments.

## Managed Service

`ocint daemon lch setup` and `apply` render
`ocint-coordinator-ngrok.service`. Initial setup leaves it disabled; subsequent
apply preserves and reports its existing enablement. Explicitly disable it for
a pre-rollout live test. The service requires the coordinator and runs the
equivalent of:

```bash
ngrok http \
  --url="$OCINT_NGROK_URL" \
  --inspect=false \
  http://127.0.0.1:8733
```

For a manual connectivity check, first ensure the managed ngrok unit is stopped
and the coordinator ingress is listening, then use that command. Do not run a
second tunnel against the same static domain during the autonomous live harness
or production service.

After the explicit live E2E passes, start in receiver-first order:

```bash
systemctl --user enable --now ocint-coordinator.service
systemctl --user enable --now ocint-coordinator-ngrok.service
```

## Security

- Bind the Slack ingress to `127.0.0.1`.
- Expose only the Slack Events route through the ingress service.
- Verify every Slack request signature before accepting an event.
- Keep ports `8732`, `8733`, `4097`, `4098`, and `4040` closed in the GCP firewall.
- Keep `~/.config/ngrok/ngrok.yml` outside the repository.
- Keep Slack, GitHub, API, and SSH credentials out of the ngrok process.
- Preserve the static domain and daemon state across restart and rollback.
