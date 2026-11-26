"""Score independent observation bundles against a separately pinned study. Missing evidence holds release."""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
from statistics import mean, median
from math import log, sqrt
import subprocess

from stakeholder_corpus import (EFFECTS, FAMILIES, HEX, IDENT, STAGES, changed, digest, load_manifest,
                                read, require, verified_file)
from stakeholder_statistics import agreement, bounded_lower, counts, exact_lower, order_bounds, rates

ARMS = ("oryx-claude", "ref-claude", "oryx-codex")
HOSTS = ("linux", "macos", "wsl2")
WORKFLOWS = ("setup", "update", "conversation", "draft", "rehearsal")
DIMENSIONS = ("evidence", "intent", "usefulness", "revision", "ownership", "critical-objections")
DISPOSITIONS = ("propose", "park", "ask", "route")
REFERENCE = "52d55027c25f544ef6e55e9240be06340615c295"
INTEGRATION = {
    "adapter": ("meeting", "chat", "second-subscriber", "reverse-order", "grants-before-dispatch",
                "slow-failure-retry", "foreground", "span-at-preview-and-apply"),
    "storage": ("existing-new", "source-wording-destination-revision", "concurrent-accept", "identity-only",
                "hundred-unrelated", "model-input", "scoped-readiness", "follow-up"),
    "handoffs": ("concurrent-offers", "lost-ack", "defer-replay", "skip-return-mute", "feedback-consent",
                 "authorized-issue-retry", "recording-transport"),
    "continuity": ("hard-kill-cross-client", "no-history-two-days", "similar-open-tasks", "parent-revision",
                   "missing-partial-events", "four-settings", "silent-journal", "tip-mute-compaction"),
    "privacy": ("off-record", "profile-refusal", "expired", "other-studio", "model-input-and-reads",
                "backup-restore-feedback", "revoke", "backfill-opt-out", "purge-race", "retention", "quiet"),
    "install": ("protected-launch", "fresh-format2", "format1", "0.13-to-0.14", "supported-upgrade",
                "optional-setup", "existing-grants", "native-capture", "recovery"),
}


def local(root, name):
    path = (root / name).resolve(strict=True)
    require(Path(name).as_posix() == name and not Path(name).is_absolute() and path.is_relative_to(root.resolve()),
            "Evidence path escapes bundle")
    return path


def verify_signature(root, name, reviewer, keys):
    public = local(root, "keys/" + reviewer + ".pem")
    require(digest(public.read_bytes()) == keys[reviewer], "Independent public key differs from registration")
    cmd = ["openssl", "dgst", "-sha256", "-verify", str(public), "-signature",
           str(local(root, name + "." + reviewer + ".sig")), str(local(root, name))]
    require(subprocess.run(cmd, capture_output=True).returncode == 0, f"Invalid independent signature on {name}")


def observed(root, ref):
    require(isinstance(ref, dict) and HEX.fullmatch(ref["sha256"]), "Missing captured evidence digest")
    path = local(root, ref["path"])
    raw = path.read_bytes()
    require(raw and digest(raw) == ref["sha256"], f"Evidence missing or changed: {ref['path']}")
    return raw


def receipt(root, ref):
    return json.loads(observed(root, ref))


def successful(checks, name, condition):
    checks[name] = bool(condition)


