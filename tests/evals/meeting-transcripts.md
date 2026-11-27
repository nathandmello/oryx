# Meeting transcript evals

Use fresh agent sessions to exercise the installed skill against public calls. Each run gets a separate Hub and private repository.

| Case | Input and expected behavior |
| --- | --- |
| `product` | GitLab product call. Distinguish interview goals, accepted kickoff materials, open format choices, and a completed label change. |
| `staff` | GitLab engineering staff call. Track acting roles, reporting ownership, and the timing of a reorganization. |
| `engineering` | Open edX maintenance call. Ingest a noisy transcript with interrupted turns, misheard release names, and a tentative migration schedule. |
| `resolutions` | W3C VC API call. Retrieve the pinned GitHub source and file decisions in the initiative overview and a dated note. |
| `noisy-full` | W3C test-suite call. Use the full transcript, including the closing update that settles one scheduling question. |
| `excerpt` | Use only the scheduling excerpt of that call. Both cancellations are tentative at this point. |
| `ambiguous-source` | Two fictional catalog entries match across Teams and Google Drive. Ask which meeting to ingest and wait before retrieval or filing. |
| Replay | Give a fresh agent the same capture request and the records created on the first run. |

The [manifest](meeting_cases.json) records prompts, URLs, content hashes, and the excerpt boundaries. The GitLab samples are third-party transcriptions of GitLab Unfiltered recordings. The wiki and W3C pages are publisher sources. Grade against the supplied text.

## Run a case

1. From the oryx root, prepare a new directory outside the checkout. The harness copies the shared Hub and omits eval files.
2. Start an agent with fresh conversation context in the generated `hub/`. Supply the text of `prompt.txt` as its request.
3. Give the agent access to its own Hub, the supplied input, and an authorized reader for the requested public source.
4. Keep other runs, evaluation criteria, and prior replies outside the agent's inputs. Save its final reply beside `prompt.txt`.
5. Run the file checks. Give a separate reviewer the output, source, and [rubric](meeting_rubric.json).
6. Score each criterion as pass, partial, or fail. Cite the source passage and the agent's claim. Flag other material errors separately.

Use the Hub's normal session-start hook. For an agent runner without hook support, deliver its generated startup context to the fresh session.

For URL retrieval, inspect the tool history. Verify the agent used an available authorized reader for the confirmed source or reported the missing capability.

```sh
python3 tests/evals/meeting_transcripts.py prepare product /tmp/meeting-product
codex exec --ephemeral --sandbox workspace-write -C /tmp/meeting-product/hub \
  --output-last-message /tmp/meeting-product/reply.md - < /tmp/meeting-product/prompt.txt
python3 tests/evals/meeting_transcripts.py check product /tmp/meeting-product
```

The Open edX case uses the dialogue from the [public meeting page](https://openedx.atlassian.net/wiki/spaces/COMM/pages/4519067649/2024-10-03%2BMeeting%2Bnotes). Save the full transcript section from the web reader, including its heading and ending time. The tested reader request used line 294 and a long response. Supply the saved text with `--source-view`. The harness preserves empty turns and checks the resulting hash.

```sh
python3 tests/evals/meeting_transcripts.py prepare engineering /tmp/meeting-engineering --source-view /tmp/wiki-view.txt
```

For a cached sample, use `--source-file` with the reviewed bytes. The harness verifies the checksum before using any input.

## Replay a capture

```sh
python3 tests/evals/meeting_transcripts.py replay resolutions /tmp/meeting-replay --prior-run /tmp/meeting-resolutions
# Run another fresh agent with /tmp/meeting-replay/hub as its workspace.
python3 tests/evals/meeting_transcripts.py check resolutions /tmp/meeting-replay
```

The checker validates Hub structure and compares file hashes. It checks the expected initiative overview, dated note, and allowed checkpoint updates. Summary cases require unchanged records. Replay compares the original and final evidence bytes.

See the [recorded evaluation](meeting-results.md) for observed outcomes.
