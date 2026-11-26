"""Serve an isolated oryx installation with fictional PM records."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_opportunities import InitiativeTests, pm
import local_ui


def add_candidate(fixture, identifier, title, areas=()):
    fixture.submit(
        {**fixture.capture(identifier, title=title, source=f"Fixture evidence for {title}"), "areas": list(areas)},
        fixture.describe(identifier, problem=f"Customers report a blocked workflow for {title}"),
        fixture.target(identifier),
        fixture.decision("evaluate", identifier),
        fixture.decision("prepare-brief", identifier),
    )
    slug = identifier.split("/")[1]
    fixture.brief_ready(f"workspace/initiatives/example/{slug}/initiative-brief.md")
    fixture.submit(fixture.decision("approve-initiative", identifier))


def main():
    fixture = InitiativeTests()
    try:
        fixture.setUp()
        area = "product/example/area/renewals"
        fixture.cli("set-remit", value={"status": "confirmed", "responsibilities": [], "follow": [area]})
        fixture.submit(fixture.setup_event(), fixture.metric())
        add_candidate(fixture, fixture.i, "Renewal delays", [area])
        add_candidate(fixture, f"{fixture.product_id}/exports", "Export turnaround")
        confirmations = 0

        def confirm(root, review):
            # The browser tests cancel the first approval and confirm subsequent attempts.
            nonlocal confirmations
            confirmations += 1
            return confirmations > 1

        app = local_ui.App(fixture.root, pm.prepare_private_write, pm.run_initiative_work, confirm)
        with local_ui.make_server(app) as server:
            print(json.dumps({
                "url": f"{server.origin}/#{server.token}", "root": str(fixture.root),
                "today": fixture.today,
            }), flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