def timeline(events, useful_index, timeout):
    """The observer timestamps all events with one monotonic clock in milliseconds."""
    require(events and events[0]["kind"] == "submitted", "Missing PM submission")
    times = [x["ms"] for x in events]
    require(all(type(t) in (float,int) and math.isfinite(t) and t >= 0 for t in times)
            and times == sorted(times), "Broken clock")
    end = events[-1]["kind"]
    require(end in {"completed","timeout","failure"}, "Missing terminal event")
    require(not any(x["kind"] in {"completed","timeout","failure"} for x in events[:-1]), "Events after completion")
    duration = times[-1] - times[0]
    if end == "timeout":
        duration = max(duration, timeout)
    require(duration > 0, "Invalid zero duration")
    if useful_index is None:
        require(end != "completed", "No first useful response in completed trial")
        first = duration
    else:
        require(type(useful_index) is int and 0 <= useful_index < len(events), "Invalid useful event")
        row = events[useful_index]
        require(row["kind"] == "reply" and row.get("text","").strip(), "Missing reviewed useful reply")
        first = row["ms"] - times[0]
        require(first > 0, "Invalid first-result interval")
    result = {"first": first, "complete": duration, "turns": sum(x["kind"] in {"submitted","pm"} for x in events),
              "completed": end == "completed"}
    for category in ("human","model","approval","handoff"):
        start = None
        elapsed = 0
        for event in events:
            if event["kind"] == category + "-start":
                require(start is None, "Overlapping timing segment")
                start = event["ms"]
            elif event["kind"] == category + "-end":
                require(start is not None, "Unmatched timing segment")
                elapsed += event["ms"] - start
                start = None
        require(start is None or end != "completed", "Unfinished timing segment")
        result[category] = elapsed + (times[-1] - start if start is not None else 0)
    return result


def first_useful(root, timeline_rows, grade, negative=None):
    index = grade["useful_event"]
    if index is None:
        return None
    label = grade["useful_basis"]
    require(label["kind"] in {"grounded","warranted-clarification","correct-abstention"} and
            label["rationale"].strip(), "Missing independently judged first useful result")
    observed(root,label["evidence"])
    require(label["kind"] != "correct-abstention" or negative is not False, "Empty answer on a positive source")
    require(type(index) is int and 0 <= index < len(timeline_rows), "Invalid first useful result index")
    return index


def audit_trial(root, observed_run, grade, key, checks, name, timeout, source_bytes):
    require(set(grade["observations"]) == {"intake","candidates","preview","effects","fresh-use"},
            "Missing five-point observations")
    for stage, note in grade["observations"].items():
        require(note == "unobservable" and stage == "candidates" or isinstance(note, dict)
                and observed(root,note), "Missing stage evidence")
    require(type(grade["critical"]) is list, "Critical findings must be listed")
    successful(checks,name+"/integrity", not grade["critical"])
    require(set(grade["assertions"]) == set(key["assertions"]), "Missing effect assertions")
    for field, verdict in grade["assertions"].items():
        observed(root,verdict["evidence"])
        successful(checks,name+"/"+field, verdict["result"] == "pass")
    snapshots = [receipt(root,observed_run["snapshots"][stage]) for stage in STAGES]
    require(all(isinstance(s,dict) and s for s in snapshots), "Empty filesystem capture")
    for stage, before, after in zip(STAGES[1:],snapshots,snapshots[1:]):
        expected = grade["expected_changes"][stage]
        require(isinstance(expected,dict), "Missing expected file changes")
        actual = {path:after.get(path) for path in changed(before,after)}
        successful(checks,name+"/files/"+stage, actual == expected)
    policy = key["effect_policy"]
    accesses = receipt(root,observed_run["effects_log"])
    require(isinstance(accesses,list), "Expected independently captured filesystem and transport effects")
    for item in accesses:
        require(item["stage"] in STAGES and item["kind"] in {"read","write","send","issue","delete"}
                and type(item["reviewed_record"]) is bool, "Unknown captured effect")
        observed(root,item["evidence"])
        if item["kind"] in {"send","issue"}:
            successful(checks,name+"/external/"+item["id"],item["kind"] in policy["external_actions"])
        if item["kind"] in {"write","delete"} and item["reviewed_record"]:
            allowed = (item["stage"] == "outcome" and policy["approval"] == "reviewed-only"
                       and bool(item.get("approval_event")))
            successful(checks,name+"/authorization/"+item["id"],allowed)
    require(len({item["id"] for item in accesses}) == len(accesses), "Duplicate effect observation")
    for field in ("tool_trace","model_inputs","retrieval","transport","launch","transcript"):
        observed(root,observed_run[field])
    for finding in grade["findings"]:
        require(isinstance(finding["meaning"], str) and finding["meaning"].strip() and finding["disposition"] in DISPOSITIONS and
                type(finding["supported"]) is bool and type(finding["durable"]) is bool,
                "Incomplete semantic coding")
        observed(root, finding["output_evidence"])
        require(type(finding["settled"]) is bool, "Missing certainty judgment")
        if finding["settled"] and not finding["supported"]:
            successful(checks,name+"/unsupported-settled",False)
        if finding["supported"]:
            span = finding["source_span"]
            raw = source_bytes[span["source"]]
            start,end = span["start"],span["end"]
            require(type(start) is int and type(end) is int and 0 <= start < end <= len(raw) and
                    raw[start:end] == span["quote"].encode(), "Claim locator does not match frozen source bytes")
    events = receipt(root,observed_run["events"])
    require(events[0]["session"] == observed_run["session"] and
            events[0]["source_sha256"] == digest(source_bytes["source.txt"]), "Event stream belongs to another trial")
    timing = timeline(events, first_useful(root,events,grade,key["negative"]), timeout)
    successful(checks,name+"/completed", timing["completed"])
    return timing


