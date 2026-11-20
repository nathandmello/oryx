const horizons = ["now", "next", "later"];
const screenNames = { roadmap: "Roadmap", task: "Tasks", "launch-checklist": "Launch checklists" };
const screenPaths = { roadmap: "roadmap", task: "tasks", "launch-checklist": "launch-checklists" };
const comparisonSections = ["Objectives and obligations", "Capacity constraints", "Comparison", "Sources"];
const app = document.querySelector("#app");
const nav = document.querySelector("nav");
const sessionKey = "pm-hub-session";
const fragment = location.hash.slice(1);
if (fragment) {
  sessionStorage.setItem(sessionKey, fragment);
  history.replaceState(null, "", location.pathname + location.search);
}
const token = sessionStorage.getItem(sessionKey);
const requestedScreen = new URLSearchParams(location.search).get("screen");
const state = {
  screen: Object.keys(screenPaths).find(screen => screenPaths[screen] === requestedScreen) || "roadmap",
  catalog: null, product: "", cycle: "", area: "", board: null, edit: null, view: null,
  presenting: false, scope: { task: {}, "launch-checklist": {} }, list: null, filter: "",
  setup: null,
};
let dragged = null;
let boardRequest = 0;
let workRequestNumber = 0;

function node(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
    else if (value === true) element.setAttribute(key, "");
    else if (value !== false && value != null) element.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child != null && child !== false) element.append(child);
  }
  return element;
}

function label(text, control, wide = false) {
  return node("label", { class: wide ? "wide" : null }, text, control);
}

function button(text, action, style = "", attributes = {}) {
  return node("button", { type: "button", class: "btn " + style, onclick: action, ...attributes }, text);
}

function input(value = "", attrs = {}) {
  return node("input", { value: value ?? "", ...attrs });
}

function textarea(value = "", attrs = {}) {
  return node("textarea", attrs, value);
}

function select(options, current, attrs = {}) {
  const control = node("select", attrs, options.map(([value, text]) => node("option", { value }, text)));
  control.value = current;
  return control;
}

function readable(value) {
  return value ? value[0].toUpperCase() + value.slice(1).replaceAll("-", " ") : "";
}

function badge(value, tone = value) {
  return node("span", { class: "badge", "data-tone": tone }, readable(value));
}

function actions(...children) {
  return node("div", { class: "actions" }, children);
}

function alert(message = "", error = false, dialog = null) {
  const target = dialog?.querySelector(".dialog-status") || document.querySelector(".status");
  target.textContent = message;
  target.hidden = !message;
  target.classList.toggle("error", error);
}

async function api(endpoint, body = {}) {
  if (!token) throw new Error("Open this browser session from the oryx launcher.");
  const response = await fetch("/api/" + endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-PM-Hub-Token": token },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (response.status === 409 && result.status === "onboarding_required") {
    enterSetup(result.onboarding);
    throw new SetupRequired();
  }
  if (!response.ok) throw new Error(result.error);
  return result;
}

class SetupRequired extends Error {}

async function attempt(event, callback) {
  const target = event?.currentTarget;
  const dialog = target?.closest("dialog");
  const canDisable = target && "disabled" in target;
  if (canDisable) target.disabled = true;
  alert("", false, dialog);
  try {
    await callback();
  } catch (error) {
    if (!(error instanceof SetupRequired)) alert(error.message, true, dialog?.open ? dialog : null);
  } finally {
    if (canDisable) target.disabled = false;
  }
}

function modal(title, body, footer = []) {
  const dialog = node("dialog", { "aria-label": title });
  dialog.append(
    node("div", { class: "dialog-header" }, node("h2", {}, title),
      button("Close", () => dialog.close(), "ghost compact")),
    node("div", { class: "dialog-body" }, node("p", { class: "dialog-status", role: "alert", hidden: true }), body),
  );
  if (footer.length) dialog.append(node("div", { class: "dialog-footer" }, footer));
  document.querySelector("#dialogs").append(dialog);
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  dialog.showModal();
  return dialog;
}

function formGrid(...children) {
  return node("form", { class: "form-grid", onsubmit: event => event.preventDefault() }, children);
}

function heading(title, detail, ...buttons) {
  return node("div", { class: "heading" },
    node("div", {}, node("h1", {}, title), detail && node("p", {}, detail)),
    buttons.length ? actions(...buttons) : null);
}

function productOptions(onlyRoadmaps) {
  return state.catalog.products.filter(product => !onlyRoadmaps || product.roadmap)
    .map(product => [product.id, product.title]);
}

async function loadBoard(view = state.view) {
  const request = ++boardRequest;
  state.product ||= productOptions(true)[0]?.[0] || "";
  const board = state.product ? await api("roadmap", { product: state.product, view }) : null;
  if (request !== boardRequest || state.screen !== "roadmap") return;
  state.view = view;
  state.board = board;
  if (!board?.cycles.some(cycle => cycle.cycle === state.cycle)) {
    state.cycle = board?.cycles.find(cycle => cycle.starts_on <= board.today && cycle.ends_on >= board.today)?.cycle
      || board?.cycles.at(-1)?.cycle || "";
  }
}

function cycleRows() {
  return state.board?.rows.filter(row => row.cycle === state.cycle) || [];
}

function selectedCycle() {
  return state.board?.cycles.find(cycle => cycle.cycle === state.cycle);
}

function startEdit() {
  const rows = cycleRows();
  const order = Object.fromEntries(horizons.map(horizon => [
    horizon, rows.filter(row => row.horizon === horizon).map(row => row.id),
  ]));
  state.edit = { order, effort: {}, reason: "", source: "" };
  state.area = "";
  render();
}

