"""Serve the oryx browser app on the presenter's machine."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import subprocess
import sys
from threading import Lock
from urllib.parse import urlencode
import webbrowser

import initiative_store
import layout
import customizations
import onboarding
import roadmap_edit
import storage
import task_context
import workspace

ASSETS = {
    "/": ("index.html", "text/html"),
    "/app.css": ("app.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
MAX_BODY = 1024 * 1024


def reviewed_comparison(root, path, revision):
    _, _, contents = initiative_store.local_markdown(root, path, "prioritization")
    if initiative_store.digest(contents) != revision:
        raise ValueError("The comparison changed. Review a fresh proposal")
    return contents.decode("utf-8")


class App:
    def __init__(self, root, prepare_write, run_work, confirm):
        self.root = root
        self.prepare_write = prepare_write
        self.run_work = run_work
        self.confirm = confirm
        self.approval_lock = Lock()
        self.review = None

    def require_setup(self):
        state = onboarding.status(workspace.repo(self.root, "workspace"))
        if not state["ready"]:
            raise onboarding.SetupRequired(state)

    def catalog(self):
        private = workspace.repo(self.root, "workspace")
        workspace.settings(self.root)
        products = {}
        for doc in task_context.context_documents(private).values():
            product = doc["product"]
            if not product:
                continue
            entry = products.setdefault(product, {"id": product, "title": product, "initiatives": {}, "roadmap": False})
            if doc["kind"] == "product-context":
                entry["title"] = doc["title"]
            if doc["kind"] == "initiative-context" and doc["parent"] == layout.product(product):
                entry["initiatives"][doc["initiative"]] = doc["title"]
        for product in initiative_store.products(self.root):
            entry = products.setdefault(product, {"id": product, "title": product, "initiatives": {}, "roadmap": False})
            entry["roadmap"] = True
            try:
                _, _, register = initiative_store.read(self.root, product)
            except (ValueError, OSError, subprocess.SubprocessError):
                # Its roadmap reports the register error. Context-owned lists remain available.
                continue
            entry["initiatives"].update((item["id"].split("/")[1], item["title"]) for item in register.items.values())
        ordered = sorted(products.values(), key=lambda entry: (entry["title"].casefold(), entry["id"]))
        return {"products": ordered, "can_approve": not initiative_store.in_agent_session()}

    def preview(self, product, body):
        with self.approval_lock:
            if body.get("mode") == "new":
                changes = roadmap_edit.new_cycle_changes(body)
                cycle_event = changes[0]
                roadmap_edit.save_comparison(
                    self.root, product, cycle_event["cycle"], cycle_event["options"], body["sections"],
                    body["comparison_revision"], body["revision"], self.prepare_write, body.get("starter_revision"),
                )
            elif body.get("mode") == "edit":
                changes = roadmap_edit.placement_changes(self.root, product, body)
            else:
                raise ValueError("Choose a cycle to create or edit")
            proposal, _, _, register = initiative_store.prepare(self.root, product, changes)
            roadmap_edit.check_revision(proposal["base"], body.get("revision"))
            cycles = {event["cycle"] for event in changes if "cycle" in event}
            cycles.add(body["cycle"])
            documents = []
            for cycle in sorted(cycles):
                reference = register.cycles[cycle]["references"]
                path = layout.prioritization(product, cycle)
                if reference["path"] != path:
                    raise ValueError("The approved comparison must belong to this product and cycle")
                contents = reviewed_comparison(self.root, path, reference["sha256"])
                documents.append({"path": path, "text": contents, "revision": reference["sha256"]})
            titles = {event["initiative"]: register.items[event["initiative"]]["title"]
                      for event in changes if "initiative" in event}
            identifier = secrets.token_urlsafe(24)
            public = {"id": identifier, "product": product, "revision": proposal["revision"], "changes": changes,
                      "documents": documents, "titles": titles}
            self.review = (public, proposal)
            return public

    def approve(self, identifier):
        if initiative_store.in_agent_session():
            raise ValueError("Open oryx from your own terminal to approve this roadmap change")
        with self.approval_lock:
            if self.review is None or identifier != self.review[0]["id"]:
                raise ValueError("Review a current proposal before approval")
            review, proposal = self.review
            self.prepare_write(self.root)
            current, _, _, _ = initiative_store.prepare(self.root, review["product"], proposal["changes"])
            if current != proposal:
                self.review = None
                raise ValueError("The roadmap or comparison changed. Review a fresh proposal")
            self.check_documents(review)
            if not self.confirm(self.root, review):
                return {"cancelled": True}
            try:
                with storage.writer_lock(storage.private_root(self.root)):
                    self.require_setup()
                    self.check_documents(review)
                    revision = initiative_store.apply(self.root, review["product"], proposal,
                                                      approved_revision=review["revision"])
            finally:
                self.review = None
            return {"revision": revision}

    def check_documents(self, review):
        # Releasing the last placement can remove its comparison from the register's live checks.
        for doc in review["documents"]:
            reviewed_comparison(self.root, doc["path"], doc["revision"])

    def dispatch(self, path, body):
        self.require_setup()
        if path == "/api/catalog":
            return self.catalog()
        if path == "/api/approve":
            return self.approve(body["id"])
        product = layout.slug(body["product"])
        if path == "/api/work":
            command, operation = body["command"], body["operation"]
            if command not in ("task", "launch-checklist") or operation not in ("list", "apply", "init"):
                raise ValueError("Choose an initiative work operation")
            if operation == "init" and command != "launch-checklist":
                raise ValueError("Only a launch checklist can start from a template")
            return self.run_work(
                self.root, command, operation, product, layout.slug(body["initiative"]),
                expected=body.get("revision"), changes=body.get("changes"),
                write=operation != "list" and body.get("save") is True,
                **({"starter_revision": body["starter_revision"]} if "starter_revision" in body else {}),
            )
        if path == "/api/roadmap-fields":
            values = body["values"]
            if not isinstance(values, dict):
                raise ValueError("Supply the initiative field values")
            self.prepare_write(self.root)
            return customizations.apply(self.root, {"revision": body["revision"], "values": [
                {"product": product, "id": body["id"], "field": key, "value": value} for key, value in values.items()]})
        workspace.repo(self.root, "workspace")
        workspace.settings(self.root)
        if path == "/api/roadmap":
            return roadmap_edit.board(self.root, product, body.get("view"))
        if path == "/api/roadmap-export":
            board = roadmap_edit.board(self.root, product, body["view"])
            view = board["presentation"]
            if (view.get("warning") or view["name"] != body["view"]
                    or ("revision" in body and body["revision"] != view["revision"])
                    or ("board_revision" in body and body["board_revision"] != board["revision"])):
                raise ValueError("The custom view changed. Refresh the roadmap before exporting.")
            rows = [row for row in board["rows"] if row["cycle"] == body["cycle"]
                    and (not body.get("area") or body["area"] in row["areas"])]
            return {"html": customizations.page(self.root, view, rows, expected_page=body.get("page_revision"))}
        if path == "/api/comparison-template":
            return roadmap_edit.comparison_template(self.root, product)
        if path == "/api/comparison":
            return roadmap_edit.comparison(self.root, product, layout.slug(body["cycle"]))
        if path == "/api/candidate":
            _, register = roadmap_edit.snapshot(self.root, product)
            item = register.items.get(body["initiative"])
            if item is None or item["phase"] != "candidate":
                raise ValueError("Choose an approved roadmap candidate")
            reference = item["initiative_brief"]
            _, _, contents = initiative_store.local_markdown(self.root, reference["path"], "initiative-brief")
            if initiative_store.digest(contents) != reference["sha256"]:
                raise ValueError("The Initiative Brief changed. Review the approved revision")
            return {"text": contents.decode("utf-8"), "path": reference["path"]}
        if path == "/api/roadmap-preview":
            return self.preview(product, body)
        raise ValueError("Unknown oryx operation")


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(15)
        super().setup()

    def log_message(self, *args):
        pass

    def respond(self, code, content_type, data):
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def json_response(self, code, payload):
        self.respond(code, "application/json", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def local_host(self):
        return self.headers.get_all("Host") == [self.server.host]

    def do_GET(self):
        if not self.local_host():
            self.json_response(403, {"error": "Use the local oryx address"})
            return
        asset = ASSETS.get(self.path.partition("?")[0])
        if asset is None:
            self.json_response(404, {"error": "Page not found"})
            return
        file, media_type = asset
        content = (self.server.app.root / "tools" / "local_ui" / file).read_bytes()
        self.respond(200, media_type, content)

    def do_POST(self):
        if (not self.local_host() or self.headers.get_all("Origin") != [self.server.origin]
                or not secrets.compare_digest(self.headers.get("X-PM-Hub-Token", "").encode(), self.server.token.encode())):
            self.json_response(403, {"error": "Open this session from the oryx launcher"})
            return
        try:
            lengths = self.headers.get_all("Content-Length") or []
            if (self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding")
                    or len(lengths) != 1 or not 0 < int(lengths[0]) <= MAX_BODY):
                raise ValueError("Supply a JSON request under 1 MiB")
            body = storage.json_input(self.rfile.read(int(lengths[0])).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("Supply a JSON object")
            result = self.server.app.dispatch(self.path, body)
        except onboarding.SetupRequired as exc:
            step = {key: exc.state[key] for key in ("stage", "stage_available", "prompt")}
            self.json_response(409, onboarding.required(step))
        except (KeyError, TypeError, AttributeError):
            self.json_response(400, {"error": "Supply the fields for this oryx operation"})
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.json_response(400, {"error": str(exc)})
        else:
            self.json_response(200, result)


def make_server(app):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.app = app
    server.host = f"127.0.0.1:{server.server_port}"
    server.origin = "http://" + server.host
    server.token = secrets.token_urlsafe(32)
    return server


def confirm_on_desktop(root, review):
    prompt = root / "tools" / "local_ui" / "confirm.py"
    response = subprocess.run([sys.executable, str(prompt)], input=json.dumps(review), text=True, capture_output=True)
    if response.returncode == 0:
        return True
    if response.returncode == 1:
        return False
    raise ValueError("The approval window could not open. Start oryx from your desktop with Tk available")


def serve(root, no_open, prepare_write, run_work, *, screen="roadmap"):
    workspace.repo(root, "workspace")
    workspace.settings(root)
    app = App(root, prepare_write, run_work, confirm_on_desktop)
    with make_server(app) as server:
        query = urlencode({"screen": screen})
        address = f"{server.origin}/?{query}#{server.token}"
        print(f"oryx is open at {address}", flush=True)
        if not no_open:
            webbrowser.open(address)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
