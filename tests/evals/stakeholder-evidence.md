# Stakeholder evidence bundle

A release operator pins both checksums outside the candidate. Use the trusted scorer installation. The candidate cannot supply a trusted PASS. Four distinct public keys authenticate the observer, two readers and an independent adjudicator. Keep private keys off client machines.

## Files

| File | Required evidence |
| --- | --- |
| `registration.json` | Frozen study design, candidate and reference commit IDs, manifest digest, public key digests, independent calibration and source-review digests |
| `keys/ROLE.pem` | Public verification key with the pinned PEM byte digest |
| `reader-a-source.json`, `reader-b-source.json` | Each reader's source-only keys and evidence rationale, indexed by held-out case and variant |
| Registered source adjudication | Final key and explanation for every case, bound to the frozen bytes |
| `observer.json` | Registration pin, known-answer runs, blinded ID mapping, native observations, timed sessions and integration capture references |
| `reader-a-blind.json`, `reader-b-blind.json` | Registration pin and independent coded outputs indexed by anonymous ID |
| `adjudication.json` | Registration pin, observer and review hashes, resolved findings, effect grades, timing grades and disagreements |
| `FILE.ROLE.sig` | Detached signature of the exact file bytes under that role's pinned key |

Sign externally with `openssl dgst -sha256 -sign PRIVATE_KEY -out FILE.ROLE.sig FILE`. File references contain relative `path` and `sha256` fields. Keep all referenced files inside the observer bundle.

## Records

Each setup specifies hub revision, client, executable version, model and revision, tools and settings. Register `oryx-claude`, `ref-claude`, `oryx-codex` and `oryx-codex-off`. The Codex pair differs only by its boolean subscriber setting. The first two use identical client settings.

Registration fixes the number of repeats, timeout in milliseconds, calibrated Codex budgets, maximum material claims per artifact and consequential dimensions per workflow. Store the paired trial order and reference-repeat pairing. Each timing deployment identifies its operating point, original, pinned source digest, and warm or cold stratum. Independent inputs cannot share source bytes within a stratum.

A semantic run has the key `CASE/ARM/REPEAT`. The observer records a distinct session ID, submission timestamp, setup, input hashes and event stream. Collect monotonic milliseconds and event kind for every submission, PM turn, reply, model interval, human interval, approval, handoff and terminal state. Include actual reply text. Timeouts count against completion and latency.

A run includes before-and-after snapshot references for every stage, actual access and transport effects, launch capture, transcript, tool trace, model-bound inputs and retrieval trace. Each filesystem snapshot maps relative paths to their entry mode and content digest. The observer's effect log identifies the action, stage, reviewed-record status, and original trace.

Readers grade each observation and effect against its independent capture. For each supported finding, store a canonical meaning, disposition, support and durable-proposal flags, output evidence, and the frozen source's UTF-8 byte offsets and exact quote. Match paraphrases only when their consequential meaning agrees. Preserve unsupported meanings for comparative scoring.

A wholly negative source can still require a warranted question or an explicit statement that attribution remains unknown. Register that obligation as non-durable. Grade the actual abstention separately. Reserve `route` for handoff to a different owner and `propose` for a requested change presented for review.

Use `park` when evidence preserves an open question without requiring a PM reply. Use `ask` when the pending task warrants clarification. Register both if either outcome serves the PM's request. A judge codes the action the operator actually observed.

For a reader-specific clinic demo, foreground framing can surface two different historical concerns. Filing either one needs separate authorization. A missing decision or an absent reader’s reaction can matter in the reply while creating no durable stakeholder claim. Register foreground requirements with the activity rubric and trace their effect separately.

Record the expected changed paths and resulting fingerprints per stage.

An independent third reader resolves material disagreements against the source and records each rationale. Development-only reader agreement calibrates the rubric. Keep source reviews, blind output judgments and adjudication separate. Preserve the frozen hidden keys after candidate feedback.

The adjudicator resolves critical failures, consequential dimensions and expected effects. Signed observation receipts cover each supported host, client and integration scenario listed in the scorer. A self-reported status alone cannot satisfy a gate. Review the complete input schema in the executable scorer. [Scorer](stakeholder_release.py)

## Statistics

The scorer publishes pooled precision, recall, F1 and raw counts. It clusters repetitions by original for confidence bounds. Split transformations affect critical and effects gates. They do not enlarge the independent sample.

Use exact one-sided 95% bounds for binary coaching outcomes. Use one-sided Hoeffding bounds for comparative means, paired differences and bounded source-truth ratios. For latency ratios, use a 97.5% upper numerator and 97.5% lower denominator order-statistic bound. A missing denominator or bound holds release.