function removePlacement(id) {
  for (const horizon of horizons) {
    state.edit.order[horizon] = state.edit.order[horizon].filter(item => item !== id);
  }
}

function move(id, horizon, before = null) {
  if (id === before) return;
  removePlacement(id);
  const column = state.edit.order[horizon];
  const index = before ? column.indexOf(before) : column.length;
  column.splice(index === -1 ? column.length : index, 0, id);
  render();
}

function moveDialog(row) {
  const current = horizons.find(horizon => state.edit.order[horizon].includes(row.id));
  const destination = select(horizons.map(horizon => [horizon, readable(horizon)]), current);
  const position = select([], "");
  function positions() {
    const source = state.edit.order[destination.value].filter(id => id !== row.id);
    const labels = new Map([...cycleRows(), ...state.board.candidates].map(item => [item.id, item.title]));
    position.replaceChildren(...source.map(id => node("option", { value: id }, "Before " + labels.get(id))),
      node("option", { value: "" }, "End of column"));
    const index = state.edit.order[current].indexOf(row.id);
    position.value = destination.value === current ? state.edit.order[current][index + 1] || "" : "";
  }
  destination.addEventListener("change", positions);
  positions();
  const dialog = modal("Move " + row.title, formGrid(label("Horizon", destination), label("Position", position)), [
    button("Return to candidates", () => {
      dialog.close();
      removePlacement(row.id);
      delete state.edit.effort[row.id];
      render();
    }, "ghost"),
    button("Move", () => {
      dialog.close();
      move(row.id, destination.value, position.value);
    }, "primary"),
  ]);
}

function connectDrop(element, horizon, before = null) {
  element.addEventListener("dragover", event => {
    if (!dragged) return;
    event.preventDefault();
    event.stopPropagation();
    element.classList.add("over");
  });
  element.addEventListener("dragleave", event => {
    if (!element.contains(event.relatedTarget)) element.classList.remove("over");
  });
  element.addEventListener("drop", event => {
    event.preventDefault();
    event.stopPropagation();
    element.classList.remove("over");
    if (dragged) move(dragged, horizon, before);
    dragged = null;
  });
}

function roadmapCard(row, horizon) {
  const movable = row.phase === "planned" || row.phase === "candidate";
  const card = node("article", { class: "card", draggable: !!state.edit && movable ? "true" : null },
    node("h3", {}, row.title), row.outcome && node("p", { class: "muted" }, row.outcome));
  if (row.evidence_reviews?.length) {
    card.append(node("h4", {}, "Evidence to review"),
      node("ul", { "aria-label": "Evidence to review" }, row.evidence_reviews.map(review => node("li", {}, review))));
  }
  if (state.edit) {
    connectDrop(card, horizon, row.id);
    if (movable) {
      card.addEventListener("dragstart", event => {
        dragged = row.id;
        event.dataTransfer.setData("text/plain", row.id);
        event.dataTransfer.effectAllowed = "move";
      });
      card.addEventListener("dragend", () => {
        dragged = null;
        document.querySelectorAll(".over").forEach(element => element.classList.remove("over"));
      });
      card.append(actions(button("Move", () => moveDialog(row), "compact", { "aria-label": "Move " + row.title })));
    } else card.append(actions(badge("fixed")));
  }
  if (row.rank != null) {
    card.append(node("details", {}, node("summary", {}, state.edit ? "Approved placement" : "Details"),
      node("p", { class: "small" }, readable(row.phase) + " · Rank " + row.rank + " · " + row.effort + " " + row.unit),
      row.trade_off && node("p", { class: "small muted" }, row.trade_off)));
  }
  return card;
}

async function reviewBoard(event) {
  await attempt(event, async () => {
    const proposal = await api("roadmap-preview", {
      mode: "edit", product: state.product, cycle: state.cycle, revision: state.board.revision, ...state.edit,
    });
    showRoadmapReview(proposal);
  });
}

function addCandidate() {
  const candidates = [
    ...state.board.candidates.filter(candidate => candidate.eligible_cycles.includes(state.cycle)),
    ...cycleRows().filter(row => row.phase === "planned"),
  ].filter(candidate => !Object.values(state.edit.order).some(ids => ids.includes(candidate.id)));
  if (!candidates.length) {
    modal("Add a candidate", node("p", {}, "All eligible candidates are on this board. Compare additional candidates in a new cycle."));
    return;
  }
  const choice = select(candidates.map(item => [item.id, item.title]), candidates[0].id);
  const horizon = select(horizons.map(value => [value, readable(value)]), "next");
  const effort = input("", { type: "number", min: 1, required: true });
  function update() {
    const candidate = candidates.find(item => item.id === choice.value);
    effort.value = candidate.effort ?? "";
    effort.disabled = candidate.effort != null;
  }
  choice.addEventListener("change", update);
  update();
  const form = formGrid(label("Candidate", choice, true), label("Horizon", horizon), label("Effort", effort));
  const dialog = modal("Add a candidate", form, [button("Add to preview", () => {
    if (!form.reportValidity()) return;
    if (!effort.disabled) state.edit.effort[choice.value] = Number(effort.value);
    dialog.close();
    move(choice.value, horizon.value);
  }, "primary")]);
}

async function showComparison(event) {
  await attempt(event, async () => {
    const result = await api("comparison", { product: state.product, cycle: state.cycle });
    modal("Planning comparison", node("div", {}, node("p", { class: "muted small" }, result.path),
      node("pre", {}, result.text || "The planning comparison is missing.")));
  });
}