def semantic(root, cases, keys, observation, final, reg, checks, private):
    rows = defaultdict(list)
    totals = defaultdict(Counter)
    per_original = defaultdict(lambda: defaultdict(Counter))
    coaching = defaultdict(dict)
    timings = {}
    held = sorted(k for k,v in cases.items() if v["split"] == "heldout")
    reps = reg["repeats"]
    require(type(reps) is int and reps >= 3, "Need three fresh preregistered repeats")
    expected = {f"{case}/{arm}/{i}" for case in held for arm in ARMS for i in range(reps)}
    require(set(observation) == set(final) == expected, "Incomplete semantic schedule")
    sessions = set()
    for case in held:
        info, key = cases[case], keys[case]
        source_bytes = {field:verified_file(private,cases,case,field).read_bytes() for field in ("source.txt","seed.json")}
        for i in range(reps):
            a,b = (observation[f"{case}/{arm}/{i}"]["submitted_utc_ms"] for arm in ARMS[:2])
            require(type(a) is int and type(b) is int and a != b and min(a,b) > 0, "Missing paired start times")
            require((a < b) == ((held.index(case)+i)%2 == 0), "Native trial order differs from freeze")
        for arm in ARMS:
            for i in range(reps):
                name = f"{case}/{arm}/{i}"
                run, grade = observation[name], final[name]
                require(run["session"] not in sessions and run["session"] and run["setup"] == reg["setups"][arm],
                        "Duplicate session or client/model/settings mismatch")
                require(run["case_files"] == info["files"]["source.txt"] and run["request_sha256"] == info["files"]["request.txt"]
                        and run["seed_sha256"] == info["files"]["seed.json"], "Case inputs differ from freeze")
                sessions.add(run["session"])
                timings[name] = audit_trial(root,run,grade,key,checks,name,reg["timeout_ms"],source_bytes)
                cnt = counts(grade["findings"], key)
                successful(checks,name+"/negative", cnt["negative_proposals"] == 0)
                if key["negative"]:
                    abstention = grade["abstention"]
                    observed(root,abstention["evidence"])
                    successful(checks,name+"/warranted-abstention",abstention["result"] == "pass"
                               and bool(abstention["rationale"].strip()))
                    for required in key["required"]:
                        successful(checks,name+"/negative-obligation/"+required["id"],
                                   any(f["supported"] and f["meaning"] == required["id"] for f in grade["findings"]))
                rows[case,arm].append(grade["findings"])
                if info["origin"] != case:
                    transform = grade["transformation"]
                    require(transform["expectation"] == info["transformation"] and transform["rationale"].strip(),
                            "Transformed input was not compared with its original")
                    observed(root,transform["original_evidence"])
                    observed(root,transform["variant_evidence"])
                    successful(checks,name+"/transformation",transform["result"] == "pass")
                    continue
                if arm == "ref-claude":
                    continue
                for bucket in ("overall",info["family"]):
                    totals[arm,bucket].update(cnt)
                    per_original[arm,bucket][case].update(cnt)
                if info["workflow"] in WORKFLOWS:
                    rubric = grade["rubric"]
                    require(set(rubric) == set(DIMENSIONS) and all(v in {"pass","fail","inapplicable"} for v in rubric.values()),
                            "Missing coaching rubric")
                    dimensions = reg["consequential_dimensions"][info["workflow"]]
                    require(set(dimensions) >= {"evidence","intent","usefulness","ownership","critical-objections"},
                            "Coaching dimensions omitted")
                    passed = all(rubric[k] == "pass" for k in dimensions)
                    successful(checks,name+"/objections", rubric["critical-objections"] == "pass")
                    bucket = coaching[arm,info["workflow"]]
                    bucket[case] = bucket.get(case,True) and passed
    extraction, comparison, downstream = {}, {}, {}
    for arm in ("oryx-claude","oryx-codex"):
        for family in ("overall",*FAMILIES):
            row = rates(totals[arm,family])
            extraction[f"{arm}/{family}"] = row
            p,r = (.95,.90) if family == "overall" else (.90,.85)
            by_case = per_original[arm,family]
            n = len(by_case)
            for num,den,threshold,label in (("correct","proposed",p,"precision"),("recovered","required",r,"recall")):
                cap = reg["per_artifact_claim_cap"]
                require(all(c[den] <= reps*cap for c in by_case.values()), "Preregistered claim bound exceeded")
                denominator = sum(c[den] for c in by_case.values()) / (reps*n) if n else 0
                uncertainty = cap * sqrt(log(20)/(2*n)) / denominator if denominator else None
                lower = row[label] - uncertainty if uncertainty is not None else None
                row[label+"_lower95"] = lower
                successful(checks,f"{arm}/{family}/{label}", lower is not None and lower >= threshold)
            row["independent"] = n
        for workflow in WORKFLOWS:
            values = coaching[arm,workflow].values()
            low = exact_lower(sum(values),len(values))
            downstream[f"{arm}/{workflow}"] = dict(pass_count=sum(values), independent=len(values), lower95=low)
            successful(checks,f"{arm}/{workflow}/coaching", low >= .90)
    for family in FAMILIES:
        paired, deltas = [], []
        abstentions = Counter()
        for case in held:
            group = cases[case]
            if group["origin"] != case or group["family"] != family:
                continue
            scored, gaps = [], []
            for i in range(reps):
                cand, ref = rows[case,"oryx-claude"][i], rows[case,"ref-claude"][i]
                cross = agreement(cand, ref)
                repeat = agreement(ref, rows[case,"ref-claude"][(i+1)%reps])
                if cross is None:
                    abstentions["both_empty"] += 1
                    abstentions["correct"] += keys[case]["negative"]
                    successful(checks,f"{case}/{i}/paired-abstention",keys[case]["negative"])
                if cross is not None:
                    scored.append(cross)
                if cross is not None and repeat is not None:
                    gaps.append(cross-repeat)
                elif cross is not None or repeat is not None:
                    # The paired deficit lacks its denominator. Preserve that uncertainty.
                    successful(checks,f"{case}/{i}/paired-comparability",False)
            if scored:
                paired.append(mean(scored))
            if gaps:
                deltas.append(mean(gaps))
        lower, delta = bounded_lower(paired), bounded_lower(deltas,2)
        comparison[family] = dict(independent=len(paired), mean=mean(paired) if paired else None,
                                  lower95=lower, deficit_lower95=delta, abstentions=dict(abstentions))
        successful(checks,f"{family}/agreement", lower is not None and lower >= .90 and delta is not None and delta >= -.05)
    return dict(extraction=extraction, comparison=comparison, coaching=downstream, semantic_timings=timings)


