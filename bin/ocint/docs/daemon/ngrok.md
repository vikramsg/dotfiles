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

The account's public development domain is visible on the
[Domains page](https://dashboard.ngrok.com/domains). Do not write that domain in
tracked documentation. The commands below discover it from the running agent
and save it only in the ignored `.env` file.

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
private and never commit it. The package `.env` stores only the public URL.

## Start And Discover

Start the tunnel after the Slack ingress is listening on port `8733`:

```bash
ngrok http 8733
```

While ngrok is running, determine its public HTTPS URL from the local agent API:

```bash
curl --fail --silent http://127.0.0.1:4040/api/tunnels |
  jq -r '.tunnels[] | select(.proto == "https") | .public_url'
```

From `bin/ocint`, store that base URL in the ignored `.env` file:

```bash
OCINT_NGROK_URL="$(curl --fail --silent http://127.0.0.1:4040/api/tunnels |
  jq -r '.tunnels[] | select(.proto == "https") | .public_url')"
printf 'OCINT_NGROK_URL=%s\n' "$OCINT_NGROK_URL" > .env
```

The tracked `.env.example` documents the variable without recording the actual
domain. The Slack Events request URL is the base URL plus `/slack/events`:

```bash
set -a
. ./.env
set +a
printf '%s/slack/events\n' "$OCINT_NGROK_URL"
```

To request the same saved domain explicitly on a later run:

```bash
set -a
. ./.env
set +a
ngrok http 8733 --domain "${OCINT_NGROK_URL#https://}"
```

## Security

- Bind the Slack ingress to `127.0.0.1`.
- Expose only the Slack Events route through the ingress service.
- Verify every Slack request signature before accepting an event.
- Keep ports `8732`, `8733`, and `4040` closed in the GCP firewall.
- Keep `~/.config/ngrok/ngrok.yml` outside the repository.
