# Run the stakeholder study

Use three isolated accounts or machines for operators, reviewers, and the evidence recorder. Keep the candidate and reference in separate workspaces. Only the recorder can write observation bundles. Keep answer keys, prior runs, reviewer private keys, and other Studios outside every client mount. A shared Unix account cannot enforce this boundary.

## Register before collection

Use fictional material or lawfully reusable public professional records. Record the source URL, license and discussion ID for public inputs. Remove unnecessary personal data. Use fictional PM requests and seeds when appropriate. Group mirrors, extracts and related sessions under one original. Keep provenance in the private manifest.

Include at least 12 development and 48 independent held-out originals across six families. Freeze source bytes, requests, dates, scoped grants, equivalent native seed records, PM responses and proposed source keys.

```sh
python3 -B tests/evals/stakeholder_corpus.py freeze /study/originals.jsonl /study/frozen
python3 -B tests/evals/stakeholder_corpus.py packet /study/frozen "$MANIFEST_PIN" "$CASE" /operator/inbox
```

Distribute the manifest pin separately. Use each hub’s normal provisioning surface. Keep seed instructions and response scripts with the operator.


Mount only authorized source bytes and the seeded hub. Submit the verbatim request. Never send the case ID, family, rubric, or expected destination.

Two readers label each source independently before seeing output. Record required meanings, permissible alternatives, prohibited propositions, speaker or intermediary, exact evidence, uncertainty, scope and legitimate silence. Adjudicate disagreements against the source. Freeze the resolved keys, signed reviews and rubric before collecting outputs.

Calibrate budgets, sample sizes, claim bounds, operating points, rubric dimensions and stopping rules on development data. Freeze them before collection. Preserve earlier attempts. Use a fresh confirmation set after holdout-informed changes.

Even perfect outcomes need 59 nonempty paired originals per family for the deficit bound and 29 per coaching workflow. Perfect overall precision needs 76 originals at full claim capacity or 183 at half capacity.

## Run the Codex study

Register `oryx-stakeholder-study/v2` before collection. Freeze new registrations, scorer and evidence pins. Preserve historical studies and signed reports.

Use one pinned Codex repository harness for both hubs. Load each hub's instructions and tools from its checkout. Verify both routes with positive development cases. Pin the harness bytes, client version, model revision, tools and settings.

Use three fresh trials per arm. Alternate hub order by sorted case and repeat, beginning with Oryx. Compare each reference repeat with its next cyclic repeat.

Score Oryx extraction, effects and coaching on these runs. Label comparative quality, latency and PM turns `matched-codex-repo-harness`. The pinned reference supports generic repository use. Its documented native clients differ.

Run protected Oryx Codex separately for absolute latency and subscriber overhead. Preflight its positive known answer and capture its protected launch.

```sh
python3 tools/pm.py agent codex
```

Exercise both client adapters for installation, privacy and cross-client recovery on Linux, macOS and WSL2. Record shell and hook fixtures as such. Collect native capture and protected launch evidence on each supported host. Claude contributes integration evidence without generating graded model answers.

On each host, run the approved parity fixture against the reviewed checkout. Record the launch and complete output independently.

```sh
python3 tests/test_client_core_parity.py --capture
```

Submit one PM turn at a time. Apply only the scripted response appropriate to the observed request. Capture intake, candidates, visible preview, approved effects, replay and fresh-session reuse. Preserve unobservable internal stages. Observe tool calls, actual reads, model-bound input, and external test transport from outside the client.

Capture each controlled filesystem at baseline, preview, outcome, retry and fresh use. Include the private journal root in the recorder's scope. Fingerprint ignored files and symlinks. Record Git state separately when relevant.

```sh
python3 -B tests/evals/stakeholder_corpus.py snapshot /run/observed-volumes /recorder/baseline.json
```

Use independent monotonic event capture from PM submission. Mark grounded first results, warranted questions, or correct completed abstentions. Record common-work completion, elapsed human and model time, PM turns, and approval or handoff overhead. Include failed completions and timeouts. Time all four deployments on at least 100 independent matched originals in each warm and cold stratum.

## Grade and decide


Randomize opaque output IDs. Remove hub identities and launch metadata from judge copies. Keep exact source spans, quotations, and observable actions. Both judges code every material finding, including duplicates and false positives.

Canonical meanings require matching person, speaker, evidence, qualifiers, time and scope. Code disposition separately. An absence of visible findings does not establish correct abstention.

Grade consequential coaching dimensions against the PM's purpose. Check critical objections and fresh-session evidence. A third reader resolves disagreements. Record a rationale, independent trace, and actual filesystem delta for each effect. Independently verify the full protected host matrix, privacy, installation and recovery.

```sh
python3 -B tests/evals/stakeholder_release.py /study/frozen "$MANIFEST_PIN" /recorder/evidence "$REGISTRATION_PIN"
```

A missing, failed or inconclusive gate holds release. The scorer emits counts, bounds, failures and timing details for complete bundles. Keep evidence private. Publish the authorized reviewer receipt. [Bundle format](stakeholder-evidence.md)
