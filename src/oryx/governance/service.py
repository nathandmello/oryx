"""Customer Unix peer daemon and provisioning entry. User actions arrive on its restricted socket."""
import argparse
import base64
import json
import os
from pathlib import Path
import socket
import socketserver
import struct
import sys

from .common import LIMIT, canonical, decode, identifier, shape
from .peer import Peer, initialize
from oryx.sharing import effects


def operate(c, op, b):
    def fields(*required, optional=()):
        return shape(b, required, optional)
    if op == "scope":
        fields("scope")
        return c.scope(b["scope"])
    if op == "sync":
        fields("scope", optional=("expected_actor",))
        if "expected_actor" in b and c.actor != b["expected_actor"]:
            raise PermissionError("The current principal differs from the connected scope")
        return c.sync(b["scope"])
    if op == "read":
        fields("scope","kind","id",optional=("revision",))
        return c.record(b["scope"], b["kind"], b["id"], b.get("revision"))
    if op == "owner":
        fields("id")
        row = c.db.execute("SELECT * FROM owners WHERE id=?", (b["id"],)).fetchone()
        if not row or "read" not in c.rights(row["scope"]):
            raise PermissionError("Authoritative home unavailable")
        return dict(row)
    if op == "resolve":
        fields("scope","id")
        return c.metric(b["scope"], b["id"])
    if op == "report":
        fields("scope","id","as_of")
        return c.report(b["scope"],b["id"],b["as_of"])
    if op == "reviews":
        fields(optional=("scope",))
        if "scope" in b:
            c.require(b["scope"], "read")
        return [effects.proposal_info(c,r) for r in c.db.execute("SELECT * FROM proposals WHERE status='open' ORDER BY id")
                if ("scope" not in b or r["scope"] == b["scope"]) and {"read","review"} <= c.rights(r["scope"]) and c.actor != r["actor"]
                and c.actor in json.loads(r["body"])["audience"]]
    if op in {"authorize", "disclosure-status"}:
        fields("scope","commitment","audience","base")
        info = c.scope(b["scope"])
        if info["audience"] != b["audience"] or info["revision"] != b["base"]:
            raise ValueError("Destination changed since local review")
        if op == "disclosure-status":
            return {"proposal":effects.approved_digest(c,b["commitment"],b["scope"])}
        return effects.approval(c,b["commitment"],b["scope"])
    if op in {"propose","transfer"}:
        if b.get("operation") != op:
            raise ValueError("Disclosure operation does not match the approved intent")
        return effects.propose(c,b)
    if op == "reconcile" and "effect" in b:
        fields("scope","effect")
        c.require(b["scope"],"read")
        receipt=c.db.execute("SELECT * FROM receipts WHERE id=? AND scope=?", (b["effect"],b["scope"])).fetchone()
        return dict(receipt) if receipt else {"status":"unconfirmed"}
    if op == "proposal-status":
        fields("scope","commitment")
        c.require(b["scope"],"read")
        key=effects.commit_id(c,b["commitment"])
        cancelled=c.db.execute("SELECT scope FROM receipts WHERE id=?",(key+"/cancel",)).fetchone()
        if cancelled:
            return {"id":key,"scope":cancelled["scope"],"status":"closed"}
        rec=c.db.execute("SELECT * FROM proposals WHERE id=? AND scope=?",(key,b["scope"])).fetchone()
        return effects.proposal_info(c,rec) if rec else {"status":"unconfirmed"}
    if op == "cancel-unpushed":
        fields("scope","commitment")
        c.human()
        scope=b["scope"]
        c.require(scope,"read")
        key=effects.approved_digest(c,b["commitment"],scope)
        rec=c.db.execute("SELECT * FROM proposals WHERE id=?",(key,)).fetchone()
        if rec and (rec["status"]!="prepared" or c.git(scope).ref("refs/heads/proposals/"+key)):
            raise ValueError("The proposal exists at the destination; inspect and close its exact candidate")
        c.receipt(key+"/cancel","cancel-unpushed",scope,key)
        if rec:
            c.db.execute("UPDATE proposals SET status='closed' WHERE id=?",(key,))
        return {"id":key,"scope":scope,"status":"closed"}
    if op == "close":
        fields("proposal","candidate")
        c.human()
        r=effects.row(c,b["proposal"])
        if c.actor!=r["actor"] or b["candidate"]!=r["candidate"] or r["status"] not in {"open","approved","closed"}:
            raise PermissionError("The submitting PM may close only the current unmerged proposal")
        c.require(r["scope"],"propose")
        c.db.execute("UPDATE proposals SET status='closed' WHERE id=?", (r["id"],))
        c.receipt(r["id"]+"/close","close",r["scope"],r["candidate"])
        return effects.proposal_info(c,effects.row(c,r["id"]))
    if op in {"inspect","reconcile"}:
        fields("proposal")
        cancelled=c.db.execute("SELECT * FROM receipts WHERE id=? AND effect='cancel-unpushed'",(b["proposal"]+"/cancel",)).fetchone()
        if cancelled and op=="reconcile":
            c.require(cancelled["scope"],"read")
            return {"id":b["proposal"],"scope":cancelled["scope"],"status":"closed"}
        r = effects.row(c,b["proposal"])
        if c.actor not in json.loads(r["body"])["audience"]:
            raise PermissionError("Proposal is outside its reviewed audience")
        result = effects.proposal_info(c,r)
        if op == "inspect":
            intent=json.loads(r["body"])
            result["intent"]=intent
            from .peer import storage_path
            previous=c.git(r["scope"]).get(r["base"],storage_path(intent["kind"],intent["id"]))
            if previous:
                c.deliverable(r["scope"],previous)
            result["previous"]=previous
        return result
    if op == "review":
        fields("proposal","candidate","approve")
        return effects.review(c,b["proposal"],b["candidate"],b["approve"])
    if op == "merge":
        fields("proposal","candidate")
        return effects.merge(c,b["proposal"],b["candidate"])
    if op in {"publish","send"}:
        if b.get("operation") != op:
            raise ValueError("Disclosure operation does not match the approved intent")
        return effects.dispatch_direct(c,b)
    if op == "page":
        fields("scope","page")
        return effects.read_page(c,b["scope"],b["page"])
    if op == "delivery":
        fields("id","scope")
        c.require(b["scope"], "read")
        row = c.db.execute("SELECT * FROM deliveries WHERE id=? AND scope=?", (b["id"], b["scope"])).fetchone()
        if not row or c.actor not in json.loads(row["audience"]):
            raise PermissionError("Delivery is outside its reviewed audience")
        effects.check_distribution(c,row["id"])
        result={"scope":b["scope"],"content":row["body"],"source_revision":row["source_rev"],
                "source_last_updated":row["source_updated"],"sent":row["stamp"]}
        if c.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='renditions'").fetchone():
            artifact=c.db.execute("SELECT format,data FROM renditions WHERE id=?",(b["id"],)).fetchone()
            if artifact:
                result.update(format=artifact["format"],data_base64=base64.b64encode(artifact["data"]).decode("ascii"))
        return result
    raise ValueError("Unknown customer peer operation")


