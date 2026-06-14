# Stealth and Challenge Handling

Use this reference when browser automation is blocked, challenged, or visually diverges from the accessibility snapshot. Common cases include anti-bot interstitials, Cloudflare or Turnstile checks, CAPTCHA-like verification widgets, blank or partial pages, or controls that are visible in screenshots but absent from `playwright-cli snapshot`.

## When To Use This

- Cloudflare interstitials or challenge pages
- CAPTCHA-like or Turnstile widgets
- Bot-detection pages that behave differently in headless vs headed mode
- Pages where `snapshot` does not expose the visible control you need to interact with
- Pages that require visual verification before normal content loads
- Pages that partially load, loop during verification, or fall back after an apparent success

## Core Rule

Do not rely only on the accessibility snapshot or markdown output. Always save screenshots to `tmp` and read the screenshots before deciding whether the page is blocked or whether a click succeeded.

## Artifact Requirements

- Save each visual state to `tmp`
- Read each screenshot before acting on the next step
- Use `snapshot --boxes` to compare refs and coordinates
- Keep before-click, after-click, after-wait, and after-reload artifacts

## Required Workflow

1. Open the page and save an initial screenshot to `tmp`.
2. Save a snapshot with `--boxes` so you can compare refs and coordinates.
3. Read the screenshot image using the read tool.
4. If the widget is visible in the screenshot but missing from the snapshot, switch to mouse coordinates.
5. Save screenshots before click, after click, after wait, and after reload.
6. Read every saved screenshot before concluding success or failure.
7. If verification succeeds, reuse the same persistent profile for the rest of the session.

## Recommended Screenshot Sequence

```text
tmp/site-00-initial.png
tmp/site-01-after-wait.png
tmp/site-02-before-click.png
tmp/site-03-after-click.png
tmp/site-04-after-verification-wait.png
tmp/site-05-after-reload.png
```

## Recommended Attempt Order

1. Baseline `playwright-cli open`
2. Headed Chromium
3. Headed Chromium with a persistent profile
4. Config-driven Chromium with realistic viewport, locale, timezone, and profile
5. Raw Playwright persistent context if the CLI session is unreliable

## Visual-Only Controls

If the control is present in the screenshot but absent from `snapshot`, treat it as a visual target rather than a ref-driven target.

1. Save a screenshot.
2. Read the screenshot.
3. Estimate the coordinates from the image.
4. Use mouse actions rather than `click eNN`.
5. Save and read the post-click screenshot.

## Common Patterns

- A challenge checkbox may be visible in the screenshot while being absent from `playwright-cli snapshot`.
- Coordinate clicks can move the widget into a `Verifying...` state, but may still fall back to the checkbox.
- Headed Chromium with a persistent profile is a strong first escalation when baseline automation is challenged.
- Config changes like viewport, locale, timezone, and user agent can make runs more reproducible, but they do not guarantee that a challenge will pass.
- In Linux/Xvfb environments, Chromium may require `--no-sandbox` in the launch args.

## Headed CLI Examples

```bash
playwright-cli open --headed --browser=chromium "https://example.com"
playwright-cli screenshot --filename=tmp/site-00-initial.png
playwright-cli snapshot --boxes --filename=tmp/site-00-initial.yml
```

```bash
playwright-cli open --headed --browser=chromium --profile=tmp/site-profile "https://example.com"
```

### xvfb-run

**Note**: Headed usage may require running a display server.
Use `xvfb-run`. If its not available, stop and report to the user that headed runs cannot work without a display running.

## Coordinate Interaction

Use this only after reading the screenshot and confirming the control is visually present.

```bash
playwright-cli mousemove <x> <y>
playwright-cli mousedown
playwright-cli mouseup
playwright-cli screenshot --filename=tmp/site-03-after-click.png
```

Coordinates should come from the saved screenshot, not from guesswork.

## Config Example

```json
{
  "browser": {
    "browserName": "chromium",
    "userDataDir": "tmp/site-profile",
    "launchOptions": {
      "headless": false,
      "args": ["--window-size=1280,720", "--no-sandbox"]
    },
    "contextOptions": {
      "viewport": { "width": 1280, "height": 720 },
      "locale": "de-DE",
      "timezoneId": "Europe/Berlin",
      "userAgent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    }
  }
}
```

Then open with:

```bash
playwright-cli open --config=tmp/site-config.json "https://example.com"
```

## Config Knobs

Use these only as needed:

- `headless: false` for a visible browser
- `userDataDir` or `--profile` for persistence across reloads
- `viewport` for stable screenshot dimensions
- `locale` and `timezoneId` when the site is region-sensitive
- `userAgent` when you need reproducible browser identity
- `--no-sandbox` in Linux environments where Chromium sandboxing fails

## Raw Playwright Fallback

If `playwright-cli` does not keep a reliable session, use a raw Playwright persistent context and keep the same profile on disk.

```js
const context = await chromium.launchPersistentContext('tmp/site-profile', {
  headless: false,
  viewport: { width: 1280, height: 720 }
})
```

## Outcome Checklist

- If the page becomes interactive, keep the same profile and continue in that session.
- If the challenge loops, save the final screenshot and stop escalating blindly.
- If the widget falls back after `Verifying...`, treat that as a failed attempt and try the next escalation.
- If a browser fails to launch because of host dependencies, record that and fall back to Chromium.