function editRoadmapFields(row, view) {
  const readers = new Map();
  const controls = Object.entries(view.columns).filter(([key]) => Object.hasOwn(view.fields, key)).map(([key, title]) => {
    const field = view.fields[key];
    const value = row[key];
    let control;
    if (field.type === "multiple") {
      control = node("select", { multiple: true }, field.choices.map(choice =>
        node("option", { value: choice, selected: value?.includes(choice) }, choice)));
      readers.set(key, () => {
        const selected = Array.from(control.selectedOptions, option => option.value);
        const previous = value || [];
        if (!selected.length) return previous.length ? null : value ?? null;
        return [...previous.filter(item => selected.includes(item)), ...selected.filter(item => !previous.includes(item))];
      });
    } else if (field.type === "choice" || field.type === "boolean") {
      const choices = field.choices || ["true", "false"];
      control = select([["", "Unset"], ...choices.map(choice => [choice, choice])], String(value ?? ""));
      readers.set(key, () => control.value === "" ? null :
        field.type === "boolean" ? control.value === "true" : control.value);
    } else {
      control = field.type === "text" ? textarea(value ?? "") : input(value, { type: field.type, step: field.type === "number" ? "any" : null });
      const initial = control.value;
      // Preserve original line endings and numeric precision in untouched controls.
      const original = value ?? null;
      readers.set(key, () => control.value === initial ? original :
        control.value === "" ? null : field.type === "number" ? Number(control.value) : control.value);
    }
    return label(title, control);
  });
  const dialog = modal("Fields for " + row.title, formGrid(...controls), [
    button("Save fields", event => attempt(event, async () => {
      const values = Object.fromEntries(Array.from(readers, ([key, read]) => [key, read()]).filter(([key, value]) =>
        JSON.stringify(value) !== JSON.stringify(row[key] ?? null) && !(row[key] == null && Array.isArray(value) && !value.length)));
      if (Object.keys(values).length) {
        await api("roadmap-fields", { product: row.product, id: row.id, revision: view.revision, values });
      }
      dialog.close();
      await loadBoard();
      render();
    }), "primary"),
  ]);
}

function customizedRoadmap(view, rows) {
  const fields = Object.entries(view.columns);
  const canEdit = !state.presenting && fields.some(([key]) => Object.hasOwn(view.fields, key));
  const edit = row => button("Edit fields", () => editRoadmapFields(row, view), "compact",
    { "aria-label": "Edit fields for " + row.title });
  const groups = new Map();
  for (const row of rows) {
    const value = row[view.group];
    const names = view.group === "none" ? [""] : Array.isArray(value) && value.length ? value :
      [Array.isArray(value) || value == null || value === "" ? null : value];
    for (const name of names) {
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push(row);
    }
  }
  const display = value => Array.isArray(value) ? value.join(", ") : String(value ?? "");
  const wrapper = node("section", { class: "custom-roadmap " + view.density, "aria-label": view.title });
  for (const [group, items] of groups) {
    const title = group ?? (groups.has("Unassigned") ? "Unassigned (no value)" : "Unassigned");
    const section = node("section", {}, group !== "" && node("h2", {}, String(title)));
    if (view.layout === "table") {
      section.append(node("table", {}, node("thead", {}, node("tr", {},
        fields.map(([, title]) => node("th", { scope: "col" }, title)), canEdit && node("th", {}, "Actions"))),
        node("tbody", {}, items.map(row => node("tr", {},
          fields.map(([key]) => node("td", {}, display(row[key]))), canEdit && node("td", {}, edit(row)))))));
    } else {
      section.append(node("div", { class: "custom-cards" }, items.map(row =>
        node("article", { class: "card" }, node("dl", {}, fields.map(([key, title]) =>
          [node("dt", {}, title), node("dd", {}, display(row[key]))])), canEdit && edit(row)))));
    }
    wrapper.append(section);
  }
  if (!rows.length) wrapper.append(node("p", { class: "empty" }, "No initiatives"));
  return wrapper;
}

function downloadRoadmap(view) {
  return button("Download custom view", event => attempt(event, async () => {
    const result = await api("roadmap-export", { product: state.product, cycle: state.cycle, area: state.area,
      view: view.name, revision: view.revision, board_revision: state.board.revision, page_revision: view.page_revision });
    const url = URL.createObjectURL(new Blob([result.html], { type: "text/html" }));
    const download = node("a", { href: url, download: state.product + "-" + view.name + ".html" });
    download.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }));
}

