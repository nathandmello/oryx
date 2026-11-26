# Qualify a stakeholder release

The study operator freezes the fixtures and registers the study before collecting evidence.
The independent reviewer controls the qualification runner, approved scorer installation, and signing identity. [Study protocol](../tests/evals/stakeholder_release.py)

## Prepare the independent runner

Keep the candidate checkout, its import paths, and its executable tools off the reviewer host.
Install an independently reviewed copy of `release_qualification.py`, a trusted Python interpreter, and OpenSSL through the reviewer's protected channel.
Install the approved `stakeholder_release.py`, `stakeholder_statistics.py`, and `stakeholder_corpus.py` in a separate private scorer directory.

Generate the minimum named gate list with the installed controller. Add the case-specific gate names from the independent study registration.

```sh
python3 -I /review/qualification.py required-gates > /review/scorer/required-gates.json
python3 -I /review/qualification.py fingerprint scorer /review/scorer
```

Pin this scorer digest before the study. It covers all three modules and the required gate list.
The evaluator runs in an isolated interpreter with only the pinned modules. It receives neither candidate code nor signing-key arguments.

## Bind the study and observed evidence

Use a read-only snapshot of the independent evidence bundle. Record its digest after capture and before scoring.

```sh
python3 -I /review/qualification.py fingerprint evidence /review-data/evidence
```

Protect the workflows and release verifier through repository rules and independent review.
Set the repository Actions variable `ORYX_STUDY_REVIEWER_PUBLIC_KEY` to the independent reviewer's PEM public key.
Keep the private key with the reviewer, outside all input directories.

Set the Actions variable `ORYX_STUDY_PINS` from the independent registration and capture records.
Use the full reviewed commit as the key. Retain entries for candidates that may need a publication retry.

```json
{
  "<candidate commit>": {
    "manifest_sha256": "<frozen fixture manifest>",
    "registration_sha256": "<preregistered study>",
    "scorer_sha256": "<approved scorer and required gate list>",
    "evidence_sha256": "<captured evidence snapshot>"
  }
}
```

## Sign and verify

Confirm the repository, reviewed commit, and release version from the protected release request.
On the reviewer host, use the independent pins and new output paths.

```sh
python3 -I /review/qualification.py attest \
  --repository OWNER/REPO --head "$candidate" --version "$version" \
  --manifest "$manifest" --registration "$study" \
  --scorer-dir /review/scorer --scorer-digest "$scorer" \
  --frozen /review-data/frozen --evidence /review-data/evidence --evidence-digest "$captured" \
  --report /review-data/results.json --signing-key /review/keys/reviewer.pem \
  > /review-data/qualification-section.md
```

The command saves the scorer's exact output. It rechecks the captured evidence before signing.
A verified pass binds the repository, candidate, version, all four pins, and report digest.

Verify the signed receipt against the private report with the expected values.

```sh
python3 -I /review/qualification.py verify \
  --repository OWNER/REPO --head "$candidate" --version "$version" \
  --manifest "$manifest" --registration "$study" \
  --scorer-dir /review/scorer --scorer-digest "$scorer" \
  --evidence /review-data/evidence --evidence-digest "$captured" \
  --report /review-data/results.json --public-key /review/keys/reviewer-public.pem \
  --receipt /review-data/qualification-section.md
```

Add the signed section to the pull request description through the authorised review process. Keep the report and raw evidence private.
The review workflow fetches the current description, changed paths, and release metadata at the reviewed head.
Publication verifies the same signature and all four protected pins before checking the merged tree. [Publication rules](publication.md)
