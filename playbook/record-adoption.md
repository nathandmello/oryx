# Adopt a Workspace or restore selected records

Use the PM’s local Linux terminal. Keep the original Workspace offline during the operation. Choose an empty, owner-only parent directory outside Core and other Git repositories. Give each output a new name in that directory.

## Adopt an existing 0.16.0 Workspace

Adoption supports the 0.16.0 format-2 layout and self-contained Git repositories. The preview lists file paths, content revisions, logical names and opaque files. Read the plan locally and save its digest.

```sh
"$ORYX_CORE/bin/oryx" workspace adoption-preview "$ORIGINAL" "$NEW_WORKSPACE"
"$ORYX_CORE/bin/oryx" workspace adopt "$ORIGINAL" "$NEW_WORKSPACE" \
  --backup "$LOCAL_BACKUP" --expect "$PLAN_DIGEST"
export ORYX_WORKSPACE="$NEW_WORKSPACE"
"$ORYX_CORE/bin/oryx" workspace record-list
```

Adoption creates and verifies a machine-local backup before publishing the separate owner-only copy. The copy retains Git objects, refs, the index, uncommitted and ignored files, and source bytes. Keep that backup and its reviewed inventory private. The backup contains private history and can include secrets.

The copy assigns IDs to eligible records. Existing callers and approval receipts keep their original paths. A purpose-based name can resolve to the same record. For an indexed record, request its current path, an exact historical revision or a link from that revision.

```sh
"$ORYX_CORE/bin/oryx" workspace record-resolve "$RECORD_ID" --revision "$SHA256"
"$ORYX_CORE/bin/oryx" workspace record-citation "$RECORD_ID" "$ORIGINAL_HREF" --revision "$SHA256"
```

After editing records, review the output of `workspace record-list`. Use its digest with `workspace record-refresh --expect` to register the reviewed revisions. Use `workspace record-move ID NEW_PATH --expect REVISION` for independent domain records. A caller-bound path, unresolved transfer or ambiguous citation requires separate review. Historical-only deleted files remain available in the local Git history.

## Move selected work to another machine

Portable export creates a new private Git history from reviewed text. Select the audience, files and any historical SHA-256 revisions. Save the selection as a private JSON file outside the Workspace.

```json
{"audience":"My replacement laptop","lineage":"new-private-history","files":{"pm-notes.txt":[],"context/company/overview.md":[]}}
```

Review the committed, staged and working revisions, historical selections, aliases and omissions. Each file can disclose customer information. Check its actual text for the named recipient. Export can hold credential-like data, protected sources, unresolved grants and incomplete approval receipts. Keep the local backup for full history.

```sh
"$ORYX_CORE/bin/oryx" workspace portable-preview "$PORTABLE" < "$SELECTION"
"$ORYX_CORE/bin/oryx" workspace portable-export "$PORTABLE" \
  --expect "$SELECTION_DIGEST" < "$SELECTION"
"$ORYX_CORE/bin/oryx" workspace portable-restore "$PORTABLE" "$DESTINATION" \
  --expect "$MANIFEST_DIGEST"
```

Take the manifest digest from the successful export. Carry it through a trusted separate channel and protect the archive in transit. Restore publishes a separate Workspace with the selected bytes, stable IDs and Git layers. Core supplies any missing starter guides.

Restored protected notes retain their governing status in a fresh local generation. Select a still-pending note draft and its exact base notes to carry it into the local review queue. Select a source-independent workflow checkpoint and its owning handoff together to resume the reviewed step. Earlier approvals, writing grants and pending sends stay on the source machine.

Old refs, raw Git objects, all host state, credentials and unselected historical revisions stay local. An old citation whose target revision was omitted reports that it cannot verify the target. Repeating a completed restore preserves later edits in the destination.