function roadmapScreen() {
  const products = productOptions(true);
  const cycle = selectedCycle();
  const selectedProduct = products.find(([id]) => id === state.product);
  const cycleDetail = cycle ? cycle.starts_on + " to " + cycle.ends_on + "  ·  " + cycle.reserved + " / "
    + cycle.capacity + " " + cycle.unit + " reserved" : "";
  const view = state.board?.presentation;
  const rows = cycleRows();
  const visible = rows.filter(row => !state.area || row.areas.includes(state.area));
  if (view?.custom && state.presenting) {
    app.append(heading(view.title, "", view.page && downloadRoadmap(view)), customizedRoadmap(view, visible));
    return;
  }
  app.append(heading(view?.custom ? view.title : "Roadmap", selectedProduct ? [selectedProduct[1], cycleDetail].filter(Boolean).join("  ·  ") : "",
    !state.edit && !state.presenting && state.board && button("New planning cycle", event => attempt(event, newCycleDialog), "primary"),
    !state.edit && !state.presenting && !!cycle && button("Present", togglePresentation),
  ));
  if (!products.length) {
    app.append(node("div", { class: "panel empty" }, "Set up a signed product initiative register to open its roadmap."));
    return;
  }
  const subjects = [...new Set(rows.flatMap(row => row.areas))].sort();
  const controls = node("div", { class: "filters" },
    label("Product", select(products, state.product, { disabled: !!state.edit, onchange: event => attempt(event, async () => {
      state.product = event.target.value;
      state.view = null;
      state.cycle = state.area = "";
      state.board = null;
      try { await loadBoard(); } finally { render(); }
    }) })),
    label("Planning cycle", select((state.board?.cycles || []).map(item => [item.cycle, item.cycle]), state.cycle,
      { disabled: !!state.edit, onchange: event => {
        state.cycle = event.target.value;
        state.area = "";
        render();
      } })),
    !state.edit && view && Object.keys(view.views).length > 1 && label("View", select(Object.entries(view.views), view.name,
      { onchange: event => attempt(event, async () => {
        await loadBoard(event.target.value);
        render();
      }) })),
    !state.edit && label("Product area", select([["", "All areas"], ...subjects.map(subject => [subject, readable(subject.split("/").at(-1))])],
      state.area, { onchange: event => { state.area = event.target.value; render(); } })),
    !state.edit && cycle && button("Refresh", event => attempt(event, async () => { await loadBoard(); render(); })),
    !state.edit && view?.page && cycle && downloadRoadmap(view),
    !state.edit && !state.presenting && cycle && button("View comparison", showComparison),
    !state.edit && !state.presenting && cycle && button("Edit priorities", startEdit, "primary", {
      disabled: cycle.ends_on < state.board.today,
    }),
  );
  app.append(controls);
  if (view?.warning) app.append(node("p", { role: "status" }, view.warning));
  if (!cycle) {
    app.append(node("div", { class: "panel empty" }, state.board
      ? "Create a planning cycle to compare and select approved candidates."
      : "The roadmap could not be loaded. Select a product to try again."));
    return;
  }
  if (state.edit) {
    const draftInput = key => input(state.edit[key], { oninput: event => { state.edit[key] = event.target.value; } });
    app.append(node("section", { class: "panel stack" },
      node("div", { class: "panel-heading" }, node("h2", {}, "Preview changes"), actions(
        button("Add candidate", addCandidate), button("Discard", () => { state.edit = null; render(); }, "ghost"),
        button("Review changes", reviewBoard, "primary"))),
      node("div", { class: "form-grid" }, label("Trade-off or reason", draftInput("reason")), label("Decision source", draftInput("source"))),
    ));
  }
  const byId = new Map([...rows, ...(state.board?.candidates || []).map(row => ({ ...row, phase: "candidate" }))].map(row => [row.id, row]));
  if (!state.edit && view?.custom) {
    app.append(customizedRoadmap(view, visible));
    return;
  }
  app.append(node("section", { class: "board", "aria-label": "Roadmap horizons" },
    horizons.map(horizon => {
      const items = state.edit ? state.edit.order[horizon].map(id => byId.get(id)) : visible.filter(row => row.horizon === horizon);
      const lane = node("section", { class: "lane", "data-lane": horizon },
        node("div", { class: "lane-head" }, node("h2", {}, readable(horizon)),
          node("span", { class: "muted small", "aria-label": items.length + " initiatives" }, String(items.length))),
        items.length ? items.map(row => roadmapCard(row, horizon)) : node("p", { class: "empty" }, "No initiatives"));
      if (state.edit) connectDrop(lane, horizon);
      return lane;
    })));
}

function togglePresentation() {
  state.presenting = !state.presenting;
  render();
  if (state.presenting) document.documentElement.requestFullscreen?.().catch(() => {});
  else if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}

function showRoadmapReview(proposal, onSaved = () => {}) {
  const review = node("div", { class: "stack" },
    node("p", { class: "muted" }, "Review the proposed changes. Approval opens a confirmation window on this computer."),
    node("div", { class: "review-list" }, proposal.changes.map(change => {
      const title = change.type === "cycle" ? "Create " + change.cycle : proposal.titles[change.initiative];
      const summary = change.type === "cycle"
        ? change.starts_on + " to " + change.ends_on + " · " + change.capacity + " " + change.unit
        : change.action === "plan" ? readable(change.horizon) + " · Rank " + change.rank + " · Effort " + change.effort
          : "Release the current placement";
      return node("article", { class: "review-item" }, node("h3", {}, title), node("p", { class: "small" }, summary),
        change.reason && node("p", { class: "muted small" }, change.reason + " · " + change.source));
    })),
    proposal.documents.map(doc => node("details", {}, node("summary", {}, doc.path), node("pre", {}, doc.text))),
    !state.catalog.signing && node("p", { class: "muted" }, "Start oryx with a local signing key to approve changes."),
  );
  const dialog = modal("Review roadmap proposal", review, [button("Approve on this computer", event => attempt(event, async () => {
    alert("Confirm the proposal in the oryx desktop window.", false, dialog);
    const result = await api("approve", { id: proposal.id });
    if (result.cancelled) {
      alert("Approval cancelled. You can review or approve again.", false, dialog);
      return;
    }
    dialog.close();
    onSaved();
    state.edit = null;
    const created = proposal.changes.find(change => change.type === "cycle");
    if (created) state.cycle = created.cycle;
    await loadBoard();
    render();
    alert("The signed roadmap is up to date.");
  }), "primary", { disabled: !state.catalog.signing })]);
}

