# Workspace customization

Use a workflow rule for agent judgment. Use a template or view change when the generated artifact or app must change.

## Apply a change

Run `python3 tools/pm.py customize show`. Read the revision and effective settings.
Send a JSON merge patch through standard input to `python3 tools/pm.py customize apply`.

Use the returned revision for your next edit. A stale edit requires a fresh read.
A null property removes its workspace override. Lists replace the previous list. Omitted settings continue to inherit from core.

This example adds a brief section, a choice field, and a grouped roadmap table.

```json
{
  "revision": "<revision from customize show>",
  "config": {
    "templates": {
      "initiative-brief": {
        "Risks and assumptions": {
          "prompt": "Which remaining risk could change this decision?",
          "before": "Sources"
        }
      }
    },
    "fields": {
      "x-confidence": {"type": "choice", "label": "Confidence", "choices": ["Low", "Medium", "High"]}
    },
    "views": {
      "review": {
        "title": "Decision review", "layout": "table", "group": "areas",
        "columns": ["title", "x-confidence", "*"], "hidden": ["effort"],
        "labels": {"title": "Initiative"}, "density": "compact"
      }
    },
    "default_view": "review"
  }
}
```

## Draft templates

Template keys match the Markdown filenames under `templates/`, without the extension.
Use `add` to set a section’s contents and position. Use `append` to extend a section or `replace` to change its body.

Set the operation under `mode`. For additions, `before` defaults to Work state.
Use `content` instead of `prompt` for a Markdown table, list, or subsection in a work artifact.
Changing between a prompt and a table preserves the section’s position. Each product can choose its own format.

Studio settings override corresponding core settings, including core product defaults. Other properties still inherit.

Keep core identity, filing, evidence, and approval sections intact.
If an update removes a saved anchor, new drafts flag the fallback position near Work state. Studio keeps the requested anchor.

New records inherit current prompts. Existing drafts and approved files retain their original bytes.

Discovery approval covers additional sections in the reviewed plan. If a section changes, review the revised plan with the PM.
Use the findings section for results collected during the timebox. Brief answer sections containing a literal starter
ask the PM to complete it before review. The browser’s planning cycle form includes product-specific comparison sections.

Product-specific settings belong under `config.products.<product>`. Set `templates` for product-owned draft paths or `default_view` for that product’s roadmap.
Portfolio exports use the workspace default. Explicit view selections take precedence.

## Launch checklist starters

Under `config.checkpoints`, key starter changes by checkpoint ID. Set `title`, `phase`, or `criterion`.
Use `{"omit":true}` to exclude a starter row. Keep upstream, launch, and downstream coverage.
Product choices can override the workspace starter under `products.<product>.checkpoints`.

Preview with `launch-checklist init --preview`. The browser verifies the previewed starter before creating a checklist.
Existing checklists retain their rows, evidence, and history.

## Roadmap data and views

Use a stable field ID starting with `x-`. Supported types are text, number, boolean, date, choice, and multiple.
Use ISO dates and supply a list of choices for choice or multiple.
Edit values in a customized browser view or send `values` alongside a configuration patch.

```json
{"revision":"<revision>","values":[{"product":"example","id":"<registered initiative ID>","field":"x-confidence","value":"High"}]}
```

Use null to clear a value. Hiding, relabelling, or reordering a column preserves its values.
Clear or convert incompatible data explicitly when changing a field type. Apply related edits together.

Settings and values share `settings.json` in the Workspace’s [customization folder](../README.md#placement).
Custom fields travel with their initiative across cycles. The PM reviews planning decisions through the usual approval workflow.
Put the figures behind a decision in its approved comparison when you need their historical values.

Select a named view in the browser or pass `--view review` to `pm.py roadmap`.
Use `--view core` for the original columns and layout.

Choose board or table, an optional grouping field or `none`, and ordered columns.
An asterisk includes other fields, including future additions. Product, cycle, and area filters still apply.

List each permitted column explicitly for customer views. Check the grouping field before presenting.
JSON, CSV, and Markdown exports use the selected columns. Edit priorities opens the planning board.

## Bespoke interfaces

For a custom standalone interface, save HTML under `views/<name>.html` in that customization folder.
Include one `<!-- pm:roadmap-data -->` marker. Set the view's `page` to that name.

Export with `python3 tools/pm.py roadmap --view review --format html`. Save the output in the private workspace.
Read the embedded JSON from the `pm-roadmap` element. It contains column labels and the projected rows.

In the browser, **Download custom view** exports the current cycle and area filter.
Choose the view and area before entering Present. A changed export definition or page requires a refresh.

Open the exported file separately. Export again for fresh data. Keep sensitive exports private.
Custom page code runs only when someone opens the exported file.

## Updates and feedback

Alignment compares workspace settings with [core defaults](customization-defaults.json). Matching definitions retire into private history.
Field values remain available when core takes over a definition. Partial and uncertain matches remain active.
Use [override reporting](overrides.md) for requested improvements. Use identifiers such as `fields/x-confidence`, `views/review`, or `templates/initiative-brief`.

Only approved public wording goes to GitHub. Stored field values and private templates stay local.