def peer_uid(sock):
    if hasattr(socket, "SO_PEERCRED"):
        return struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))[1]
    if hasattr(sock, "getpeereid"):
        return sock.getpeereid()[0]
    raise PermissionError("Kernel peer credentials are unavailable")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.connection.settimeout(15)
            uid = peer_uid(self.connection)
            req = shape(decode(self.rfile.readline(LIMIT + 1)), ("organization","operation","payload"))
            with self.server.peer.operation(uid, req["organization"]) as ctx:
                result = operate(ctx,req["operation"],req["payload"])
            reply = {"ok":True,"result":result}
            if len(canonical(reply)) >= LIMIT:
                raise ValueError("Response exceeds the scoped retrieval limit")
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            reply = {"ok":False,"error":str(exc)}
        except Exception:
            reply={"ok":False,"error":"Customer peer could not confirm the effect; reconcile before retrying"}
        self.wfile.write(canonical(reply) + b"\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    choices=p.add_subparsers(dest="command",required=True)
    init=choices.add_parser("init");init.add_argument("--store",type=Path,required=True);init.add_argument("--roster",type=Path,required=True)
    serve=choices.add_parser("serve");serve.add_argument("--store",type=Path,required=True);serve.add_argument("--socket",type=Path,required=True)
    a=p.parse_args(argv)
    if a.command=="init":
        initialize(a.store, decode(a.roster.read_bytes()))
        return 0
    # Provision the socket directory separately so clients can connect without access to the private store.
    path=a.socket.absolute()
    parent=path.parent
    if path.resolve()!=path or parent.stat().st_uid not in {0,os.geteuid()} or parent.stat().st_mode & 0o022:
        raise PermissionError("Provision a protected socket directory first")
    with socketserver.UnixStreamServer(str(path),Handler) as server:
        server.peer=Peer(a.store)
        os.chmod(path,0o666)  # Every operation separately authenticates kernel UID and current scope rights.
        try:
            server.serve_forever()
        finally:
            path.unlink(missing_ok=True)
    return 0


if __name__=="__main__":
    sys.exit(main())
