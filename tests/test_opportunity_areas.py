"""Verify initiative area relationships through the signed register and both portfolio views."""

import csv
from io import StringIO
import json
import unittest

import test_opportunities
import layout
import pm_profile


class InitiativeAreaTests(unittest.TestCase):
    inline = "product/example/area/renewals"
    standalone = "product/example/area/billing"
    follow = "product/example/area/collections"

    def setUp(self):
        self.hub = test_opportunities.InitiativeTests()
        self.addCleanup(self.hub.doCleanups)
        self.hub.setUp()

    def set_areas(self, *subjects):
        return {"type": "set-areas", "initiative": self.hub.i, "areas": list(subjects),
                "source": "PM scope review, item 7"}

    def remit(self, *, status="confirmed", roles=(), follow=()):
        data = {"status": status, "responsibilities": list(roles), "follow": list(follow)}
        self.hub.cli("set-remit", value=data)

    def inline_context(self):
        entry = {"scope": "product", "product": "example", "product_area": "renewals",
                 "topic": "constraints", "question": "Which renewal window applies?"}
        self.hub.cli("route-context", "--write", self.hub.product_context, value={"sources": [], "entries": [entry]})

    def test_optional_areas_resolve_current_context_and_filter_each_portfolio_view(self):
        h = self.hub
        self.inline_context()
        area_path = layout.area("example", "billing")
        h.cli("new", "product-area-context", area_path, "--reason", "Finance checks the billing rules monthly.",
              "--trigger", "Review when billing policy changes.")
        self.remit(follow=[self.follow])
        contacts = [self.inline, self.standalone, self.follow]
        h.submit(h.setup_event(), {**h.capture(), "areas": contacts},
                 h.capture(h.product_id + "/other", "Tax labels", "Support ticket TAX-12"))
        report = h.trace()
        self.assertEqual(report["initiative"]["areas"], sorted(contacts))
        self.assertEqual(report["initiative"]["areas_source"], h.capture()["source"])
        self.assertEqual(report["context"]["areas"][self.standalone]["area_brief"], area_path)
        inline = report["context"]["areas"][self.inline]["inline"]
        self.assertEqual(inline[0]["path"], h.product_context)
        self.assertGreater(inline[0]["line"], 0)
        self.assertNotIn("Which renewal window applies?", json.dumps(report["context"]))
        self.assertEqual(report["context"]["areas"][self.follow]["remit"], {"path": pm_profile.PATH, "entries": ["follow"]})
        other = json.loads(h.cli("initiative", "show", "example", h.product_id + "/other"))
        self.assertEqual(other["initiative"]["areas"], [])
        self.assertEqual(other["context"]["areas"], {})

        rows = json.loads(h.cli("backlog", "--product", "example", "--area", "renewals"))
        self.assertEqual([row["id"] for row in rows], [h.i])
        self.assertEqual(rows[0]["areas"], sorted(contacts))
        self.assertEqual(rows, json.loads(h.cli("backlog", "--area", self.inline)))
        h.submit(self.set_areas(self.standalone))
        self.assertEqual(h.trace()["initiative"]["areas_source"], self.set_areas()["source"])
        self.assertEqual(json.loads(h.cli("backlog", "--area", self.inline)), [])

        h.submit(h.describe(), h.metric(), h.target(), h.decision("evaluate"), h.decision("prepare-brief"))
        h.brief_ready()
        h.submit(h.decision("approve-initiative"), h.cycle(), h.plan())
        h.preview(self.set_areas(), error="Reopen the initiative")
        rows = json.loads(h.cli("roadmap", "--product", "example", "--area", "billing"))
        self.assertEqual([(row["id"], row["areas"]) for row in rows], [(h.i, [self.standalone])])
        self.assertEqual(json.loads(h.cli("roadmap", "--area", self.follow)), [])
        row = next(csv.DictReader(StringIO(h.cli("roadmap", "--area", self.standalone, "--format", "csv"))))
        self.assertEqual(row["areas"], self.standalone)
        h.submit(h.decision("reopen"), self.set_areas())
        self.assertEqual(h.trace()["initiative"]["areas"], [])

    def test_reject_unknown_cross_product_and_unconfirmed_area_evidence(self):
        h = self.hub
        h.submit(h.setup_event(), h.capture())
        role = {"subject": "product/example", "role": "owner", "goals": [], "depends_on": [self.follow]}
        self.remit(roles=[role], follow=["area/renewals"])
        for bad in ([self.inline, self.inline], ["area/renewals"], ["renewals"], [None], self.inline):
            h.preview({**self.set_areas(), "areas": bad}, error="needs product areas")
        h.preview(self.set_areas("product/foreign/area/renewals"), error="scoped to product/example")
        h.preview(self.set_areas(self.inline), error="Unknown product area")
        h.submit(self.set_areas(self.follow))
        self.assertEqual(h.trace()["context"]["areas"][self.follow]["remit"]["entries"], ["depends_on"])
        self.remit(status="draft", follow=[self.follow])
        h.preview(self.set_areas(self.follow), error="Unknown product area")
        self.remit(roles=[{**role, "subject": self.inline}])
        h.submit(self.set_areas(self.inline))
        self.assertEqual(h.trace()["context"]["areas"][self.inline]["remit"]["entries"], ["responsibilities"])
        h.cli("roadmap", "--area", "renewals", error="full product area subject")
        h.cli("backlog", "--product", "example", "--area", "product/foreign/area/renewals", error="full product area subject")

    def test_approval_rechecks_live_evidence_and_preserves_signed_historical_links(self):
        h = self.hub
        self.remit(follow=[self.follow])
        h.submit(h.setup_event(), h.capture())
        proposed = h.preview(self.set_areas(self.follow))
        self.remit(status="draft", follow=[self.follow])
        h.apply(proposed, error="Unknown product area")
        self.remit(follow=[self.follow])
        h.submit(self.set_areas(self.follow))
        self.remit(status="draft", follow=[self.follow])
        report = h.trace()
        self.assertEqual(report["initiative"]["areas"], [self.follow])
        self.assertIn("Unknown product area", report["context"]["areas"][self.follow]["issue"])
        self.assertEqual(json.loads(h.cli("backlog", "--area", self.follow))[0]["id"], h.i)
        h.submit(h.describe(), h.decision("evaluate"))
        h.preview(h.decision("prepare-brief"), error="Unknown product area")
        h.submit(self.set_areas())
        self.assertEqual(h.trace()["initiative"]["areas"], [])

    def test_initiative_context_requires_owning_product_and_area_overview_requires_valid_parent(self):
        h = self.hub
        h.submit(h.setup_event(), h.capture())
        other_parent = layout.product("other")
        h.cli("new", "product-context", other_parent)
        context = layout.initiative("renewal")
        h.cli("new", "initiative-context", context, "--parent", other_parent)
        self.assertIsNone(h.trace()["context"]["initiative"])
        path = h.work / context
        path.write_text(path.read_text().replace("/products/other/", "/products/example/"))
        self.assertEqual(h.trace()["context"]["initiative"]["path"], context)
        area_path = layout.area("example", "billing")
        h.cli("new", "product-area-context", area_path, "--reason", "Finance consults these rules.",
              "--trigger", "Review after billing changes.")
        area = h.work / area_path
        area.write_text(area.read_text().replace("## Filing", "## Unverified filing"))
        h.preview(self.set_areas(self.standalone), error="filing")

    def test_same_area_slug_in_two_products_and_schema_contract(self):
        h = self.hub
        foreign_subject = "product/second/area/renewals"
        self.remit(follow=[self.inline, foreign_subject])
        h.submit(h.setup_event(), {**h.capture(), "areas": [self.inline]})
        second_context = layout.product("second")
        h.cli("new", "product-context", second_context)
        setup = {**h.setup_event(), "product_context": second_context}
        proposal = json.loads(h.cli("initiative", "propose", "second", value=[setup]))
        h.cli("initiative", "apply", "second", "--key", str(h.key), value=proposal)
        second_id = json.loads(h.cli("initiative", "show", "second"))["context"]["product"]["id"] + "/renewal"
        proposal = json.loads(h.cli("initiative", "propose", "second",
                                    value=[{**h.capture(second_id), "areas": [foreign_subject]}]))
        h.cli("initiative", "apply", "second", "--key", str(h.key), value=proposal)
        self.assertEqual([row["id"] for row in json.loads(h.cli("backlog", "--area", self.inline))], [h.i])
        rows = json.loads(h.cli("backlog", "--product", "second", "--area", "renewals"))
        self.assertEqual([row["id"] for row in rows], [second_id])
        schema = json.loads(h.cli("initiative", "schema"))
        self.assertEqual(schema["optional_fields_by_type"]["capture"]["areas"], "product areas")
        self.assertEqual(schema["fields_by_type"]["set-areas"], {"initiative": "initiative ID", "areas": "product areas",
                                                                 "source": "text"})
