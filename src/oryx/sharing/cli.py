"""Local exact review and customer peer operations using JSON on standard input."""
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from oryx.governance.client import request
from oryx.governance.cli import arguments, private_root, read_body
from oryx.governance.common import SHA, canonical, digest, shape
from oryx.governance.files import directory, read, save
from . import transfer
from .render import MIME, rendition


def prepare(private, body, call=request):
    shape(body, ("operation","scope","id"), ("kind","content","last_updated","references","source_scope","page","expected_page","live","format","recipients"))
    op=body["operation"]
    if op not in {"propose","publish","send","transfer"}:
        raise ValueError("Choose the specific outward operation")
    info=call("scope",{"scope":body["scope"]})
    intent={"operation":op,"scope":info["scope"],"base":info["revision"],"audience":info["audience"],
            "kind":body.get("kind","record"),"id":body["id"],"references":body.get("references",[])}
    if op=="transfer" or (op in {"send","publish"} and "source_scope" not in body):
        source,data,modified=transfer.source(private,body["id"])
        intent.update(source={k:source[k] for k in ("workspace_id","id","revision")},content=data.decode(),
                      last_updated=datetime.fromtimestamp(modified,timezone.utc).isoformat())
    elif op in {"send","publish"}:
        source=call("read",{"scope":body.get("source_scope"),"id":body["id"],"kind":"record"})
        rec=source["record"]
        intent.update(content=rec["content"],last_updated=rec["last_updated"],references=rec["references"],
                      source={"scope":source["scope"],"id":rec["id"],"kind":rec["kind"],"revision":source["revision"]})
    else:
        intent.update(content=body["content"],last_updated=body["last_updated"])
    if op=="publish":
        if "workspace_id" in intent["source"] and body.get("live",False):
            raise ValueError("Use a shared authoritative source for unattended live refresh, or publish this private snapshot")
        intent.update(page=body["page"],expected_page=body["expected_page"],live=body.get("live",False))
    if op=="send":
        intent.update(format=body.get("format","md"),recipients=body.get("recipients",info["audience"]))
    key=digest(canonical(intent))
    draft={"organization":info["organization"],"actor":info["actor"],"commitment":key,"intent":intent}
    folder=directory(private,".oryx/staging/sharing",True)
    save(folder / (key+".json"),draft)
    return draft


def staged(private, key):
    if not isinstance(key,str) or not SHA.fullmatch(key):
        raise ValueError("Supply the exact staged commitment")
    document=read(directory(private,".oryx/staging/sharing") / (key+".json"))
    if document.get("commitment")!=key or digest(canonical(document["intent"]))!=key:
        raise ValueError("Sharing draft changed; review it again")
    return document


def authorize(draft, call=request):
    intent=draft["intent"]
    info=call("scope",{"scope":intent["scope"]})
    if (info["actor"]!=draft["actor"] or info["organization"]!=draft["organization"] or info["revision"]!=intent["base"]
            or info["audience"]!=intent["audience"]):
        raise ValueError("The reviewed actor, audience or destination revision changed")
    # Reopen the controlling terminal rather than treating agent-supplied standard input as a PM gesture.
    with open("/dev/tty","r+",encoding="utf-8") as tty:
        tty.write("This first external write exposes the exact material below to the named destination audience.\n")
        tty.write(json.dumps(intent,indent=2,ensure_ascii=True)+"\n")
        tty.write("Type DISCLOSE to authorize this revision and audience: ");tty.flush()
        if tty.readline().strip()!="DISCLOSE":
            return {"status":"kept-private","commitment":draft["commitment"]}
    return call("authorize",{"scope":intent["scope"],"commitment":draft["commitment"],"base":intent["base"],"audience":intent["audience"]})


def export(private,body,call=request):
    shape(body,("id","format"),("source_scope","output"))
    fmt=body["format"]
    if "source_scope" in body:
        src=call("read",{"scope":body["source_scope"],"kind":"record","id":body["id"]})
        text,stamp=src["record"]["content"],src["record"]["last_updated"]
    else:
        _,data,modified=transfer.source(private,body["id"])
        text,stamp=data.decode(),datetime.fromtimestamp(modified,timezone.utc).isoformat()
    rendered=rendition(fmt,text,stamp)
    result={"format":fmt,"mime":MIME[fmt],"source_last_updated":stamp,"sha256":digest(rendered),"size":len(rendered)}
    if body.get("output"):
        path=Path(body["output"])
        if not path.is_absolute() or path.resolve()!=path or private==path or private in path.parents:
            raise ValueError("Select a new export file outside the authoritative Workspace")
        with path.open("xb") as output:
            os.fchmod(output.fileno(),0o600)
            output.write(rendered)
        result["output"]=str(path)
    else:
        result["data_base64"]=base64.b64encode(rendered).decode("ascii")
    return result