def performance(root, registration, observer, grades, checks):
    result = {}
    expected = registration["timing_schedule"]
    require(set(expected) == set(observer) == set(grades), "Missing independently timed deployment")
    groups = defaultdict(dict)
    used = set()
    for session, design in expected.items():
        run = observer[session]
        require(run["session"] == session and run["condition"] == design, "Wrong performance assignment")
        require(design["stratum"] in {"warm","cold"} and design["arm"] in {*ARMS,"oryx-codex-off"},
                "Unexpected operating point")
        require(run["setup"] == registration["setups"][design["arm"]], "Performance client settings differ")
        arm, group, pair = design["arm"],design["stratum"],design["original"]
        require((group,pair,arm) not in used and pair, "Performance repeats cannot increase independent n")
        used.add((group,pair,arm))
        require(HEX.fullmatch(design["source_sha256"]) and
                digest(observed(root,run["source"])) == design["source_sha256"], "Timing input differs from schedule")
        observed(root,run["launch"])
        observed(root,run["transcript"])
        events = receipt(root,run["events"])
        require(events[0]["session"] == session and events[0]["source_sha256"] == design["source_sha256"],
                "Replayed performance event stream")
        timing = timeline(events,first_useful(root,events,grades[session]),registration["timeout_ms"])
        common = [i for i,event in enumerate(events) if event["kind"] == "common-complete"]
        require(len(common) == 1 or not timing["completed"] and not common, "Missing common-work completion")
        timing["common"] = events[common[0]]["ms"] - events[0]["ms"] if common else timing["complete"]
        require(timing["common"] >= timing["first"] or not timing["completed"], "Common work ended before useful result")
        require(not timing["completed"] or timing["model"] > 0, "Missing measured model interval")
        successful(checks,session+"/completed",timing["completed"])
        groups[group,arm][pair] = timing
    for group in ("warm","cold"):
        originals = {}
        for design in expected.values():
            if design["stratum"] == group:
                key = design["original"]
                require(key not in originals or originals[key] == design["source_sha256"], "Mismatched timing pair")
                originals[key] = design["source_sha256"]
        require(len(set(originals.values())) == len(originals), "Repeated source cannot inflate independent n")
        arms = {arm:groups[group,arm] for arm in (*ARMS,"oryx-codex-off")}
        pairs = set(arms["ref-claude"])
        require(all(set(v)==pairs for v in arms.values()) and len(pairs)>=100, "Insufficient matched independent timing sessions")
        for metric in ("first","complete"):
            for q in (.5,.95):
                matched_metric = "common" if metric == "complete" else metric
                bounds = {arm:order_bounds([v[matched_metric] for v in trials.values()],q) for arm,trials in arms.items()}
                lower = bounds["ref-claude"][0]
                upper = bounds["oryx-claude"][1]
                code = f"{group}/{metric}/p{int(q*100)}"
                result[code] = {"n":len(pairs),"bounds":bounds,"matched_upper_ratio":upper/lower if upper and lower else None}
                successful(checks, code+"/relative", bool(lower and upper and upper/lower <= 1.2))
                if q == .95:
                    enabled, disabled = bounds["oryx-codex"][1], bounds["oryx-codex-off"][0]
                    absolute_upper = order_bounds([v[metric] for v in arms["oryx-codex"].values()],q)[1]
                    successful(checks,code+"/absolute", bool(absolute_upper and absolute_upper <= registration["codex_budgets_ms"][metric]))
                    successful(checks,code+"/subscriber", bool(disabled and enabled and enabled / disabled <= 1.1))
        turns = [arms["oryx-claude"][key]["turns"]-arms["ref-claude"][key]["turns"] for key in pairs]
        successful(checks,group+"/turns", median(turns) <= 1 and order_bounds(turns,.5)[1] <= 1)
    result["trials"] = {f"{group}/{arm}/{pair}":value for (group,arm),runs in groups.items()
                        for pair,value in runs.items()}
    return result


