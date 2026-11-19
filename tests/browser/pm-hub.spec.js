const { execFileSync, spawn } = require("node:child_process");
const { once } = require("node:events");
const path = require("node:path");
const { createInterface } = require("node:readline");
const { test: base, expect } = require("@playwright/test");

const python = process.env.PM_HUB_PYTHON || "python3";
const action = ["action", "workspace", "browser", "open"];
const scope = ["example", "renewal"];

async function launch(args, options = {}) {
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
      closed.then(([code]) => { throw new Error("PM Hub launcher exited (" + code + ") " + stderr); }),
      once(AbortSignal.timeout(20_000), "abort").then(() => { throw new Error("PM Hub launcher timed out"); }),
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
  hub: async ({}, use) => {
    const server = await launch([path.join(__dirname, "fixture.py")], {
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    });
    try {
      const data = JSON.parse(server.line);
      const env = { ...process.env, PM_HUB_ALLOWED_SIGNERS: data.signers, PYTHONDONTWRITEBYTECODE: "1" };
      const args = [path.join(data.root, "tools", "pm.py")];
      await use({
        ...data,
        cli: (command, input) => JSON.parse(execFileSync(python, ["-B", ...args, ...command], {
          cwd: data.root, env, encoding: "utf8", input: input === undefined ? undefined : JSON.stringify(input),
        })),
        open: screen => launch([...args, ...action, "--no-open", "--screen", screen], { cwd: data.root, env }),
      });
    } finally {
      await server.stop();
    }
  },
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
      expect(launcher.line).toMatch(/^PM Hub is open at http:\/\/127\.0\.0\.1:/);
      await page.goto(launcher.line.split(" ").at(-1));
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

test("compare and sign a cycle, filter the board, and approve a drag change", async ({ hub, page }) => {
  await page.goto(hub.url);
  await button(page, "New planning cycle").click();
  const cycle = dialog(page, "New planning cycle");
  await fill(cycle, {
    "Cycle ID": "customer-operations",
    "Period end": hub.today,
    "Capacity": "4",
    "Effort unit": "engineer-days",
    "Objectives and obligations": "Improve renewal timing and export turnaround.",
    "Capacity constraints": "Four engineer-days remain after maintenance.",
    "Alternatives and trade-offs": "Run both pilots within the remaining capacity.",
    "Sources": "Pilot evidence and the signed initiative briefs.",
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
  await expect(review.getByText("Create customer-operations")).toBeVisible();
  await button(review, "Approve on this computer").click();
  await expect(review.getByText("Approval cancelled. You can review or approve again.")).toBeVisible();
  expect(hub.cli(["roadmap", "--product", "example"])).toEqual([]);
  await button(review, "Approve on this computer").click();
  await expect(lane(page, "now").getByRole("heading", { name: "Renewal delays" })).toBeVisible();
  await expect(lane(page, "later").getByRole("heading", { name: "Export turnaround" })).toBeVisible();

  const renewalID = hub.cli(["roadmap", "--product", "example"]).find(row => row.title === "Renewal delays").id;
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
