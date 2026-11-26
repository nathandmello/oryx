# Stakeholder evidence bundle

Use this bundle for the optional offline stakeholder comparison. Save the manifest and registration digests before collection. Evidence references use a bundle-relative `path` and the SHA-256 digest of the file bytes in `sha256`.

## Files

| File | Required evidence |
| --- | --- |
| `registration.json` | Frozen study design, candidate and reference commit IDs, manifest digest, calibration and source-review digests |
| `reader-a-source.json`, `reader-b-source.json` | Each reader’s source-only labels and evidence rationale, indexed by held-out case and variant |
| Registered source adjudication | Resolved labels and rationale for every held-out case, bound to the frozen bytes |
| `observer.json` | Registration pin, known-answer runs, blinded ID mapping, deployment observations, timed sessions and integration capture references |
| `reader-a-blind.json`, `reader-b-blind.json` | Registration pin and independent coded outputs indexed by anonymous ID |
| `adjudication.json` | Registration pin, observer and review hashes, resolved findings, effect grades, timing grades and disagreements |

## Records

Set `protocol` to `oryx-stakeholder-study/v2` and `comparison_mode` to `matched-codex-repo-harness`. Each Codex setup pins its client version, model revision, tools, settings and hub revision.

| Deployment | Registered use |
| --- | --- |
| `oryx-codex-harness`, `ref-codex-harness` | Matched semantic trials and matched timing. Both use the comparison mode and identical harness bytes. Set `harness_sha256` and supply the registration's `harness` file reference. |
| `oryx-codex-native`, `oryx-codex-native-off` | Protected native latency and subscriber comparison. Set `mode` to `protected-native`. Only the boolean `subscriber` setting differs. |

Register both `client_adapters` with `client`, `revision`, `client_version`, and `hooks_sha256`. Register `parity_source_hashes` from the reviewed commit and `parity_runner_sha256` from the runner used in the study.

For each host, `observer.shared_core[host]` holds the parity `report` and `launch` references plus the observed `runner_sha256`. The adjudicator supplies `evidence`, `result`, and `critical` for the same host. Verify the runner, checkout and invocation independently. The scorer checks executed paths, effects, record digests, host and candidate for both clients.

Freeze repeats, timeout, native budgets, claim cap, consequential dimensions, timing schedule, trial order and repeat pairing. Register each timing original’s distinct source digest and source-reviewed boolean `negative` label. Match both across deployments.

Identify semantic runs by `CASE/ARM/REPEAT`. Record a unique session, submission timestamp, setup and input hashes. Timestamp submissions, PM turns, reply text, human and model intervals, approvals, handoffs and terminal events with one monotonic clock. Include timeouts.

Capture stage snapshots, actual reads and transport effects, launch, transcript, tools, model inputs and retrieval. Map paths to entry modes and content digests. Log each action, stage, reviewed-record status and trace.

For each supported finding, store a canonical meaning, disposition, support and durable-proposal flags, output evidence, and the frozen source's UTF-8 byte offsets and exact quote. Match paraphrases only when their consequential meaning agrees. Preserve unsupported meanings for comparative scoring.

A wholly negative source can still require a warranted question or an explicit statement that attribution remains unknown. Register that obligation as non-durable. Grade the actual abstention separately. Reserve `route` for handoff to a different owner and `propose` for a requested change presented for review.

Use `park` for an open question and `ask` for warranted clarification. Register both when either serves the request.

Register foreground framing with the workflow rubric. Historical concerns can shape a clinic demo. Filing them requires separate authorization. Trace missing decisions and absent-reader reactions separately.

Record the expected changed paths and resulting fingerprints per stage.

The third reader resolves disagreements against the source and records each rationale. Calibrate the rubric on development material. Keep source reviews, blind judgments and adjudication separate. Keep the original source labels.

The adjudicator grades critical failures, consequential dimensions and effects. Record observations for each host, client and integration scenario. [Scorer](stakeholder_release.py)

## Statistics

The scorer reports pooled precision, recall, F1 and raw counts. It clusters repetitions by original for confidence bounds. Include transformed cases when examining critical failures and effects. Count each original once for confidence bounds.

Sample independent originals from one target distribution per coaching workflow and timing stratum. Use exact one-sided 95% bounds for binary coaching. For independent original means in [0,1], invert the one-sided Bernoulli KL Chernoff bound at fixed sample size. Use its lower bound for agreement. For each paired difference, bound the mean negative part above. Its negative bounds the mean difference below.

For source-truth ratios, normalize each original's errors and denominator by its registered maximum. Divide the 97.5% upper error bound by the 97.5% lower denominator bound. Subtract from one.

For latency ratios, use a 97.5% upper numerator and 97.5% lower denominator order-statistic bound. When a denominator or bound is missing, the timing comparison cannot meet its threshold.
