"""Evaluator controls use toy rows. No release fixture or answer is installed with the Hub."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

EVALS = Path(__file__).resolve().parent / "evals"
sys.path.insert(0, str(EVALS))
import stakeholder_corpus as corpus
import stakeholder_release as gate
import stakeholder_statistics as stats


def finding(meaning, disposition="propose", supported=True):
    return {"meaning":meaning,"disposition":disposition,"supported":supported,"durable":True}


def toy_corpus():
    rows = []
    for family in corpus.FAMILIES:
        for i in range(10):
            ident = f"{family}-{i}"
            negative = i >= 8
            rows.append(dict(id=ident, origin=ident, split="dev" if i < 2 else "heldout",
                             family=family, format="minutes", workflow="intake", date="2026-01-03",
                             source=f"Toy artifact {ident}\n", prompt="Process the supplied toy.",
                             permitted_sources=["source.txt"], script=["Review before saving."],
                             seed={"people":[],"profiles":{},"decisions":[],"grants":[]},
                             key={"negative":negative,"required":[] if negative else [{"id":"one"}],
                                  "permissible":[],"prohibited":[],"assertions":list(corpus.EFFECTS)}))
    return rows


class StakeholderEvaluationTests(unittest.TestCase):
    def test_one_to_one_duplicates_abstentions_and_dispositions(self):
        a, b = finding("A"), finding("B","ask")
        self.assertEqual(stats.agreement([a,b],[a,b]),1)
        self.assertEqual(stats.agreement([a,a],[a,a]),.5)
        self.assertEqual(stats.agreement([a,b],[a]),2/3)
        self.assertEqual(stats.agreement([a],[finding("A","route")]),0)
        self.assertEqual(stats.agreement([], [a]),0)
        self.assertIsNone(stats.agreement([], []))

    def test_supported_duplicates_permissible_and_negative_denominators(self):
        key = {"required":[{"id":"A"},{"id":"B"}],"permissible":[{"id":"C"}],"negative":False}
        claims = [finding("A"),finding("A"),finding("B",supported=False),finding("C")]
        result = stats.rates(stats.counts(claims,key))
        self.assertEqual((result["precision"],result["recall"],result["f1"]),(.5,.5,.5))
        missing = stats.rates(stats.counts([],key))
        self.assertIsNone(missing["precision"])
        self.assertEqual(missing["recall"],0)
        self.assertEqual(missing["f1"],0)
        self.assertEqual(stats.counts(claims,dict(key,negative=True))["negative_proposals"],4)

    def test_confidence_bounds_need_independent_evidence(self):
        self.assertLess(stats.exact_lower(28,28),.90)
        self.assertGreater(stats.exact_lower(29,29),.90)
        self.assertAlmostEqual(stats.exact_lower(6,10),.3035372126,places=8)
        self.assertIsNone(stats.bounded_lower([]))
        self.assertLess(stats.bounded_lower([1]*8),.90)
        self.assertLess(stats.bounded_lower([0]*8,width=2),-.05)
        self.assertEqual(stats.order_bounds(list(range(1,101)),.95), (90,100))
        self.assertIsNone(stats.order_bounds([1]*8,.95)[1])

    def test_clean_packet_and_freeze_reject_tampering_and_variant_inflation(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            rows = toy_corpus()
            rows[8]["key"]["required"] = [{"id":"uncertain","durable":False}]
            source = root/"originals"
            def write_rows():
                source.write_text("".join(json.dumps(i)+"\n" for i in rows))
            write_rows()
            frozen = root/"frozen"
            pin = corpus.freeze(source,frozen)
            case = rows[2]["id"]
            output = root/"packet"
            corpus.packet(frozen,pin,case,output)
            self.assertEqual({p.name for p in output.iterdir()},{"source.txt","seed.json","request.txt"})
            (frozen/case/"source.txt").write_text("altered")
            with self.assertRaisesRegex(ValueError,"changed"):
                corpus.packet(frozen,pin,case,root/"new")
            with self.assertRaisesRegex(ValueError,"digest"):
                corpus.load_manifest(frozen,"0"*64)
            rows[3]["origin"] = rows[2]["id"]
            rows[3]["transform_expectation"] = "Name changed."
            write_rows()
            with self.assertRaisesRegex(ValueError,"breadth"):
                corpus.freeze(source,root/"thin")

    def test_filesystem_effects_include_ignored_hidden_and_link_changes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/".git").mkdir()
            (root/".gitignore").write_text(".private/\n")
            (root/".private").mkdir()
            (root/".private/log").write_text("before")
            (root/"link").symlink_to(".private/log")
            before = corpus.snapshot(root)
            (root/".private/log").write_text("after")
            (root/"link").unlink()
            self.assertEqual(corpus.changed(before,corpus.snapshot(root)),{".private/log","link"})

    def test_timeout_counts_and_progress_does_not_qualify(self):
        events = [{"kind":"submitted","ms":50},{"kind":"progress","ms":80},{"kind":"timeout","ms":90}]
        t = gate.timeline(events,None,1000)
        self.assertFalse(t["completed"])
        self.assertEqual((t["first"],t["complete"]),(1000,1000))
        with self.assertRaisesRegex(ValueError,"useful reply"):
            gate.timeline(events,1,1000)
        events[-1] = {"kind":"completed","ms":95}
        with self.assertRaisesRegex(ValueError,"No first useful"):
            gate.timeline(events,None,1000)

    def test_detached_observer_signature_fails_on_changed_evidence(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"keys").mkdir()
            key = root/"private.key"
            pub = root/"keys/observer.pem"
            artifact = root/"observer.json"
            artifact.write_text('{"observed": true}')
            subprocess.run(["openssl","genpkey","-algorithm","EC","-pkeyopt","ec_paramgen_curve:P-256",
                            "-out",str(key)],check=True,capture_output=True)
            subprocess.run(["openssl","pkey","-in",str(key),"-pubout","-out",str(pub)],check=True,capture_output=True)
            subprocess.run(["openssl","dgst","-sha256","-sign",str(key),"-out",str(root/"observer.json.observer.sig"),
                            str(artifact)],check=True,capture_output=True)
            keys = {"observer":corpus.digest(pub.read_bytes())}
            gate.verify_signature(root,"observer.json","observer",keys)
            artifact.write_text('{"observed": false}')
            with self.assertRaisesRegex(ValueError,"signature"):
                gate.verify_signature(root,"observer.json","observer",keys)

    def test_gate_cannot_pass_empty_or_self_reported_results(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            frozen = root/"frozen"
            rows = root/"rows"
            rows.write_text("".join(json.dumps(i)+"\n" for i in toy_corpus()))
            pin = corpus.freeze(rows,frozen)
            registration = root/"registration.json"
            registration.write_text('{"decision":"PASS","checks":{"protected":true}}')
            args = [sys.executable,"-B",str(EVALS/"stakeholder_release.py"),str(frozen),pin,
                    str(root),corpus.digest(registration.read_bytes())]
            proc = subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(proc.returncode,1)
            self.assertEqual(json.loads(proc.stdout)["decision"],"HOLD")


    def test_critical_integrity_and_file_effect_hold_even_with_valid_signed_shape(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            def store(name, value):
                blob = corpus.data(value)
                (root/name).write_bytes(blob)
                return {"path":name,"sha256":corpus.digest(blob)}
            trace = store("trace.json",{"observation":"toy external observer"})
            first_snapshot = store("before.json",{"record":[33188,"b"*64]})
            second_snapshot = store("after.json",{"record":[33188,"d"*64]})
            source = {"source.txt":b"Toy evidence"}
            sha = corpus.digest(source["source.txt"])
            events = store("events.json",[
                {"kind":"submitted","ms":100,"session":"unit-a","source_sha256":sha},
                {"kind":"reply","ms":110,"text":"The fictional source needs clarification."},
                {"kind":"completed","ms":112}])
            captures = store("effects.json",[{"id":"write-1","stage":"preview","kind":"write",
                                               "reviewed_record":True,"evidence":trace}])
            run = {key:trace for key in ("tool_trace","model_inputs","retrieval","transport","launch","transcript")}
            run.update(session="unit-a",events=events,effects_log=captures,
                       snapshots={s:first_snapshot if i==0 else second_snapshot for i,s in enumerate(corpus.STAGES)})
            stages = ("intake","candidates","preview","effects","fresh-use")
            row = finding("unsupported")
            row.update(supported=False,settled=True,output_evidence=trace)
            verdict = dict(observations={k:trace for k in stages}, critical=["wrong person"],findings=[row],
                           assertions={k:{"evidence":trace,"result":"pass"} for k in corpus.EFFECTS},
                           expected_changes={k:{} for k in corpus.STAGES[1:]},useful_event=1,
                           useful_basis={"kind":"warranted-clarification","rationale":"Source is unclear.","evidence":trace})
            key = dict(negative=False,assertions=corpus.EFFECTS,
                       effect_policy={"external_actions":[],"approval":"reviewed-only"})
            checks = {}
            gate.audit_trial(root,run,verdict,key,checks,"unit",500,source)
            self.assertFalse(checks["unit/integrity"])
            self.assertFalse(checks["unit/files/preview"])
            self.assertFalse(checks["unit/authorization/write-1"])
            self.assertFalse(checks["unit/unsupported-settled"])
            self.assertTrue(checks["unit/completed"])
            verdict["useful_basis"]["kind"] = "correct-abstention"
            with self.assertRaisesRegex(ValueError,"positive source"):
                gate.audit_trial(root,run,verdict,key,{},"unit",500,source)

    def test_timing_gates_reject_empty_schedules_and_reused_sessions(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError,"Insufficient matched"):
                gate.performance(root,{"timing_schedule":{}},{},{},{})
            reg = {"timing_schedule":{"one":{"arm":"oryx-codex","stratum":"cold","original":"A"}}}
            run = {"session":"two","condition":reg["timing_schedule"]["one"]}
            with self.assertRaisesRegex(ValueError,"assignment"):
                gate.performance(root,reg,{"one":run},{"one":{}},{})


    def test_synthetic_complete_timing_matrix_scores_and_pins_observed_events(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            def save(name, raw):
                (root/name).write_bytes(raw)
                return {"path":name, "sha256":corpus.digest(raw)}
            schedule, runs, grades = {}, {}, {}
            trace = save("dummy-trace",b"toy evidence for arithmetic checks only")
            setups = {a:{"test":a} for a in (*gate.ARMS,"oryx-codex-off")}
            for group in ("warm","cold"):
                for i in range(100):
                    source = save(f"source-{group}-{i}",f"unit {group} {i}".encode())
                    for arm in setups:
                        sid = f"{group}-{i}-{arm}"
                        design = dict(arm=arm,stratum=group,original=str(i),source_sha256=source["sha256"])
                        events = [{"kind":"submitted","ms":5,"session":sid,"source_sha256":source["sha256"]},
                                  {"kind":"model-start","ms":6},{"kind":"reply","ms":9,"text":"test finding"},
                                  {"kind":"model-end","ms":11},{"kind":"common-complete","ms":12},
                                  {"kind":"completed","ms":13}]
                        schedule[sid] = design
                        runs[sid] = dict(session=sid,condition=design,setup=setups[arm],source=source,launch=trace,
                                         transcript=trace,events=save(sid,corpus.data(events)))
                        grades[sid] = dict(useful_event=2,useful_basis={"kind":"grounded","rationale":"toy","evidence":trace})
            registration = {"timing_schedule":schedule,"setups":setups,"timeout_ms":100,
                            "codex_budgets_ms":{"first":4,"complete":8}}
            checks = {}
            result = gate.performance(root,registration,runs,grades,checks)
            self.assertTrue(all(checks.values()))
            self.assertEqual(result["warm/complete/p95"]["matched_upper_ratio"],1)
            registration["codex_budgets_ms"]["complete"] = 7
            gate.performance(root,registration,runs,grades,checks)
            self.assertFalse(checks["cold/complete/p95/absolute"])
            a,b = list(runs)[:2]
            runs[b]["events"] = runs[a]["events"]
            with self.assertRaisesRegex(ValueError,"Replayed"):
                gate.performance(root,registration,runs,grades,{})


if __name__ == "__main__":
    unittest.main()