async function newCycleDialog() {
  const candidates = state.board.candidates;
  if (!candidates.length) {
    modal("New planning cycle", node("p", {}, "Approve at least one Initiative Brief to compare candidates."));
    return;
  }
  const product = state.product;
  const expectedRoadmap = state.board.revision;
  const starter = await api("comparison-template", { product });
  if (state.screen !== "roadmap" || state.product !== product) return;
  const id = input("", { required: true, pattern: "[a-z0-9]+(?:-[a-z0-9]+)*", placeholder: "q1-renewals" });
  const dates = [input(state.board.today, { type: "date", required: true }), input("", { type: "date", required: true })];
  const capacity = input("", { type: "number", min: 0, required: true });
  const unit = input("", { required: true, placeholder: "Engineer-days" });
  const reason = input("", { placeholder: "Why these selections?" });
  const source = input("", { placeholder: "Planning meeting or document" });
  const sections = Object.fromEntries(comparisonSections.map(name => [name, textarea("", { required: true })]));
  const comparisonNotes = sections.Comparison;
  const comparisonFields = node("div", { class: "wide stack" });
  let extraSections = new Map();
  function showSections(comparison, isTemplate) {
    extraSections = new Map();
    comparisonFields.replaceChildren();
    if (isTemplate) {
      for (const message of starter.notices || []) comparisonFields.append(node("p", {}, message));
    }
    // JSON object keys that look like integers are enumerated first by JS.
    for (const name of comparison.order) {
      const body = comparison.sections[name];
      const standard = comparisonSections.includes(name);
      const control = standard ? sections[name] : textarea("", { required: true });
      const value = name === "Comparison" ? body.split("\n").filter(line => !line.trim().startsWith("|")).join("\n").trim() : body;
      const prompt = isTemplate && value.match(/^\{\{([^{}]+)\}\}$/);
      control.placeholder = prompt ? prompt[1] : "";
      control.value = prompt ? "" : value;
      if (name === "Comparison") {
        comparisonFields.append(node("h2", {}, "Compare approved candidates"), ...entries.map(entry => entry.card));
      }
      if (!standard) extraSections.set(name, control);
      comparisonFields.append(label(name === "Comparison" ? "Alternatives and trade-offs" : name, control, true));
    }
  }
  let comparisonRevision = "absent";
  let loadedId = "";
  const entries = candidates.map(candidate => {
    const include = input("", { type: "checkbox" });
    const assessment = input("", { disabled: true, required: true });
    const horizon = select([["", "Compare only"], ...horizons.map(value => [value, readable(value)])], "", { disabled: true });
    const rank = input("", { type: "number", min: 1, required: true, disabled: true });
    const effort = input("", { type: "number", min: 1, required: true, disabled: true });
    function update() {
      assessment.disabled = horizon.disabled = !include.checked;
      rank.disabled = effort.disabled = !include.checked || !horizon.value;
    }
    include.addEventListener("change", update);
    horizon.addEventListener("change", update);
    const card = node("section", { class: "panel stack wide" },
      node("div", { class: "panel-heading" }, node("h3", {}, candidate.title),
        button("View approved brief", event => attempt(event, async () => {
          const result = await api("candidate", { product, initiative: candidate.id });
          modal(candidate.title, node("pre", {}, result.text));
        }), "compact")),
      node("p", { class: "muted small" }, candidate.outcome),
      node("label", { class: "inline" }, include, "Compare " + candidate.title),
      node("div", { class: "form-grid" }, label("Assessment", assessment, true), label("Selection", horizon),
        label("Rank", rank), label("Effort", effort)));
    return { candidate, include, assessment, horizon, rank, effort, card, update };
  });
  showSections(starter, true);
  const loadExisting = button("Load existing comparison", event => attempt(event, async () => {
    if (!id.reportValidity()) return;
    const result = await api("comparison", { product, cycle: id.value });
    if (result.signed) throw new Error("This cycle already exists. Open its board to change placements.");
    if (!result.text) throw new Error("No saved comparison for that cycle ID.");
    comparisonRevision = result.revision;
    loadedId = id.value;
    showSections(result, false);
    const rows = new Map(result.sections.Comparison.split("\n").filter(line => line.trim().startsWith("|"))
      .map(line => line.split("|").slice(1, 3).map(cell => cell.trim())));
    const unavailable = [...rows.keys()].filter(key => key.includes("/") && !candidates.some(item => item.id === key));
    if (unavailable.length) alert("Review options no longer eligible for a new cycle: " + unavailable.join(", "), true, dialog);
    for (const entry of entries) {
      entry.include.checked = rows.has(entry.candidate.id);
      entry.assessment.value = rows.get(entry.candidate.id) || "";
      entry.update();
    }
  }), "compact");
  const form = formGrid(
    label("Cycle ID", id), node("div", { class: "actions" }, loadExisting),
    label("Period start", dates[0]), label("Period end", dates[1]),
    label("Capacity", capacity), label("Effort unit", unit),
    comparisonFields,
    label("Selection reason", reason), label("Decision source", source),
  );
  const dialog = modal("New planning cycle", form, [button("Save comparison and review", event => attempt(event, async () => {
    if (!form.reportValidity()) return;
    const compared = entries.filter(entry => entry.include.checked);
    if (!compared.length) throw new Error("Choose at least one approved candidate to compare.");
    if (compared.some(entry => entry.assessment.value.includes("|"))) throw new Error("Use prose without table separators in assessments.");
    const options = compared.map(entry => entry.candidate.id);
    const table = ["| Initiative ID | Assessment |", "| --- | --- |",
      ...compared.map(entry => "| " + entry.candidate.id + " | " + entry.assessment.value.trim() + " |")].join("\n");
    const content = Object.fromEntries([...Object.entries(sections), ...extraSections].map(([name, control]) => [name, control.value]));
    content.Comparison = table + "\n\n" + comparisonNotes.value;
    const proposal = await api("roadmap-preview", {
      mode: "new", product, cycle: id.value, revision: expectedRoadmap,
      comparison_revision: loadedId === id.value ? comparisonRevision : "absent",
      starter_revision: starter.revision,
      sections: content, options, starts_on: dates[0].value, ends_on: dates[1].value,
      capacity: Number(capacity.value), unit: unit.value.trim(), reason: reason.value.trim(), source: source.value.trim(),
      placements: compared.filter(entry => entry.horizon.value).map(entry => ({
        initiative: entry.candidate.id, horizon: entry.horizon.value, rank: Number(entry.rank.value), effort: Number(entry.effort.value),
      })),
    });
    loadedId = id.value;
    comparisonRevision = proposal.documents[0].revision;
    showRoadmapReview(proposal, () => dialog.close());
  }), "primary")]);
}

