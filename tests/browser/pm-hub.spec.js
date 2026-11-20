const { execFileSync, spawn, spawnSync } = require("node:child_process");
const { once } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const { createInterface } = require("node:readline");
const { test: base, expect } = require("@playwright/test");

const python = process.env.PM_HUB_PYTHON || "python3";
const action = ["action", "workspace", "browser", "open"];
const scope = ["example", "renewal"];

async function launch(args, options = {}, timeout = 20_000) {
  const child = spawn(python, ["-B", ...args], { ...options, stdio: ["ignore", "pipe", "pipe"] });
  const closed = once(child, "close");
  const lines = createInterface({ input: child.stdout });
  let stderr = "";
  child.stderr.on("data", data => { stderr += data; });
  const stop = async () => {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGINT");
    await closed;
  };

  try {
    const line = await Promise.race([
      once(lines, "line").then(([value]) => value),
      closed.then(([code]) => { throw new Error("oryx launcher exited (" + code + ") " + stderr); }),
      once(AbortSignal.timeout(timeout), "abort").then(() => { throw new Error("oryx launcher timed out"); }),
    ]);
    return { line, stop };
  } catch (error) {
    await stop();
    throw error;
  } finally {
    lines.close();
  }
}

const test = base.extend({
  hub: [async ({}, use) => {
    // The fixture creates and signs a synthetic portfolio before it starts the server.
    const server = await launch([path.join(__dirname, "fixture.py")], {
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    }, 60_000);
    try {
      const data = JSON.parse(server.line);
      const env = { ...process.env, PM_HUB_ALLOWED_SIGNERS: data.signers, PYTHONDONTWRITEBYTECODE: "1" };
      const args = [path.join(data.root, "tools", "pm.py")];
      await use({
        ...data,
        cli: (command, input) => JSON.parse(execFileSync(python, ["-B", ...args, ...command], {
          cwd: data.root, env, encoding: "utf8", input: input === undefined ? undefined : JSON.stringify(input),
        })),
        sign: proposal => spawnSync(python, ["-B", ...args, "initiative", "apply", "example", "--key", data.fixtureKey],
          { cwd: data.root, env, encoding: "utf8", input: JSON.stringify(proposal) }),
        open: screen => launch([...args, ...action, "--no-open", "--screen", screen], { cwd: data.root, env }),
      });
    } finally {
      await server.stop();
    }
  }, { timeout: 70_000 }],
});

const button = (scope, name) => scope.getByRole("button", { name, exact: true });
const select = (scope, name) => scope.getByRole("combobox", { name, exact: true });
const field = (scope, name) => scope.getByLabel(name, { exact: true });
const dialog = (page, name) => page.getByRole("dialog", { name, exact: true });
const lane = (page, horizon) => page.locator("[data-lane=" + horizon + "]");
const card = (page, title) => page.locator(".card").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
const taskList = hub => hub.cli(["task", "list", ...scope]);
const checklist = hub => hub.cli(["launch-checklist", "list", ...scope]);

async function fill(scope, fields) {
  for (const [name, value] of Object.entries(fields)) await field(scope, name).fill(value);
}

test("the shared launcher opens each named screen and stays there on reload", async ({ hub, page }) => {
  for (const [screen, title] of [["roadmap", "Roadmap"], ["tasks", "Tasks"], ["launch-checklists", "Launch checklists"]]) {
    const launcher = await hub.open(screen);
    try {
      expect(launcher.line).toMatch(/^oryx is open at http:\/\/127\.0\.0\.1:/);
      await page.goto(launcher.line.split(" ").at(-1));
      await expect(page).toHaveTitle("oryx");
      await expect(page.getByRole("link", { name: "oryx home" })).toContainText("oryx");
      const heading = page.getByRole("heading", { name: title, exact: true });
      await expect(heading).toBeVisible();
      expect(new URL(page.url()).hash).toBe("");
      await page.reload();
      await expect(heading).toBeVisible();
    } finally {
      await launcher.stop();
    }
  }
});

