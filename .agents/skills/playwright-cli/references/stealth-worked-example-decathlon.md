# Decathlon.de Worked Example

This is a concrete, self-contained runbook for opening Decathlon.de backpacks, passing the Cloudflare challenge, and clicking through to a real product page in this environment.

## Goal

Open the Decathlon backpacks category page, pass the challenge if shown, reach the category grid, click a backpack-related product, and extract visible details from the product page.

## Target

- Category URL: `https://www.decathlon.de/alle-sportarten-a-z/wandern-trekking/rucksacke`
- Category success marker: `Outdoorrucksäcke`

## Environment Assumptions

- OS: Linux
- There may be no usable display server attached to the shell session
- Headed Chromium should therefore be run under `xvfb-run -a`
- Screenshots should be saved into `tmp`
- Screenshot images should be read with the `read` tool before deciding the next step
- `playwright-cli snapshot` alone is not enough for this site because the Cloudflare checkbox may be visible in the screenshot but missing from the snapshot

## Known-Good Browser Setup

Use Chromium with a persistent profile.

- Browser: Chromium
- Mode: headed
- Profile: persistent on disk
- Viewport: `1280x720`

Known-good raw Playwright context:

```js
const context = await chromium.launchPersistentContext(profileDir, {
  headless: false,
  viewport: { width: 1280, height: 720 },
})
```

If Chromium sandboxing fails in Linux, retry with:

```js
const context = await chromium.launchPersistentContext(profileDir, {
  headless: false,
  viewport: { width: 1280, height: 720 },
  args: ['--no-sandbox'],
})
```

## How The Profile Is Created

Use a fresh profile directory for a clean run:

```bash
PROFILE_DIR="/path/to/local/tmp/decathlon-profile-fresh-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$PROFILE_DIR"
```

Why persistence matters:

- the challenge, reload, and follow-up navigation should all happen in the same profile
- once the challenge advances, the same profile preserves cookies and session state across the reload that follows

## How It Was Run

The reliable path in this environment was raw Playwright under `xvfb-run`, not a pure `playwright-cli` session.

Exact invocation shape:

```bash
PROFILE_DIR="/path/to/local/tmp/decathlon-profile-fresh-$(date +%Y%m%d-%H%M%S)"
export PROFILE_DIR
xvfb-run -a node - <<'EOF'
const { chromium } = require('/<HOME>/.local/lib/node_modules/@playwright/cli/node_modules/playwright')

const profileDir = process.env.PROFILE_DIR
const categoryUrl = 'https://www.decathlon.de/alle-sportarten-a-z/wandern-trekking/rucksacke'

async function isChallenge(page) {
  const text = (await page.locator('body').innerText()).toLowerCase()
  return (
    text.includes('performing security verification') ||
    text.includes('sicherheitsüberprüfung') ||
    text.includes('verify you are human') ||
    text.includes('bestätigen sie, dass sie ein mensch sind') ||
    text.includes('just a moment') ||
    text.includes('nur einen moment')
  )
}

(async () => {
  const context = await chromium.launchPersistentContext(profileDir, {
    headless: false,
    viewport: { width: 1280, height: 720 },
  })
  const page = context.pages()[0] || await context.newPage()

  await page.goto(categoryUrl, { waitUntil: 'domcontentloaded', timeout: 90000 })

  if (await isChallenge(page)) {
    await page.waitForTimeout(20000)
    if (await isChallenge(page)) {
      await page.mouse.move(214, 336, { steps: 20 })
      await page.mouse.down()
      await page.mouse.up()
      await page.waitForTimeout(20000)
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 90000 })
    }
  }

  if (await isChallenge(page)) {
    throw new Error('Decathlon challenge still active after reload')
  }

  const productCard = page.locator('article').filter({ hasText: /rucksack/i }).first()
  await productCard.locator('a[href*="/p/"]').first().click()
  await page.waitForLoadState('domcontentloaded')
  await context.close()
})().catch((error) => {
  console.error(error)
  process.exit(1)
})
EOF
```

This uses the exact Playwright package path that worked in this environment and keeps the profile path explicit through `process.env.PROFILE_DIR`.

## Required Artifacts

Save these screenshots in `tmp`:

```text
tmp/decathlon-fresh-00-initial.png
tmp/decathlon-fresh-01-after-wait.png
tmp/decathlon-fresh-02-before-click.png
tmp/decathlon-fresh-03-after-click.png
tmp/decathlon-fresh-04-after-verification-wait.png
tmp/decathlon-fresh-05-after-reload.png
tmp/decathlon-fresh-06-category.png
tmp/decathlon-fresh-07-product.png
```

If a step is skipped because the page loads faster, still save the next meaningful state.

## Exact Workflow