async function loadWork() {
  const command = state.screen;
  const request = ++workRequestNumber;
  const scope = state.scope[command];
  scope.product ||= productOptions(false)[0]?.[0] || "";
  const product = state.catalog.products.find(item => item.id === scope.product);
  scope.initiative ||= Object.keys(product?.initiatives || {})[0] || "";
  const list = scope.product && scope.initiative
    ? await api("work", { ...scope, command, operation: "list" }) : null;
  if (request === workRequestNumber && state.screen === command) state.list = list;
}

function workItems(list, command) {
  return command === "task" ? list.tasks : list.checkpoints;
}

function readinessReasons(reviews) {
  if (!reviews.length) return null;
  return node("ul", { class: "readiness-reasons" }, reviews.map(({ title, reasons }) =>
    node("li", {}, title && node("strong", {}, title), reasons.map(reason => node("p", { class: "small" }, reason)))));
}

function checklistWarnings(list) {
  return Object.entries(list.outstanding).map(([key, reasons]) => {
    const [kind, id] = key.split(":");
    const check = list.checkpoints.find(item => item.id === id);
    return { title: kind === "missing" ? null : check?.title || id, reasons };
  });
}

function workScreen() {
  const command = state.screen;
  const task = command === "task";
  const scope = state.scope[command];
  const list = state.list;
  const product = state.catalog.products.find(item => item.id === scope.product);
  const initiatives = Object.entries(product?.initiatives || {}).sort((a, b) => a[1].localeCompare(b[1]));
  app.append(heading(screenNames[command], null,
    list && !task && list.revision === "absent" && button("Start from template", startChecklist),
    list && button(task ? "Add task" : "Add check", () => workEditor(), "primary")));
  const filter = input(state.filter, { type: "search", placeholder: task ? "Find a task" : "Find a check" });
  const changeScope = (event, key) => attempt(event, async () => {
    scope[key] = event.target.value;
    if (key === "product") scope.initiative = "";
    state.list = null;
    state.filter = "";
    const loading = loadWork();
    render();
    try { await loading; } finally { render(); }
  });
  app.append(node("div", { class: "filters" },
    label("Product", select(productOptions(false), scope.product, { onchange: event => changeScope(event, "product") })),
    label("Initiative", select(initiatives, scope.initiative, { onchange: event => changeScope(event, "initiative") })),
    list && label("Filter", filter),
    list && button("Refresh", event => attempt(event, async () => { await loadWork(); render(); })),
  ));
  if (!list) {
    app.append(node("div", { class: "panel empty" }, "Choose a product and initiative with an existing scope."));
    return;
  }
  if (!task) {
    const ready = list.launch_readiness === "ready for launch decision";
    app.append(node("section", { class: "panel", "aria-label": "Launch readiness" },
      node("div", { class: "panel-heading" }, node("h2", {}, "Launch readiness"),
        badge(list.launch_readiness, ready ? "done" : "pending")),
      readinessReasons(checklistWarnings(list))));
  }
  const output = node("section", { class: "rows", "aria-label": screenNames[command] });
  function updateList() {
    const query = filter.value.trim().toLowerCase();
    const rows = workItems(list, command).filter(row => [row.title, row.status, row.owner, row.phase, row.priority]
      .some(value => value?.toLowerCase().includes(query)));
    output.replaceChildren(...(rows.length ? rows.map(row => {
      const caption = [row.owner || "Unassigned", row.due_on && "Due " + row.due_on, readable(row.priority || row.phase)].filter(Boolean).join(" · ");
      const evidence = row.verification ? row.verification.evidence + " · " + row.verification.by + " · " + row.verification.on
        : row.waiver ? row.waiver.reason + " · " + row.waiver.by + " · " + row.waiver.on : row.resolution;
      const dependency = row.unfinished_dependencies?.length ? "Unfinished dependencies: " + row.unfinished_dependencies.join(", ") : "";
      const supporting = row.task_status ? Object.entries(row.task_status).map(([key, value]) => key + " · " + readable(value)).join(", ") : "";
      return node("article", { class: "row" },
        node("div", {}, node("h3", {}, row.title), node("p", { class: "muted small" }, caption),
          node("p", {}, row.completion_criteria || row.criterion),
          [row.blocked_reason, dependency, supporting, evidence].filter(Boolean).map(value => node("p", { class: "muted small" }, value)),
          row.launch_reviews && node("div", {}, node("strong", {}, "Launch checks to review"), readinessReasons(row.launch_reviews))),
        row.status === "verified" && row.review_issues?.length ? badge("verification needs review", "pending") : badge(row.status), button("Edit", () => workEditor(row), "compact", { "aria-label": "Edit " + row.title }));
    }) : [node("p", { class: "empty" }, query ? "No matching items." : task ? "No tasks yet." : "No checks yet.")]));
  }
  filter.addEventListener("input", () => { state.filter = filter.value; updateList(); });
  updateList();
  app.append(output);
}

