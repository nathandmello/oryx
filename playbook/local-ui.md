# Use PM Hub in a browser

Open the Hub on the computer that holds the private workspace.
Use the [shared command menu](commands.md) to start the app:

```text
/pm workspace browser open
```

The app opens to Roadmap by default. Add `--screen tasks` or `--screen launch-checklists` to start there.
From a terminal, run the same action:

```sh
python3 tools/pm.py action workspace browser open
```

Set the [allowed signers file](initiative-approvals.md) to read signed registers.
For roadmap approval, install Python with Tk support and use the PM signing key.
For a protected key, load it in your OpenSSH agent before launch. Pass the absolute path to its public key:

```sh
python3 tools/pm.py action workspace browser open --key "$PM_SIGNING_KEY_PATH"
```

Start the app as the PM account when using a separate agent account. Use the local window to confirm the proposal.
The app opens a browser tab on the same computer. Keep the launch session active during use.
Share the browser tab for a meeting. Keep the launch URL private.

## Roadmap

Choose a product and planning cycle. Filter by area or select **Present** to enlarge the roadmap.

Each affected card shows the same [evidence reviews](evidence-reviews.md) as the terminal roadmap.

Use **Edit priorities** on an open cycle. Drag a card or use **Move** to change its position or horizon.
Return a planned card to the candidates to release its capacity. Cards stay fixed after delivery starts.

Choose **New planning cycle** to compare approved candidates. Enter dates, capacity, constraints, assessments, trade-offs, and sources.
Choose a horizon, rank, and effort for each selection. Use **Compare only** to leave an option available.

Save the comparison and review the proposal. The comparison uses the same Markdown record as the terminal workflow.
You can load an existing unsigned comparison by its cycle ID.
Choose **Approve on this computer**, then confirm the exact changes in the desktop window.
If the register or comparison changes, review a fresh proposal.

## Tasks and launch checklists

Open **Tasks** or **Launch checklists**, then choose a product and initiative.
Add or edit items. Preview changes and save them to the same lists the terminal commands use.

Start a launch checklist from the shared template. Record evidence to verify a check.
A task edit preview names launch checks affected by withdrawn evidence. The checklist shows each outstanding reason and the earlier verification.

Choose independent evidence or specify verification task IDs when a check uses only some supporting tasks.
Record the approver and reason for a waiver. Review readiness before the launch decision.
If the list changes, inspect the current record and review your edits again.

See the [terminal workflow](initiative-work.md) for the list fields and [roadmap approvals](initiative-approvals.md) for the decision gates.

## Browser tests

Use Node.js 20 or later. From the Hub root, install the test dependencies and run Chromium:

```sh
npm ci --prefix tests/browser
npm exec --prefix tests/browser -- playwright install chromium
npm test --prefix tests/browser
```

Set `PM_HUB_CHROMIUM` to use an installed Chromium binary.
The tests use temporary workspaces and fixture keys. The signing tests simulate the desktop confirmation and run OpenSSH.

## Review workflow changes

The required PR review checks changes to roadmap, task, launch checklist, and browser workflow files.
Add one `## Browser impact` section to the pull request.
Start with `Changed:` and describe the affected behavior, or use `Unchanged:` and explain why it stays the same.

For changed behavior, add or update a Playwright spec in `tests/browser/`.
Describe what you verified through the terminal and browser.
The reviewer checks the explanation and test coverage. The required CI check runs Playwright.
