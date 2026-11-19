# Weekly decision review

Run the review when the PM asks or closes the week. Use the current product when known.

```sh
python3 tools/pm.py action portfolio decisions review --product checkout
```

Omit the product filter for a portfolio review. The command reads the private workspace and returns up to five findings.

| Finding | What to check |
| --- | --- |
| Decision due | Read the latest signed decision, its review date, and any follow-up measurement. |
| Forecast due | Compare the outcome evidence with the original resolution criterion. |
| Possible conflict | Compare the cited authority and scope in the open context review. |
| Context risk | Verify the cited evidence with the owner. |
| Signal review | Compare the observation with the affected claim in the active signed plan. |
| Possible trigger | Compare newly registered evidence with the PM's stated reopen condition. |
| Stale assumption | Check the assumption with its owner after the record's review date. |
| Unassessed hypothesis | Read the registered hypothesis and look for evidence of a test. |

A local review date takes priority. Without one, check an assumption after three weeks and a decision after six weeks.
Flag an assumption with no dated check so the PM can establish its age.
Check unresolved forecasts after six weeks without a probability update. Review hypotheses after 30 days without a fresh dated test result.

Each finding names its subject and includes a private record path and evidence pointers.
Start with the single recommended check. An empty list means the scan found no recorded trigger.
Review narrative sources when a date, outcome, or conflict requires judgment. Open reviews retain their [evidence review ID](evidence-reviews.md).

The PM decides whether to reopen work. Use [initiative approvals](initiative-approvals.md) for a registered change.

Ask what surprised the PM. With their agreement, carry their words into the owning [checkpoint](conversation.md).
Use [forecast review](decision-forecasts.md) to preview a sourced resolution. The scan is read-only.