function workRequest(command, scope, operation, extra = {}) {
  return api("work", { ...scope, command, operation, ...extra });
}

function commitWork(result, message) {
  state.list = result;
  render();
  alert(message);
}

async function startChecklist(event) {
  await attempt(event, async () => {
    const scope = { ...state.scope["launch-checklist"] };
    const command = "launch-checklist";
    const result = await workRequest(command, scope, "init");
    const dialog = modal("Start a launch checklist", node("div", { class: "stack" },
      result.checkpoints.map(row => node("article", { class: "review-item" },
        node("h3", {}, row.title), node("p", { class: "small muted" }, readable(row.phase)), node("p", {}, row.criterion)))),
      [button("Create checklist", e => attempt(e, async () => {
        const saved = await workRequest(command, scope, "init", { save: true, revision: result.revision, starter_revision: result.starter_revision });
        dialog.close();
        commitWork(saved, "Checklist created.");
      }), "primary")]);
  });
}

function workEditor(row = null) {
  const command = state.screen;
  const task = command === "task";
  const scope = { ...state.scope[command] };
  let revision = state.list.revision;
  let currentRow = row;
  const statuses = task ? ["todo", "in-progress", "blocked", "done", "cancelled"] : ["pending", "blocked", "verified", "waived"];
  const id = input(row?.id, { required: true, disabled: !!row, pattern: "[a-z0-9]+(?:-[a-z0-9]+)*",
    placeholder: task ? "confirm-support-handoff" : "verify-rollback" });
  const title = input(row?.title, { required: true });
  const criterion = input(row?.completion_criteria || row?.criterion, { required: true });
  const status = select(statuses.map(value => [value, readable(value)]), row?.status || statuses[0]);
  const owner = input(row?.owner);
  const due = input(row?.due_on, { type: "date" });
  const source = input(row?.source);
  const rankValues = task ? ["high", "normal", "low"] : ["upstream", "launch", "downstream"];
  const order = select(rankValues.map(value => [value, readable(value)]), row?.priority || row?.phase || (task ? "normal" : "upstream"));
  const links = input((row?.depends_on || row?.tasks || []).join(", "), { placeholder: "task-id, another-task-id" });
  const blocked = input(row?.blocked_reason);
  const resolution = input(row?.resolution);
  const evidence = input(row?.verification?.evidence);
  const verifier = input(row?.verification?.by);
  const verifiedOn = input(row?.verification?.on, { type: "date" });
  const savedBasis = row?.verification?.basis_tasks;
  const basis = select([["all", "All supporting tasks"], ["selected", "Selected supporting tasks"],
    ["independent", "Independent evidence"]], savedBasis === undefined ? "all" : savedBasis.length ? "selected" : "independent");
  const basisIds = input(savedBasis?.join(", "), { placeholder: "task-id, another-task-id" });
  const namedBasis = label("Verification task IDs", basisIds, true);
  const waiver = input(row?.waiver?.reason);
  const approver = input(row?.waiver?.by);
  const waivedOn = input(row?.waiver?.on, { type: "date" });
  const statusFields = {
    blocked: [label("Blocking reason", blocked, true)],
    ...(task ? {
      done: [label("Resolution", resolution, true)],
    } : {
      verified: [label("Verification evidence", evidence, true), label("Verified by", verifier), label("Verified on", verifiedOn),
        label("Evidence basis", basis), namedBasis],
      waived: [label("Waiver reason", waiver, true), label("Approved by", approver), label("Approved on", waivedOn)],
    }),
  };
  const latest = node("section", { class: "wide stack", hidden: true });
  const form = formGrid(
    label("Stable ID", id), label("Title", title), label(task ? "Completion criteria" : "Verification criterion", criterion, true),
    label(task ? "Priority" : "Phase", order), label("Status", status),
    label("Owner", owner), label("Due date", due), label("Source", source, true),
    label(task ? "Dependency task IDs" : "Supporting task IDs", links, true),
    Object.values(statusFields).flat(), latest,
  );
  function update() {
    for (const [value, fields] of Object.entries(statusFields)) {
      const visible = status.value === value || value === "done" && status.value === "cancelled";
      for (const field of fields) {
        field.hidden = !visible;
        field.lastChild.required = visible;
      }
    }
    namedBasis.hidden = task || status.value !== "verified" || basis.value !== "selected";
    basisIds.required = !namedBasis.hidden;
    owner.required = ["done", "verified"].includes(status.value);
  }
  basis.addEventListener("change", update);
  status.addEventListener("change", update);
  update();
  const dialog = modal(row ? "Edit " + row.title : task ? "Add task" : "Add check", form, [
    button("Check current record", event => attempt(event, async () => {
      const current = await workRequest(command, scope, "list");
      if (current.revision === revision) {
        alert("You have the current revision.", false, dialog);
        return;
      }
      const item = workItems(current, command).find(entry => entry.id === id.value);
      latest.hidden = false;
      latest.replaceChildren(node("h3", {}, "Current saved record"));
      if (item) latest.append(node("pre", {}, JSON.stringify(item, null, 2)));
      if (!row && item) {
        latest.append(node("p", {}, "This ID is in use. Choose a different ID to add your item."));
        return;
      }
      if (row && !item) {
        latest.append(node("p", {}, "This item is missing from the current list. Review the list before editing."));
        return;
      }
      latest.append(actions(button("Use current revision", () => {
        revision = current.revision;
        currentRow = item;
        latest.hidden = true;
        alert("Your edits are ready for another preview.", false, dialog);
      })));
    }), "ghost"),
    button("Preview edit", event => attempt(event, async () => {
      if (!form.reportValidity()) return;
      const clean = control => control.value.trim() || null;
      const fields = {
        title: title.value.trim(), owner: clean(owner), due_on: clean(due), source: clean(source),
        status: status.value, blocked_reason: status.value === "blocked" ? clean(blocked) : null,
      };
      const readIds = control => control.value.split(",").map(value => value.trim()).filter(Boolean);
      const ids = readIds(links);
      if (task) Object.assign(fields, {
        completion_criteria: criterion.value.trim(), priority: order.value, depends_on: ids,
        resolution: ["done", "cancelled"].includes(status.value) ? clean(resolution) : null,
      });
      else Object.assign(fields, {
        criterion: criterion.value.trim(), phase: order.value, tasks: ids,
        verification: status.value === "verified" ? { evidence: clean(evidence), by: clean(verifier), on: clean(verifiedOn) } : null,
        waiver: status.value === "waived" ? { reason: clean(waiver), by: clean(approver), on: clean(waivedOn) } : null,
      });
      if (fields.verification && basis.value !== "all") {
        fields.verification.basis_tasks = basis.value === "independent" ? [] : readIds(basisIds);
        if (basis.value === "selected" && !fields.verification.basis_tasks.length) throw new Error("Select at least one supporting task ID.");
      }
      const comparable = value => JSON.stringify(value && typeof value === "object" && !Array.isArray(value)
        ? Object.keys(value).sort().map(key => [key, value[key]]) : value);
      const changed = row ? Object.fromEntries(Object.entries(fields).filter(([key, value]) =>
        comparable(value) !== comparable(row[key]))) : fields;
      if (!Object.keys(changed).length) throw new Error("Change a field before reviewing the edit.");
      const request = { revision, changes: [{ id: id.value, action: row ? "update" : "add", fields: changed }] };
      const proposed = await workRequest(command, scope, "apply", request);
      const edited = workItems(proposed, command).find(item => item.id === id.value);
      const concerns = task ? edited.launch_reviews || [] : checklistWarnings(proposed);
      function display(value) {
        if (value == null) return "—";
        if (Array.isArray(value)) return value.join(", ") || "—";
        if (typeof value !== "object") return String(value);
        return Object.entries(value).map(([key, detail]) => {
          if (key !== "basis_tasks") return detail;
          return detail.length ? "Verification tasks: " + detail.join(", ") : "Independent evidence";
        }).join(" · ");
      }
      const review = modal("Review " + title.value.trim(), node("div", { class: "stack" },
        concerns.length > 0 && node("section", { "aria-label": "Launch checks to review" },
          node("h3", {}, "Launch checks to review"), readinessReasons(concerns)),
        Object.entries(changed).map(([key, value]) => node("article", { class: "review-item" },
          node("h3", {}, readable(key.replaceAll("_", "-"))),
          currentRow && node("p", { class: "muted small" }, "Before: " + display(currentRow[key])),
          node("p", {}, display(value))))), [button("Save edit", e => attempt(e, async () => {
        const result = await workRequest(command, scope, "apply", { ...request, save: true });
        review.close();
        dialog.close();
        commitWork(result, task ? "Task saved." : "Check saved.");
      }), "primary")]);
    }), "primary"),
  ]);
}