def submit(private,draft,call):
    intent=draft["intent"]
    info=call("scope",{"scope":intent["scope"]})
    if info["actor"]!=draft["actor"] or info["organization"]!=draft["organization"]:
        raise ValueError("Selected actor or peer changed")
    key=digest(canonical([draft["organization"],draft["actor"],draft["commitment"]]))
    # Recover receipts using only the commitment before sending any previously reviewed text.
    if intent["operation"]=="transfer":
        existing=transfer.status(private,intent["id"])
        if existing and existing["proposal"]==key and existing["status"]=="transferred":
            return existing
    if intent["operation"] in {"send","publish"}:
        prior=call("reconcile",{"scope":intent["scope"],"effect":key})
        if prior.get("id")==key and prior.get("effect")==intent["operation"]:
            return prior
    else:
        prior=call("proposal-status",{"scope":intent["scope"],"commitment":draft["commitment"]})
        if prior.get("id")==key and prior.get("status") in {"open","approved","merged","closed"}:
            return prior
    verified=call("disclosure-status",{"scope":intent["scope"],"base":intent["base"],
                  "audience":intent["audience"],"commitment":draft["commitment"]})
    if verified.get("proposal")!=key:
        raise PermissionError("Cannot confirm exact pre-disclosure authorization")
    if intent["operation"]=="transfer":
        transfer.begin(private,intent,draft["organization"],draft["actor"])
    elif "workspace_id" in intent.get("source",{}):
        row,data,_=transfer.source(private,intent["id"])
        if row["workspace_id"]!=intent["source"]["workspace_id"] or digest(data)!=intent["source"]["revision"]:
            raise ValueError("Private source changed after disclosure review")
    return call(intent["operation"],intent)


def main(argv=None):
    names=("preview","authorize","propose","inspect","review","merge","reconcile","export","publish","page","delivery","send","transfer","close")
    args=arguments(argv,names)
    try:
        body=read_body();op=args.operation
        if op=="preview":
            result=prepare(private_root(args.workspace),body)
        elif op in {"review","merge"}:
            required=("proposal","candidate","approve") if op=="review" else ("proposal","candidate")
            shape(body,required)
            candidate=request("inspect",{"proposal":body["proposal"]})
            if candidate["candidate"]!=body["candidate"]:
                raise ValueError("Inspect the updated proposal before deciding")
            with open("/dev/tty","r+",encoding="utf-8") as terminal:
                terminal.write(json.dumps(candidate,indent=2,ensure_ascii=True)+"\n")
                action=("APPROVE" if body["approve"] else "DECLINE") if op=="review" else "MERGE"
                terminal.write(f"Type {action} to apply this exact decision: ")
                terminal.flush()
                if terminal.readline().strip()!=action:
                    return _print({"status":"no-decision","candidate":candidate["candidate"]})
            result=request(op,body)
        elif op=="export":
            result=export(private_root(args.workspace),body)
        elif op=="close" and "record_id" in body:
            shape(body,("record_id","commitment"))
            private=private_root(args.workspace)
            draft=staged(private,body["commitment"])
            intent=draft["intent"]
            if intent["operation"]!="transfer" or intent["id"]!=body["record_id"]:
                raise ValueError("Select the exact pending ownership transfer")
            request("cancel-unpushed",{"scope":intent["scope"],"commitment":draft["commitment"]})
            result=transfer.reconcile(private,body["record_id"],request)
        elif op=="reconcile" and "record_id" in body:
            result=transfer.reconcile(private_root(args.workspace),body["record_id"],request)
        elif op in {"authorize","propose","publish","send","transfer"}:
            shape(body,("commitment",))
            private=private_root(args.workspace);draft=staged(private,body["commitment"]);intent=draft["intent"]
            if op=="authorize":
                result=authorize(draft)
            else:
                if op!=intent["operation"]:
                    raise ValueError("Outward operation differs from the staged review")
                result=submit(private,draft,request)
        else:
            result=request(op,body)
        return _print(result)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        print(str(exc),file=sys.stderr)
        return 1


def _print(result):
    print(json.dumps(result,ensure_ascii=True));return 0