1. Create a fresh persistent profile.
2. Launch headed Chromium under `xvfb-run -a` with viewport `1280x720`.
3. Open the category URL.
4. Save `00-initial` screenshot.
5. Read the screenshot.
6. If the category page loads immediately, skip challenge handling and continue to product selection.
7. If the Cloudflare challenge is shown, wait about 20 seconds and save `01-after-wait`.
8. Read the screenshot again.
9. If the checkbox is visible, save `02-before-click`, click it visually, save `03-after-click`, wait again, save `04-after-verification-wait`, then reload in the same persistent profile and save `05-after-reload`.
10. If the category page loads, save `06-category` and continue.
11. Select a product card whose text contains `rucksack` if possible.
12. Click the product link, wait for the product page, and save `07-product`.
13. Extract title, price, rating or review count, delivery text, and a short visible summary.

## Exact If/Else Logic

```text
Open the category URL.

If the category page loads immediately:
  Save the category screenshot.
  Accept cookies if shown.
  Click a product whose card text contains "rucksack".
  Save the product screenshot.
  Extract title, price, rating, delivery text, and summary.

Else if the Cloudflare challenge is shown:
  Save the initial challenge screenshot.
  Wait about 20s.
  Save the after-wait screenshot.

  If the checkbox is visible in the screenshot:
    Save the before-click screenshot.
    Click the checkbox visually.
    Save the after-click screenshot.
    Wait about 20s.
    Save the after-verification-wait screenshot.
    Reload in the same persistent profile.
    Save the after-reload screenshot.

    If the category page loads:
      Continue to product selection.
    Else if a skeleton or loading page appears:
      Treat that as progress, wait, reload in the same profile, then check again.
    Else:
      Save the final screenshot and stop.

  Else:
    Save the final screenshot and stop.

Else:
  Save the screenshot and report an unexpected page state.
```

## Challenge Handling Details

At `1280x720`, the Cloudflare checkbox was successfully clicked near:

- `x=214`
- `y=336`

Use these coordinates only if the screenshot layout matches the known challenge layout. If the box appears elsewhere, derive the coordinates from the current screenshot instead of hardcoding them blindly.

Known challenge progression on Decathlon:

1. Static challenge page with `Verify you are human`
2. Checkbox click
3. Intermediate loading or skeleton page may appear
4. Reload in the same profile
5. Category page becomes usable

## Product Selection Guidance

Do not click the first card blindly. Prefer a card whose visible text contains `rucksack`.

Known successful category click:

- Product: `QUECHUA Kühlrucksack 30 l isolierend und kompakt - 100`
- URL: `https://www.decathlon.de/p/kuhlrucksack-30-l-isolierend-und-kompakt-100/309970/c328m8913720`

## Known Successful Output

From a successful fresh-profile run:

- Product title: `Kühlrucksack 30 l isolierend und kompakt - 100`
- Price: `34,99 €`
- Reviews: `2.312 Bewertungen`
- Delivery: `Lieferung nach Hause`
- Visible summary: `Unsere Motivation? Einen bequemen, funktionellen Rucksack mit Kühlfunktion anzubieten, damit du deine Wanderungen voll genießen kannst! Volumen: 30 l.`

## Minimal Working Script

This is the known-good control flow that worked in this environment:

```js
const { chromium } = require('/<HOME>/.local/lib/node_modules/@playwright/cli/node_modules/playwright')

const profileDir = process.env.PROFILE_DIR
const categoryUrl = 'https://www.decathlon.de/alle-sportarten-a-z/wandern-trekking/rucksacke'

async function isChallenge(page) {
  const text = (await page.locator('body').innerText()).toLowerCase()
  return (
    text.includes('performing security verification') ||
    text.includes('sicherheitsüberprüfung') ||
    text.includes('verify you are human') ||
    text.includes('bestätigen sie, dass sie ein mensch sind') ||
    text.includes('just a moment') ||
    text.includes('nur einen moment')
  )
}

async function main() {
  const context = await chromium.launchPersistentContext(profileDir, {
    headless: false,
    viewport: { width: 1280, height: 720 },
  })

  const page = context.pages()[0] || await context.newPage()
  await page.goto(categoryUrl, { waitUntil: 'domcontentloaded', timeout: 90000 })

  if (await isChallenge(page)) {
    await page.waitForTimeout(20000)
    if (await isChallenge(page)) {
      await page.mouse.move(214, 336, { steps: 20 })
      await page.mouse.down()
      await page.mouse.up()
      await page.waitForTimeout(20000)
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 90000 })
    }
  }

  if (await isChallenge(page)) {
    throw new Error('Decathlon challenge still active after reload')
  }

  const productCard = page.locator('article').filter({ hasText: /rucksack/i }).first()
  await productCard.locator('a[href*="/p/"]').first().click()
  await page.waitForLoadState('domcontentloaded')
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
```

The exact import path above is the known-good one for this environment.

## Fallbacks

- If the challenge remains after reload, stop and report failure.
- If the checkbox is not visible in the screenshot, stop and report failure.
- If Chromium headed does not launch, retry under `xvfb-run -a`.
- If Chromium sandboxing fails, retry with `--no-sandbox`.
- If the category page loads but product click fails, save the category screenshot and report category-level details instead.

## What Worked

This site was successfully automated from a fresh profile with:

- `xvfb-run -a`
- headed Chromium
- persistent profile
- visual checkbox click
- reload in the same persistent profile

Old saved state was not required. A fresh profile also worked.