def registration(root, reg, pin):
    require(reg["manifest_sha256"] == pin and re.fullmatch(r"[0-9a-f]{40}",reg["candidate"])
            and reg["reference"] == REFERENCE, "Missing or incorrect release revisions")
    keys = reg["keys"]
    require(set(keys) == {"reader-a","reader-b","adjudicator","observer"}
            and len(set(keys.values())) == len(keys) and all(HEX.fullmatch(v) for v in keys.values()),
            "Four distinct pinned independent identities are required")
    setups = reg["setups"]
    require(set(setups) == {*ARMS,"oryx-codex-off"}, "Incomplete client matrix")
    for arm,setup in setups.items():
        require(all(setup.get(k) for k in ("client","client_version","model","model_revision","tools","settings","revision")),
                "Unpinned setup")
        require(setup["revision"] == (reg["reference"] if arm=="ref-claude" else reg["candidate"]),
                "Wrong Hub revision")
        require(setup["client"] == ("claude" if "claude" in arm else "codex"), "Wrong native client")
    for field in ("client","client_version","model","model_revision","tools","settings"):
        require(setups["oryx-claude"][field] == setups["ref-claude"][field], "Unmatched native pair")
        require(setups["oryx-codex"][field] == setups["oryx-codex-off"][field], "Unmatched subscriber comparison")
    require(setups["oryx-codex"]["subscriber"] is True and setups["oryx-codex-off"]["subscriber"] is False,
            "Missing subscriber control")
    calibration = receipt(root,reg["calibration"])
    require(calibration["codex_budgets_ms"] == reg["codex_budgets_ms"] and
            set(reg["codex_budgets_ms"]) == {"first","complete"} and
            all(type(v) in (int,float) and 0 < v < math.inf for v in reg["codex_budgets_ms"].values()) and
            type(reg["timeout_ms"]) in (int,float) and reg["timeout_ms"] >= max(reg["codex_budgets_ms"].values()),
            "Budgets require separate usability calibration")
    require(calibration["trace_refs"] and calibration["design_rationale"].strip(), "Missing calibration evidence")
    for ref in calibration["trace_refs"]:
        observed(root,ref)
    require(reg["schedule_rule"] == "alternate-hub-first-by-original-and-repeat"
            and reg["reference_pairing"] == "cyclic-next-repeat", "Unregistered native pairing")
    require(type(reg["per_artifact_claim_cap"]) is int and reg["per_artifact_claim_cap"] > 0, "Missing registered claim bound")
    require(set(reg["consequential_dimensions"]) == set(WORKFLOWS), "Missing rubric registration")
    for role in ("reader-a","reader-b"):
        name = role+"-source.json"
        verify_signature(root,name,role,keys)
        require(reg["source_reviews"][role] == digest(local(root,name).read_bytes()), "Late or changed source labels")
    return keys