async function navigate(screen) {
  if (state.screen === screen) return;
  if (state.edit && !window.confirm("Discard the current roadmap preview?")) return;
  state.screen = screen;
  const address = new URL(location.href);
  address.searchParams.set("screen", screenPaths[screen]);
  history.replaceState(null, "", address);
  state.edit = null;
  state.filter = "";
  state.list = null;
  if (screen === "roadmap") state.board = null;
  render();
  try {
    if (screen === "roadmap") await loadBoard();
    else await loadWork();
  } finally { render(); }
}

function enterSetup(current) {
  state.setup = current;
  state.board = state.list = state.catalog = state.edit = null;
  state.presenting = false;
  boardRequest++;
  workRequestNumber++;
  document.querySelectorAll("#dialogs dialog").forEach(dialog => dialog.close());
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  render();
}

function setupScreen() {
  const current = state.setup;
  const stage = { company: "Company context", pm: "PM context", product: "Product context" }[current.stage];
  app.append(heading("Continue onboarding", `You can return to ${screenNames[state.screen]} after the walkthrough.`),
    node("section", { class: "panel stack" },
      node("h2", {}, stage || "Your walkthrough"),
      node("p", {}, current.prompt),
      current.stage_available !== false && node("p", {}, "Continue in your oryx conversation. You can leave questions open."),
      actions(button("Check progress", event => attempt(event, openWorkspace)))));
}

function render() {
  document.body.classList.toggle("presenting", state.presenting);
  if (state.setup) {
    nav.replaceChildren();
    document.querySelector(".header-end").replaceChildren();
    app.replaceChildren();
    setupScreen();
    return;
  }
  nav.replaceChildren(...Object.entries(screenNames).map(([screen, text]) =>
    button(text, event => attempt(event, () => navigate(screen)), "ghost", {
      "aria-current": state.screen === screen ? "page" : null,
    })));
  const headerEnd = document.querySelector(".header-end");
  headerEnd.replaceChildren(...(state.presenting ? [button("Exit presentation", togglePresentation)] : []));
  app.replaceChildren();
  if (state.screen === "roadmap") roadmapScreen();
  else workScreen();
}

async function openWorkspace() {
  state.catalog = await api("catalog");
  state.setup = null;
  try {
    if (state.screen === "roadmap") await loadBoard();
    else await loadWork();
  } finally { render(); }
}

attempt(null, openWorkspace);