test("an empty Studio opens its agent walkthrough from a task deep link", async ({ hub, page }) => {
  const studio = path.join(hub.root, "studio");
  const reviewed = path.join(path.dirname(hub.root), "reviewed-studio");
  fs.renameSync(studio, reviewed);
  execFileSync(python, [path.join(hub.root, "tools", "pm.py"), "init-workspace", "--owner", "Fixture PM"],
    { cwd: hub.root, stdio: "pipe" });
  const address = new URL(hub.url);
  address.searchParams.set("screen", "tasks");
  await page.goto(address.href);
  await expect(page.getByRole("heading", { name: "Continue onboarding" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Company context" })).toBeVisible();
  await expect(page.getByText("Continue in your oryx conversation.", { exact: false })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(button(page, "New task")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Continue onboarding" })).toBeVisible();

  const catalog = path.join(hub.root, "playbook", "onboarding-frameworks.json");
  const frameworks = JSON.parse(fs.readFileSync(catalog, "utf8"));
  fs.writeFileSync(catalog, JSON.stringify({ ...frameworks, product: null }));
  let progress = hub.cli(["onboarding", "status"]);
  for (const topic of frameworks.company) {
    progress = hub.cli(["onboarding", "review-topic"], {
      revision: progress.revision, stage: "company", topic: topic.id,
      outcome: "open", pm_reply: "I'm still figuring that out.",
    });
  }
  await button(page, "Check progress").click();
  await expect(page.getByRole("heading", { name: "PM context" })).toBeVisible();
  await expect(page.getByText(frameworks.pm[0].question, { exact: true })).toBeVisible();
  for (const topic of frameworks.pm) {
    progress = hub.cli(["onboarding", "review-topic"], {
      revision: progress.revision, stage: "pm", topic: topic.id,
      outcome: "open", pm_reply: "Let's keep this open for now.",
    });
  }
  await button(page, "Check progress").click();
  await expect(page.getByRole("heading", { name: "Product context" })).toBeVisible();
  await expect(page.getByText("You can still update your company, PM, and stakeholder context", { exact: false })).toBeVisible();
  await expect(button(page, "New task")).toHaveCount(0);

  const checkpoint = path.join(studio, "workspace", "onboarding", "review.json");
  fs.writeFileSync(checkpoint, "damaged test checkpoint");
  await button(page, "Check progress").click();
  await expect(page.getByText("Ask oryx to review your saved progress with you.")).toBeVisible();
  await expect(page.getByText("You can still update your company", { exact: false })).toHaveCount(0);

  fs.writeFileSync(catalog, JSON.stringify(frameworks));
  fs.renameSync(studio, path.join(path.dirname(hub.root), "empty-studio"));
  fs.renameSync(reviewed, studio);
  await button(page, "Check progress").click();
  await expect(page.getByRole("heading", { name: "Tasks", exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("screen")).toBe("tasks");
});

test("compare and sign a cycle, filter the board, and approve a drag change", async ({ hub, page }) => {
  test.setTimeout(75_000);
  const template = path.join(hub.root, "templates", "prioritization.md");
  const original = fs.readFileSync(template, "utf8");
  fs.writeFileSync(template, original.replace("## Sources", "## Pilot review\n\n{{Review the pilot.}}\n\n## Sources"));
  hub.cli(["customize", "apply"], { revision: hub.cli(["customize", "show"]).revision, config: {
    products: { example: { templates: { prioritization: {
      "Review owner": { prompt: "Who will review the pilot?", before: "Pilot review" },
      "2027": { prompt: "Who sponsors the pilot in 2027?", before: "Capacity constraints" },
    } } } },
  } });
  fs.writeFileSync(template, original);
  await page.goto(hub.url);
  await button(page, "New planning cycle").click();
  const cycle = dialog(page, "New planning cycle");
  await expect(cycle.getByText("Studio placed Review owner before Work state because the saved heading Pilot review is missing.")).toBeVisible();
  const sectionLabels = await cycle.locator("label").allTextContents();
  expect(sectionLabels.indexOf("2027") + 1).toBe(sectionLabels.indexOf("Capacity constraints"));
  await fill(cycle, {
    "Cycle ID": "customer-operations",
    "Period end": hub.today,
    "Capacity": "4",
    "Effort unit": "engineer-days",
    "Objectives and obligations": "Improve renewal timing and export turnaround.",
    "Capacity constraints": "Four engineer-days remain after maintenance.",
    "2027": "The renewals lead confirmed next year's capacity.",
    "Alternatives and trade-offs": "Run both pilots within the remaining capacity.",
    "Sources": "Pilot evidence and the signed initiative briefs.",
    "Review owner": "The pilot PM will review results.",
    "Selection reason": "Test both approaches within this cycle.",
    "Decision source": "Planning meeting",
  });
  const candidates = [
    ["Renewal delays", "Start reminders earlier for renewal administrators.", "now", "1"],
    ["Export turnaround", "Reduce waiting for export users.", "later", "2"],
  ];
  for (const [name, assessment, horizon, rank] of candidates) {
    const candidate = cycle.locator("section").filter({ has: page.getByRole("heading", { name, exact: true }) });
    await field(candidate, "Compare " + name).check();
    await field(candidate, "Assessment").fill(assessment);
    await select(candidate, "Selection").selectOption(horizon);
    await fill(candidate, { Rank: rank, Effort: "2" });
  }
  await button(cycle, "Save comparison and review").click();
  const review = dialog(page, "Review roadmap proposal");
  await expect(review.locator("pre")).toContainText("The pilot PM will review results.");
  await expect(review.getByText("Create customer-operations")).toBeVisible();
  await button(review, "Approve on this computer").click();
  await expect(review.getByText("Approval cancelled. You can review or approve again.")).toBeVisible();
  expect(hub.cli(["roadmap", "--product", "example"])).toEqual([]);
  await button(review, "Approve on this computer").click();
  await expect(lane(page, "now").getByRole("heading", { name: "Renewal delays" })).toBeVisible();
  await expect(lane(page, "later").getByRole("heading", { name: "Export turnaround" })).toBeVisible();

  const renewalID = hub.cli(["roadmap", "--product", "example"]).find(row => row.title === "Renewal delays").id;
  const decision = { type: "decision", initiative: renewalID, on: hub.today,
    reason: "The PM chose earlier renewal reminders.", source: "Renewal planning review, item 2" };
  const tradeoff = "Delay export research by one week to test reminders.";
  const signedPlan = hub.cli(["initiative", "propose", "example"], [
    { ...decision, action: "unplan" },
    { ...decision, action: "plan", cycle: "customer-operations", rank: 1, horizon: "now", effort: 2,
      rationale: { choice: "Test reminders first", alternatives: ["Test both in parallel"], tradeoff,
        owner: "Renewals PM", scope: "Renewal pilot", reopen_when: "Renewal contacts rise by five percent" } },
  ]);
  expect(hub.sign(signedPlan).status).toBe(0);
  expect(hub.cli(["roadmap", "--product", "example"]).find(row => row.id === renewalID).trade_off).toBe(tradeoff);
  await button(page, "Refresh").click();
  const placement = card(page, "Renewal delays");
  await expect(placement.locator("details")).toContainText(tradeoff);
  await placement.getByText("Details", { exact: true }).click();
  await expect(placement.getByText(tradeoff, { exact: true })).toBeVisible();

  const reason = "Legal clearance is pending for the renewal audience.";
  hub.cli(["route-context", "--write", "context/products/example/overview.md"], {
    sources: [{ reference: "Fixture legal review, item 12", date: hub.today, checked_on: hub.today,
      coverage: "read", text: "Confirm clearance for the renewal pilot." }],
    entries: [{ scope: "product", product: "example", topic: "constraints", source: 1, location: "Item 12",
      quote: "Confirm clearance for the renewal pilot.", risk: { reason, targets: [renewalID] } }],
  });
  const published = hub.cli(["roadmap", "--product", "example"]);
  const [warning] = published.find(row => row.id === renewalID).evidence_reviews;
  expect(warning).toContain(reason);
  await button(page, "Refresh").click();
  await expect(card(page, "Renewal delays").getByText(warning, { exact: true })).toBeVisible();
  await expect(card(page, "Export turnaround").getByRole("list", { name: "Evidence to review" })).toHaveCount(0);

  await select(page, "Product area").selectOption("product/example/area/renewals");
  await expect(card(page, "Renewal delays")).toBeVisible();
  await expect(card(page, "Export turnaround")).toHaveCount(0);
  await button(page, "Present").click();
  await expect(page.locator("body")).toHaveClass(/presenting/);
  await expect(card(page, "Renewal delays").getByText(warning, { exact: true })).toBeVisible();
  expect(hub.cli(["roadmap", "--product", "example"])).toEqual(published);
  await button(page, "Exit presentation").click();

  await button(page, "Edit priorities").click();
  await card(page, "Renewal delays").dragTo(lane(page, "next"));
  await expect(lane(page, "next").getByRole("heading", { name: "Renewal delays" })).toBeVisible();
  expect(hub.cli(["roadmap", "--product", "example"]).find(row => row.title === "Renewal delays").horizon).toBe("now");
  await fill(page, { "Trade-off or reason": "Move the pilot after maintenance.", "Decision source": "Priority review" });
  await button(page, "Review changes").click();
  await button(review, "Approve on this computer").click();
  await expect(button(page, "Edit priorities")).toBeVisible();
  expect(hub.cli(["roadmap", "--product", "example"]).map(row => [row.title, row.horizon]))
    .toEqual([["Renewal delays", "next"], ["Export turnaround", "later"]]);

  const pages = path.join(hub.root, "studio", "customizations", "views");
  fs.mkdirSync(pages, { recursive: true });
  fs.writeFileSync(path.join(pages, "team-review.html"), "<title>Team review</title><!-- pm:roadmap-data -->");
  const config = hub.cli(["customize", "show"]);
  hub.cli(["customize", "apply"], { revision: config.revision, config: {
    fields: { "x-confidence": { type: "choice", label: "Score", choices: ["High", "Low"] },
      "x-teams": { type: "multiple", label: "Internal dependencies", choices: ["Billing", "Mobile"] } },
    views: { review: { title: "Review table", layout: "table", group: "areas", page: "team-review",
      labels: { "x-confidence": "Confidence" }, columns: ["title", "x-confidence"] } },
    default_view: "review",
  }, values: [{ product: "example", id: published.find(row => row.title === "Renewal delays").id,
    field: "x-teams", value: ["Mobile", "Billing"] }] });
  await button(page, "Refresh").click();
  await expect(page.getByRole("heading", { name: "Review table" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Confidence" })).toHaveCount(2);
  await button(page, "Edit fields for Renewal delays").click();
  const fields = dialog(page, "Fields for Renewal delays");
  await expect(field(fields, "Internal dependencies")).toHaveCount(0);
  await select(fields, "Confidence").selectOption("High");
  await button(fields, "Save fields").click();
  await expect(page.getByRole("cell", { name: "High", exact: true })).toBeVisible();
  expect(hub.cli(["roadmap", "--product", "example"])).toContainEqual({ title: "Renewal delays", "x-confidence": "High" });
  expect(Object.values(hub.cli(["customize", "show"]).values.example)[0]["x-teams"]).toEqual(["Mobile", "Billing"]);
  await page.reload();
  await expect(page.getByRole("cell", { name: "High", exact: true })).toBeVisible();
  await select(page, "Product area").selectOption("product/example/area/renewals");
  await button(page, "Present").click();
  await expect(page.getByText(/engineer-days reserved/)).toHaveCount(0);
  await expect(select(page, "Product area")).toHaveCount(0);
  await expect(select(page, "View")).toHaveCount(0);
  fs.writeFileSync(path.join(pages, "team-review.html"), "<title>Revised review</title><!-- pm:roadmap-data -->");
  await button(page, "Download custom view").click();
  await expect(page.getByText(/custom page changed/)).toBeVisible();
  await button(page, "Exit presentation").click();
  await button(page, "Refresh").click();
  await button(page, "Present").click();
  // A colleague broadens the current export while the PM is presenting.
  hub.cli(["customize", "apply"], { revision: hub.cli(["customize", "show"]).revision,
    config: { views: { review: { columns: ["title", "x-confidence", "effort"] } } } });
  await button(page, "Download custom view").click();
  await expect(page.getByText(/custom view changed/)).toBeVisible();
  hub.cli(["customize", "apply"], { revision: hub.cli(["customize", "show"]).revision,
    config: { views: { review: { columns: ["title", "x-confidence"] } } } });
  await button(page, "Exit presentation").click();
  await button(page, "Refresh").click();
  await button(page, "Present").click();
  const downloaded = page.waitForEvent("download");
  await button(page, "Download custom view").click();
  const file = await downloaded;
  const exported = fs.readFileSync(await file.path(), "utf8");
  expect(exported).toContain("<title>Revised review</title>");
  expect(exported).toContain('"x-confidence": "High"');
  expect(exported).not.toContain("Export turnaround");
  expect(exported).not.toContain('"effort"');
  await button(page, "Exit presentation").click();
  await button(page, "Edit priorities").click();
  await expect(lane(page, "next").getByRole("heading", { name: "Renewal delays" })).toBeVisible();
});

test("a stale task edit keeps the browser draft and preserves the CLI change", async ({ hub, page }) => {
  await page.goto(hub.url);
  await button(page, "Tasks").click();
  await select(page, "Initiative").selectOption("renewal");
  await button(page, "Add task").click();
  const add = dialog(page, "Add task");
  await fill(add, {
    "Stable ID": "support-handoff",
    "Title": "Coordinate support handoff",
    "Completion criteria": "Support acknowledges the launch notes.",
    "Owner": "Pilot PM",
  });
  await button(add, "Preview edit").click();
  expect(taskList(hub).tasks).toEqual([]);
  await button(page, "Save edit").click();
  await button(page, "Edit Coordinate support handoff").click();
  const editor = dialog(page, "Edit Coordinate support handoff");
  await field(editor, "Title").fill("Confirm support handoff");
  await button(editor, "Preview edit").click();
  const review = dialog(page, "Review Confirm support handoff");
  hub.cli(["task", "apply", ...scope, "--revision", taskList(hub).revision], [
    { id: "support-handoff", action: "update", fields: { owner: "Support lead" } },
  ]);
  await button(review, "Save edit").click();
  await expect(review.getByText(/The list changed/)).toBeVisible();
  await button(review, "Close").click();
  await expect(field(editor, "Title")).toHaveValue("Confirm support handoff");
  await button(editor, "Check current record").click();
  await expect(editor.getByText("Support lead", { exact: false })).toBeVisible();
  await button(editor, "Use current revision").click();
  await select(editor, "Status").selectOption("done");
  await field(editor, "Resolution").fill("Support acknowledged the handoff.");
  await button(editor, "Preview edit").click();
  await button(page, "Save edit").click();
  await expect(page.locator(".row .badge[data-tone=done]")).toBeVisible();
  expect(taskList(hub).tasks[0]).toMatchObject({ title: "Confirm support handoff", owner: "Support lead", status: "done" });
});

test("the launch template stays a preview until saved and verification retains evidence", async ({ hub, page }) => {
  await page.goto(hub.url);
  await button(page, "Launch checklists").click();
  await select(page, "Initiative").selectOption("renewal");
  await button(page, "Start from template").click();
  expect(checklist(hub).checkpoints).toEqual([]);
  hub.cli(["customize", "apply"], { revision: hub.cli(["customize", "show"]).revision,
    config: { checkpoints: { enablement: { title: "Confirm custom enablement" } } } });
  await button(page, "Create checklist").click();
  const preview = dialog(page, "Start a launch checklist");
  await expect(preview.getByRole("alert")).toContainText("template changed");
  expect(checklist(hub).checkpoints).toEqual([]);
  await button(preview, "Close").click();
  await button(page, "Start from template").click();
  await expect(dialog(page, "Start a launch checklist").getByText("Confirm custom enablement")).toBeVisible();
  await button(page, "Create checklist").click();
  await button(page, "Edit Verify launch monitoring").click();
  const editor = dialog(page, "Edit Verify launch monitoring");
  await select(editor, "Status").selectOption("verified");
  await field(editor, "Owner").fill("On-call lead");
  await button(editor, "Preview edit").click();
  await expect(dialog(page, "Review Verify launch monitoring")).toHaveCount(0);
  expect(checklist(hub).checkpoints.find(row => row.id === "launch-monitoring").status).toBe("pending");

  await fill(editor, {
    "Verification evidence": "A test alert reached the on-call rotation.",
    "Verified by": "On-call lead",
    "Verified on": hub.today,
  });
  await button(editor, "Preview edit").click();
  await button(page, "Save edit").click();
  await expect(page.locator(".row .badge[data-tone=verified]")).toBeVisible();
  const saved = checklist(hub);
  expect(saved.launch_readiness).toBe("pending");
  expect(saved.checkpoints.find(row => row.id === "launch-monitoring")).toMatchObject({
    status: "verified",
    verification: { by: "On-call lead", on: hub.today, evidence: "A test alert reached the on-call rotation." },
  });
});

test("withdrawing a verified task shows its launch impact and invalidates the reviewed ship", async ({ hub, page }) => {
  const initiative = hub.cli(["initiative", "show", "example"]).context.product.id + "/renewal";
  const decision = { type: "decision", initiative, on: hub.today, review_on: hub.today,
    reason: "The PM confirmed the small regional pilot.", source: "PM release review" };
  const propose = change => hub.cli(["initiative", "propose", "example"], [change]);
  const expedite = propose({ ...decision, action: "expedite", owner: "Incident PM", obligation: "Restore EU alerts",
    deadline: hub.today, scope: "Verify the European renewal pilot", delivery: "https://example.com/drill/42" });
  expect(hub.sign(expedite).status).toBe(0);
  const evidence = "Canary alert receipt EU-41.";
  hub.cli(["task", "apply", ...scope, "--revision", "absent"], [{ action: "add", id: "canary",
    fields: { title: "Run the canary", owner: "On-call lead", completion_criteria: "Receive the regional alert",
      status: "done", resolution: evidence } }]);
  const verification = { evidence, by: "Incident lead", on: hub.today };
  hub.cli(["launch-checklist", "apply", ...scope, "--revision", "absent"], ["upstream", "launch"].map(phase => ({
    action: "add", id: phase, fields: { title: "Check " + phase, phase, criterion: "Verify alert coverage",
      status: "verified", owner: "Incident lead", tasks: phase === "launch" ? ["canary"] : [], verification },
  })));
  const ship = { ...decision, action: "ship" };
  const ready = propose(ship);
  const withdrawn = "The receipt covered the wrong region.";
  await page.goto(hub.url);
  await button(page, "Tasks").click();
  await select(page, "Initiative").selectOption("renewal");
  await button(page, "Edit Run the canary").click();
  const task = dialog(page, "Edit Run the canary");
  await select(task, "Status").selectOption("blocked");
  await field(task, "Blocking reason").fill(withdrawn);
  await button(task, "Preview edit").click();
  const preview = dialog(page, "Review Run the canary");
  const warnings = preview.getByRole("region", { name: "Launch checks to review" });
  await expect(warnings).toContainText("Check launch");
  await expect(warnings).toContainText(withdrawn);
  expect(propose(ship)).toEqual(ready);
  await button(preview, "Save edit").click();
  await expect(page.locator(".row").filter({ hasText: "Run the canary" })).toContainText("Check launch");
  const rejected = hub.sign(ready);
  expect(rejected.status).not.toBe(0);
  expect(rejected.stdout).toContain("proposal is stale");
  await button(page, "Launch checklists").click();
  await select(page, "Initiative").selectOption("renewal");
  const readiness = page.getByRole("region", { name: "Launch readiness" });
  await expect(readiness).toContainText(withdrawn);
  const checkpoint = page.locator(".row").filter({ has: page.getByRole("heading", { name: "Check launch", exact: true }) });
  await expect(checkpoint).toContainText("Verification needs review");
  await expect(checkpoint).toContainText(evidence);

  await button(checkpoint, "Edit Check launch").click();
  const edit = dialog(page, "Edit Check launch");
  await select(edit, "Evidence basis").selectOption("independent");
  await field(edit, "Verification evidence").fill("Independent signed regional alert receipt EU-42.");
  await button(edit, "Preview edit").click();
  await button(dialog(page, "Review Check launch"), "Save edit").click();
  await expect(readiness).toContainText("Ready for launch decision");

  await button(checkpoint, "Edit Check launch").click();
  await field(edit, "Due date").fill(hub.today);
  await button(edit, "Preview edit").click();
  const due = dialog(page, "Review Check launch");
  await expect(due.getByRole("heading", { name: "Verification", exact: true })).toHaveCount(0);
  await button(due, "Save edit").click();
  await expect(edit).toHaveCount(0);
  expect(checklist(hub).checkpoints.find(row => row.id === "launch").verification.basis_tasks).toEqual([]);
});