def load_source_labels(root, cases, private, reg):
    expected = {k for k,v in cases.items() if v["split"] == "heldout"}
    keys = {}
    independent = {}
    for who in ("reader-a","reader-b"):
        reviews = read(local(root,who+"-source.json"))
        independent[who] = reviews
        require(set(reviews)==expected, "Incomplete independent source grading")
        for case,review in reviews.items():
            require(set(review) >= {"required","permissible","prohibited","negative","assertions","rationale"}
                    and review["rationale"].strip(), "Incomplete independent source grading")
    adjudicated = receipt(root,reg["source_adjudication"])
    require(set(adjudicated) == expected, "Incomplete frozen source adjudication")
    for case in expected:
        key = read(verified_file(private,cases,case,"key.json"))
        record = adjudicated[case]
        require(record["key"] == key and record["evidence_rationale"].strip(), "Frozen key and independent source adjudication differ")
        for role,reviews in independent.items():
            if any(reviews[case][field] != key[field]
                   for field in ("required","permissible","prohibited","negative","assertions")):
                require(record["source_disagreements"].get(role,"").strip(), "Unresolved source-label disagreement")
        keys[case] = key
    return keys


def release(private, pin, root, registration_pin):
    cases = load_manifest(private,pin)
    raw = local(root,"registration.json").read_bytes()
    require(HEX.fullmatch(registration_pin) and digest(raw)==registration_pin, "Registration differs from external pin")
    reg = json.loads(raw)
    identities = registration(root,reg,pin)
    keys = load_source_labels(root,cases,private,reg)
    verify_signature(root,reg["source_adjudication"]["path"],"adjudicator",identities)
    verify_signature(root,"observer.json","observer",identities)
    observations = read(local(root,"observer.json"))
    require(observations["registration"] == registration_pin, "Wrong observation study")
    verify_signature(root,"adjudication.json","adjudicator",identities)
    final = read(local(root,"adjudication.json"))
    for role in ("reader-a","reader-b"):
        name = role+"-blind.json"
        verify_signature(root,name,role,identities)
        reviews = read(local(root,name))
        require(final["blind_reviews"][role] == digest(local(root,name).read_bytes()), "Wrong independent output review")
        require(reviews["registration"] == registration_pin and reviews["cases"], "Missing blinded review")
        mapping = observations["blind_map"]
        require(len(set(mapping.values())) == len(mapping) and set(mapping.values()) == set(observations["semantics"])
                and set(reviews["cases"]) == set(mapping), "Missing blinded trial")
        for anonymous, verdict in reviews["cases"].items():
            require(IDENT.fullmatch(anonymous) and verdict["evidence"] and verdict["rationale"].strip()
                    and isinstance(verdict["findings"],list), "Missing independent evidence-based judgment")
            observed(root,verdict["evidence"])
            resolved = final["semantics"][mapping[anonymous]]
            if any(verdict[k] != resolved[k] for k in ("findings","critical","assertions","rubric")):
                require(resolved.get("disagreement_rationale","").strip(), "Missing third-reviewer adjudication")
    require(final["registration"] == registration_pin and final["observer_sha256"] == digest(local(root,"observer.json").read_bytes()),
            "Review is not bound to the observation evidence")
    checks = {}
    for host in HOSTS:
        for arm in ("oryx-claude","oryx-codex"):
            for group,items in INTEGRATION.items():
                for test in items:
                    name = "/".join((host,arm,group,test))
                    raw = receipt(root,observations["integration"][name])
                    grade = final["integration"][name]
                    require(raw["scenario"] == name and raw["setup"] == reg["setups"][arm] and raw["captured"],
                            "Wrong or absent integration observation")
                    for ref in raw["captured"]:
                        observed(root,ref)
                    observed(root,grade["evidence"])
                    successful(checks,name,grade["result"] == "pass" and not grade["critical"])
    for arm in ARMS:
        known = observations["known_answers"][arm]
        require(known["case"] in cases and cases[known["case"]]["split"] == "dev" and known["setup"] == reg["setups"][arm],
                "Known-answer preflight must use development material on the pinned setup")
        transcript = observed(root,known["transcript"])
        require(known["source_sha256"] == cases[known["case"]]["files"]["source.txt"], "Wrong known-answer source")
        verdict = final["known_answers"][arm]
        key = read(verified_file(private,cases,known["case"],"key.json"))
        require(key["required"], "A native known-answer must exercise a material positive")
        for finding in verdict["findings"]:
            require(finding["output_quote"].strip() and finding["output_quote"].encode() in transcript,
                    "Known-answer findings require observed output")
        count = counts(verdict["findings"],key)
        successful(checks,arm+"/known-answer", verdict["result"] == "pass" and not verdict["critical"]
                   and count["correct"] == count["proposed"] and count["required"] == count["recovered"])
    detail = semantic(root,cases,keys,observations["semantics"],final["semantics"],reg,checks,private)
    detail["performance"] = performance(root,reg,observations["performance"],final["performance"],checks)
    require(not set(x["session"] for x in observations["semantics"].values()) & set(observations["performance"]),
            "Semantic repetitions reused as independent performance sessions")
    failed = [name for name,ok in checks.items() if not ok]
    return {"decision":"HOLD" if failed else "PASS", "candidate":reg["candidate"], "manifest_sha256":pin,
            "registration_sha256":registration_pin, "failed":failed, "checks":checks, "results":detail}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("private", type=Path)
    cli.add_argument("manifest_sha256")
    cli.add_argument("evidence", type=Path)
    cli.add_argument("registration_sha256")
    args = cli.parse_args()
    try:
        report = release(args.private,args.manifest_sha256,args.evidence,args.registration_sha256)
    except (OSError, ValueError, KeyError, TypeError, IndexError, ArithmeticError) as exc:
        report = {"decision":"HOLD","missing_or_invalid":str(exc)}
    print(json.dumps(report,sort_keys=True,indent=2,allow_nan=False))
    return 0 if report["decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
