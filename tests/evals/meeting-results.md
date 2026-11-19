# Transcript evaluation, November 19, 2026

Fresh agent sessions ran six requests against five public meeting transcripts. Each session received its own disposable Hub, the user request, and the applicable source. The sessions shared a host. The generator workspaces excluded grading criteria, expected answers, and other runs.

An independent agent compared the replies and saved records to the source passages. All 23 content criteria passed. The file checker passed for all six runs and the separate replay.

| Case | Result | What the agent did |
| --- | --- | --- |
| GitLab product | 4/4 | Captured the interview goal, kickoff guidance, open format choice, and completed planning-label rename. |
| GitLab engineering staff | 4/4 | Credited both reporting owners after a correction. Distinguished the current reorganization from the possible future team split. |
| Open edX maintenance | 4/4 | Filed the agreed sequencing and the migration test owner. Kept the ship date and test outcome open despite caption errors. |
| W3C governance | 4/4 | Filed all three resolutions, including all conditions for a non-editorial merge, with citations. |
| W3C test-suite call | 4/4 | Identified issuer-suite limits, the open scheduling poll, and the TPAC cancellation confirmed at the end. |
| W3C scheduling excerpt | 3/3 | Kept both cancellations tentative using only the supplied passage. |
| Governance replay | Passed | A new session found the existing note. Hashes of all private records matched the first capture. |

Both ingestions updated the intended initiative overview, added one dated note, and updated the private checkpoint. All four summary requests left the private records intact.

## Retrieval and citation findings

The first W3C governance run retrieved the pinned file over HTTP despite an available GitHub connector. Its content and filing scores passed.

After a skill edit, a fresh agent called the GitHub connector but also fetched a second copy over HTTP. Both calls succeeded. The Hub now gives connector guidance at session start, before the agent opens a source. The skill reuses connector content for parsing and filing.

The final retest used the original prompt and the Hub's generated session-start context. The agent made five GitHub `fetch_file` calls and zero direct HTTP requests. It parsed the connector response, verified the three decisions, and filed the overview and dated note. All file checks passed.

The Open edX reply mentioned an out-of-scope feedback request without a line locator. Lines 68–78 support the statement. The filed release findings have locators.

The Open edX input preserves all 83 dialogue and timing lines, including empty speaker turns. Its source wiki also contains an agenda and recording duration.

Evaluation covered public GitHub retrieval and supplied transcript files. Private Notion and ChatGPT Record retrieval, live pagination on those services, and audio transcription remain untested.

## Connector clarification

A separate eval supplied two fictional matches for the same review. A fresh agent asked whether to use the March 4 Teams meeting or the March 6 Google Drive transcript. It identified the agenda for each choice and waited. The agent reported zero connector calls, and the before-and-after file hashes matched. Both clarification criteria passed.

The [case manifest](meeting_cases.json) includes source URLs and hashes. The [criterion results](meeting-grades.json) give evidence for each judgment.
