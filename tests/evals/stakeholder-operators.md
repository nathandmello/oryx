# Run the stakeholder study

Use three isolated accounts or machines for operators, reviewers, and the evidence recorder. Keep the candidate and reference in separate native workspaces. Only the recorder can write observation bundles. Keep answer keys, prior runs, reviewer private keys, and other Studios outside every client mount. A shared Unix account cannot enforce this boundary.

## Register before collection

Use original fictional material. Include 12 development and 48 independent held-out artifacts across six families. Keep transformed versions with their originals. Freeze source bytes, requests, dates, scoped grants, equivalent native seed records, PM responses and proposed source keys.

```sh
python3 -B tests/evals/stakeholder_corpus.py freeze /study/originals.jsonl /study/frozen
python3 -B tests/evals/stakeholder_corpus.py packet /study/frozen "$MANIFEST_PIN" "$CASE" /operator/inbox
```

Distribute the printed manifest checksum separately. Each case packet contains the source, request and logical seed instructions. Provision seed records through each hub's native surface. Keep provisioning instructions and the response script with the operator.


Mount only authorized source bytes and the seeded hub. Submit the verbatim request. Never send the case ID, family, rubric, or expected destination.

Two readers label each source independently before seeing output. Record required meanings, permissible alternatives, prohibited propositions, speaker or intermediary, exact evidence, uncertainty, scope and legitimate silence. Adjudicate disagreements against the source. Freeze the resolved keys, signed reviews and rubric before collecting outputs.

Use separate development trials to set budgets, independent sample sizes, claim bounds, operating points, rubric dimensions and stopping rules. Freeze them in registration. The breadth floor does not establish statistical power. Any holdout-informed change requires a fresh confirmation set. Preserve earlier attempts.

## Run both clients

Pin the candidate and reference revisions, executable versions, model revisions, tools and settings. Prove the documented normal entry points using development known answers. Start Oryx through its protected launcher.

```sh
python3 tools/pm.py agent claude
python3 tools/pm.py agent codex
```

Use the reference hub's documented Claude Code entry point, with the same Claude model and client. Alternate hub order by sorted held-out case and repeat, beginning with Oryx. Use separate workspaces for three fresh trials each. Compare each reference repeat with the next cyclic repeat. Run Oryx-only source, effects and downstream benchmarks on Codex.

Submit one PM turn at a time. Apply only the scripted response appropriate to the observed request. Capture intake, candidates, visible preview, approved effects, replay and fresh-session reuse. Preserve unobservable internal stages. Observe tool calls, actual reads, model-bound input, and external test transport from outside the client.

Capture each controlled filesystem at baseline, preview, outcome, retry and fresh use. Include the private journal root in the recorder's scope. Fingerprint ignored files and symlinks. Record Git state separately when relevant.

```sh
python3 -B tests/evals/stakeholder_corpus.py snapshot /run/observed-volumes /recorder/baseline.json
```

Use independent monotonic event capture from PM submission. Mark grounded first results, warranted questions, or correct completed abstentions. Record common-work completion, elapsed human and model time, PM turns, and approval or handoff overhead. Include failed completions and timeouts. Run independent, matched warm and cold latency sessions. Preserve at least 100 distinct originals per stratum.

## Grade and decide


Randomize opaque output IDs. Remove hub identities and launch metadata from judge copies. Keep exact source spans, quotations, and observable actions. Both judges code every material finding, including duplicates and false positives.

Canonical meanings require matching person, speaker, evidence, qualifiers, time and scope. Code disposition separately. An absence of visible findings does not establish correct abstention.

Grade consequential coaching dimensions against the PM's purpose. Check critical objections and fresh-session evidence. A third reader resolves disagreements. Record a rationale, independent trace, and actual filesystem delta for each effect. Independently verify the full protected host matrix, privacy, installation and recovery.

```sh
python3 -B tests/evals/stakeholder_release.py /study/frozen "$MANIFEST_PIN" /recorder/evidence "$REGISTRATION_PIN"
```

Use exit status and the signed independent evidence. A missing, failed or inconclusive gate holds release. The scorer emits counts, bounds, failures and timing details for complete bundles. Keep evidence private. Publish only the authorized reviewer receipt. [Bundle format](stakeholder-evidence.md)
