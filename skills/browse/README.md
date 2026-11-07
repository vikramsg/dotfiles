# Browse Skill

This skill lets agents drive Chrome through [browse](https://opencode.ai/browse/install): a Chrome extension, a local relay on `127.0.0.1`, and a CLI/MCP server that runs Playwright against the paired browser.

`SKILL.md` is the output of `browse skill` with a restricted description; its front matter records where it came from.

## Installation

Install the browse binary and add its MCP server to OpenCode:

```sh
curl -fsSL https://opencode.ai/browse/install | bash
```

Link this skill from the repository root:

```sh
just opencode
```

## Use a dedicated Chrome profile

Pair browse with a separate Chrome profile so agents only see the tabs, cookies and logins you give them. Guest windows do not work because Chrome disables extensions in Guest mode.

1. In Chrome, click the profile icon, choose **Add**, and create a profile such as `Agent`.
2. When Chrome asks you to sign in, choose **Stay signed out**. Signing in to Chrome turns on sync, which copies passwords, history and extensions from your Google account into the profile.
3. Install the browse extension in the new profile from the [Chrome Web Store](https://chromewebstore.google.com/detail/mfnicocicmmlkpjnaffgihfjhdgjkdjg). Extensions are per profile, so the copy in your main profile does not carry over.
4. Run `browse pair` and enter the printed code in the extension's **Options** page in the new profile, then click **Pair**. The code is valid for 10 minutes.
5. The relay drives one profile at a time and does not let a second extension replace a healthy connection. Remove or disable the extension in your main profile, and unpair it:

   ```sh
   browse pair --list
   browse pair --revoke <browser>
   ```

6. Confirm the agent profile is connected:

   ```sh
   browse status
   ```

Log in to websites inside the agent profile as needed. Using the same email as your main profile is fine because each profile keeps its own cookies and sessions.

## Updating

browse updates itself, but this copy of the skill does not. To refresh it, run `browse skill > skills/browse/SKILL.md`, then restore the restricted description and the `metadata` block.
