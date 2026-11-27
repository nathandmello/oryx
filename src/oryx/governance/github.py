"""Governed GitHub.com reads and head-bound merges under the acting customer credential."""
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import build_opener, HTTPRedirectHandler, Request

from .common import LIMIT, SHA, canonical, decode, digest, identifier, record_id, shape
from .files import directory, read, save

ENROLLMENT = Path("/etc/oryx/github.json")
OID = re.compile(r"[a-f0-9]{40}\Z")
REVIEW_QUERY = """query($owner:String!,$name:String!,$number:Int!){
 repository(owner:$owner,name:$name){pullRequest(number:$number){
 headRefOid baseRefOid reviewDecision mergeStateStatus}}}"""


def positive(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Expected a positive provider identity or pull number")
    return value


def oid(value):
    if not isinstance(value, str) or not OID.fullmatch(value):
        raise ValueError("Expected a GitHub commit identity")
    return value


def relative_path(value):
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+",value)
            or value.startswith("/") or value != str(PurePosixPath(value))
            or any(part in {".","..",".git"} for part in value.split("/"))):
        raise ValueError("Expected a registered repository-relative file")
    return value


def load_enrollment():
    path=ENROLLMENT
    if path.resolve()!=path or not path.is_file():
        raise PermissionError("Customer GitHub enrollment is unavailable")
    for node in (path,*path.parents):
        st=node.stat()
        if st.st_uid!=0 or st.st_mode & 0o022:
            raise PermissionError("Customer GitHub enrollment must be root-controlled")
    return decode(path.read_bytes())


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubAPI:
    """Fixed HTTPS origin, one immutable GraphQL read and a single typed merge effect."""
    def __init__(self):
        self.token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            executable=shutil.which("gh",path=os.defpath)
            if not executable:
                raise PermissionError("An authenticated GitHub user credential is required")
            result=subprocess.run([executable,"auth","token","--hostname","github.com"],
                                  capture_output=True,timeout=15,check=False)
            if result.returncode:
                raise PermissionError("The active GitHub.com credential is unavailable")
            self.token=result.stdout.decode("ascii").strip()
        self.http=build_opener(NoRedirect())

    def fetch(self, path, variables=None):
        if not path.startswith("/") or path.startswith("//") or (variables is not None and path!="/graphql"):
            raise ValueError("Invalid GitHub adapter endpoint")
        data=canonical({"query":REVIEW_QUERY,"variables":variables}) if variables is not None else None
        return self._request(path,data,"POST" if data else "GET")

    def lookup(self,path):
        try:
            return self.fetch(path)
        except FileNotFoundError:
            return None

    def create(self,slug,kind,body):
        owner,name=slug.split("/")
        routes={"tree":"git/trees","commit":"git/commits","ref":"git/refs","draft":"pulls"}
        if kind not in routes:
            raise ValueError("Unsupported GitHub proposal effect")
        path=f"/repos/{identifier(owner)}/{identifier(name)}/{routes[kind]}"
        return self._request(path,canonical(body),"POST")

    def merge(self,slug,number,head):
        owner,name=slug.split("/")
        path=f"/repos/{identifier(owner)}/{identifier(name)}/pulls/{positive(number)}/merge"
        return self._request(path,canonical({"sha":oid(head),"merge_method":"merge"}),"PUT")

    def _request(self,path,data,method):
        req=Request("https://api.github.com"+path,data=data,method=method,headers={"Authorization":"Bearer "+self.token,
                    "Accept":"application/vnd.github+json","User-Agent":"oryx-customer-governance",
                    "Content-Type":"application/json","X-GitHub-Api-Version":"2022-11-28"})
        try:
            with self.http.open(req,timeout=15) as response:
                return decode(response.read(LIMIT+1))
        except HTTPError as exc:
            if method=="GET" and exc.code==404:
                raise FileNotFoundError("Registered GitHub resource is absent or inaccessible") from exc
            if method=="PUT" and 400<=exc.code<500:
                raise PermissionError(f"GitHub declined the merge (HTTP {exc.code}); reconcile the PR") from exc
            raise RuntimeError("GitHub response is uncertain; reconcile the PR") from exc
        except (URLError,TimeoutError) as exc:
            raise PermissionError("GitHub could not confirm this operation under the acting credential") from exc


class Connection:
    def __init__(self,settings,api,uid):
        shape(settings, ("principals","repositories"), ("human_effects",))
        self.human_effects=settings.get("human_effects",{}).get(str(uid),{})
        account=settings["principals"].get(str(uid))
        if not account:
            raise PermissionError("OS principal has no enrolled GitHub user")
        self.api=api
        user=api.fetch("/user")
        if positive(user["id"])!=positive(account):
            raise PermissionError("Active GitHub identity differs from customer enrollment")
        self.account=positive(user["id"])
        self.login=identifier(user["login"])
        self.config=settings["repositories"]
        owners={}
        for scope,repo in self.config.items():
            for rid in repo.get("records",{}):
                if record_id(rid) in owners:
                    raise ValueError("A GitHub record has multiple registered authoritative homes")
                owners[rid]=scope

    def repo(self,scope):
        value=self.config[identifier(scope)]
        shape(value,("slug","id","owner_id","branch","reports"),("protection","records","destination_drafts","disclosure"))
        owner,name=value["slug"].split("/")
        path="/repos/"+identifier(owner)+"/"+identifier(name)
        identifier(value["branch"])
        current=self.api.fetch(path)
        if (current["id"]!=positive(value["id"]) or current["owner"]["id"]!=positive(value["owner_id"])
                or current["full_name"].casefold()!=value["slug"].casefold() or current["owner"]["type"]!="Organization"
                or current["permissions"].get("pull") is not True):
            raise PermissionError("Registered repository identity, organization or current read permission changed")
        return value,path,current

    def tip(self,path,reg):
        return oid(self.api.fetch(path+"/branches/"+quote(reg["branch"],safe=""))["commit"]["sha"])

    def content(self,path,filename,revision):
        entry=self.api.fetch(path+"/contents/"+relative_path(filename)+"?ref="+oid(revision))
        if entry["type"]!="file" or entry["encoding"]!="base64" or entry["path"]!=filename:
            raise ValueError("GitHub did not return the registered file")
        try:
            raw=base64.b64decode(entry["content"].replace("\n",""),validate=True)
        except (ValueError,binascii.Error) as exc:
            raise ValueError("Invalid GitHub file encoding") from exc
        return decode(raw),digest(raw)

    def registered_record(self,reg,path,rid,revision):
        filename=relative_path(reg.get("records",{})[record_id(rid)])
        if not filename.startswith("context/records/"):
            raise ValueError("Register an authoritative record in context/records")
        value,_=self.content(path,filename,revision)
        shape(value,("id","kind","content","source_revision"))
        if (value["id"]!=rid or value["kind"]!="record" or not isinstance(value["content"],str)
                or digest(value["content"].encode())!=value["source_revision"]):
            raise ValueError("GitHub record identity or exact bytes do not match its declared revision")
        return value

    def descendant(self,path,earlier,later):
        if earlier==later:
            return
        compared=self.api.fetch(path+"/compare/"+oid(earlier)+"..."+oid(later)+"?per_page=1")
        if compared["status"]!="ahead" or compared["merge_base_commit"]["sha"]!=earlier:
            raise ValueError("Expected commit is outside the official GitHub history")

    def inbox(self,path,reg):
        qualifiers=["review-requested:@me"]
        for page in range(1,21):
            teams=self.api.fetch("/user/teams?"+urlencode({"per_page":100,"page":page}))
            if not isinstance(teams,list):
                raise PermissionError("Cannot confirm GitHub team membership")
            for team in teams:
                if team["organization"]["id"]==reg["owner_id"]:
                    organization=identifier(team["organization"]["login"])
                    slug=identifier(team["slug"])
                    qualifiers.append("team-review-requested:"+organization+"/"+slug)
            if len(teams)<100:
                break
        else:
            raise ValueError("GitHub team inventory is incomplete")
        if len(qualifiers)>100:
            raise ValueError("GitHub review inventory exceeds the supported team count")
        items={}
        for qualifier in qualifiers:
            search="/search/issues?"+urlencode({"q":"repo:"+reg["slug"]+" is:pr is:open "+qualifier,"per_page":100})
            result=self.api.fetch(search)
            if result["incomplete_results"] or len(result["items"])!=result["total_count"]:
                raise ValueError("GitHub review inbox is incomplete")
            for item in result["items"]:
                if item["repository_url"]!="https://api.github.com"+path or "pull_request" not in item:
                    raise ValueError("Review inbox returned another repository or object type")
                number=positive(item["number"])
                items[number]={"pull":number,"destination":reg["slug"],"title":item["title"]}
        return [items[number] for number in sorted(items)]

    def pull(self,path,reg,number,head):
        pr=self.api.fetch(path+"/pulls/"+str(positive(number)))
        if (pr["state"]!="open" or pr["draft"] is not False or pr["base"]["repo"]["id"]!=reg["id"]
                or pr["head"]["repo"]["id"]!=reg["id"] or pr["base"]["ref"]!=reg["branch"]
                or pr["head"]["sha"]!=oid(head) or pr["base"]["sha"]!=self.tip(path,reg)):
            raise ValueError("Pull request is not the enrolled open candidate against the current official branch")
        return pr

    def policy(self,path,reg,number,head):
        pr=self.pull(path,reg,number,head)
        changed=self.api.fetch(path+"/pulls/"+str(number)+"/files?per_page=100")
        if not changed or len(changed)!=pr["changed_files"] or len(changed)>100:
            raise ValueError("Candidate change inventory is incomplete")
        records=reg.get("records",{})
        if len(set(records.values()))!=len(records):
            raise ValueError("Multiple record identities refer to one GitHub file")
        record_paths={v:k for k,v in records.items()}
        receipts=[]
        for entry in changed:
            filename=relative_path(entry["filename"])
            if filename in record_paths:
                if len(changed)!=1 or entry["status"]!="added" or filename in reg["reports"]:
                    raise ValueError("Ownership transfer requires exactly one new registered record")
                commit=self.api.fetch(path+"/git/commits/"+head)
                if commit["sha"]!=head or [p["sha"] for p in commit["parents"]]!=[pr["base"]["sha"]]:
                    raise ValueError("Transfer must contain one commit rooted directly in destination history")
                rid=record_paths[filename]
                record=self.registered_record(reg,path,rid,head)
                key="new_record" if rid in reg.get("destination_drafts",[]) else "record"
                receipts.append({key:rid,"path":filename,"source_revision":record["source_revision"]})
                continue
            if entry["status"] not in {"added","modified"} or filename not in reg["reports"]:
                raise ValueError("Change requires owner review outside the supported structured-report policy")
            control=reg["reports"][filename]
            shape(control,("owner_scope","definition_path","metric","dataset","scope"))
            owner,owner_path,_=self.repo(control["owner_scope"])
            rev=self.tip(owner_path,owner)
            metric,sha=self.content(owner_path,control["definition_path"],rev)
            shape(metric,("id","unit","window_days"))
            recipe,_=self.content(path,filename,head)
            shape(recipe,("operation","dataset","scope","metric","unit","window_days","definition_sha256"))
            window=metric["window_days"]
            if (type(window) is not int or not 1<=window<=366 or metric["id"]!=control["metric"] or metric["unit"]!="events"
                    or type(recipe["window_days"]) is not int or recipe["window_days"]!=window
                    or recipe["operation"]!="count-events" or recipe["unit"]!=metric["unit"] or recipe["definition_sha256"]!=sha
                    or any(recipe[key]!=control[key] for key in ("metric","scope","dataset"))):
                raise ValueError("Report is opaque, stale or differs from the registered metric and inputs")
            receipts.append({"report":filename,"owner_scope":control["owner_scope"],"definition_path":control["definition_path"],
                             "owner_revision":rev,"definition_sha256":sha})
        return pr,receipts

    def verify_protection(self,path,reg,number,head,pr):
        trust=shape(reg["protection"],("ruleset","app_id","check_name"))
        rule_id=positive(trust["ruleset"])
        app=positive(trust["app_id"])
        rules=self.api.fetch(path+"/rules/branches/"+quote(reg["branch"],safe=""))
        detail=self.api.fetch(path+"/rulesets/"+str(rule_id))
        if detail["id"]!=rule_id or detail["enforcement"]!="active" or detail.get("bypass_actors")!=[]:
            raise PermissionError("Mandatory no-bypass branch controls could not be verified")
        effective={r["type"]:r.get("parameters",{}) for r in rules if r.get("ruleset_id")==rule_id}
        review=effective.get("pull_request",{})
        checks=effective.get("required_status_checks",{}).get("required_status_checks",[])
        if (not positive(review.get("required_approving_review_count")) or review.get("dismiss_stale_reviews_on_push") is not True
                or review.get("require_code_owner_review") is not True
                or not any(c.get("context")==trust["check_name"] and c.get("integration_id")==app for c in checks)):
            raise PermissionError("Required fresh owner reviews or application-bound policy check missing")
        runs=self.api.fetch(path+"/commits/"+head+"/check-runs?"+urlencode({"check_name":trust["check_name"],"filter":"latest","per_page":100}))
        if len(runs["check_runs"])!=runs["total_count"]:
            raise ValueError("Incomplete GitHub check run inventory")
        trusted=[r for r in runs["check_runs"] if r["app"]["id"]==app and r["name"]==trust["check_name"]]
        if (len(trusted)!=1 or trusted[0]["head_sha"]!=head or trusted[0]["status"]!="completed"
                or trusted[0]["conclusion"]!="success"):
            raise ValueError("No unique positive, candidate-bound trusted GitHub policy result")
        owner,name=reg["slug"].split("/")
        graph=self.api.fetch("/graphql",{"owner":owner,"name":name,"number":number})
        if graph.get("errors"):
            raise PermissionError("GitHub could not establish effective review and merge state")
        decision=graph["data"]["repository"]["pullRequest"]
        if (decision["headRefOid"]!=head or decision["baseRefOid"]!=pr["base"]["sha"]
                or decision["reviewDecision"]!="APPROVED" or decision["mergeStateStatus"]!="CLEAN"):
            raise ValueError("GitHub has not confirmed a clean candidate with required approvals")
        return {"ruleset":rule_id,"check_run":positive(trusted[0]["id"]),"github_review_decision":"APPROVED",
                "require_current_base":effective.get("required_status_checks",{}).get("strict_required_status_checks_policy") is True}

    def sync_inventory(self, scope, repository, organization, branch, *, collect=False):
        reg, path, _ = self.repo(scope)
        if (reg["id"], reg["owner_id"], reg["branch"]) != (repository, organization, branch):
            raise PermissionError("GitHub repository differs from the connected scope")
        head = self.tip(path, reg)
        from oryx.workspace import replicas
        registered = reg.get("records", {})
        if len(registered) > replicas.MAX_RECORDS:
            raise ValueError("Shared replica exceeds the bounded registered inventory")
        rows, documents = [], {}
        size = 0
        for rid in sorted(registered):
            record = self.registered_record(reg, path, rid, head)
            rows.append({"id":record["id"], "revision":record["source_revision"]})
            if collect:
                row = {"path":registered[rid], "record":record}
                size += len(canonical(row))
                if size > LIMIT:
                    raise ValueError("Shared replica exceeds the bounded registered inventory")
                documents[rid] = row
        confirmed, path, _ = self.repo(scope)
        if ((confirmed["id"], confirmed["owner_id"], confirmed["branch"]) != (repository, organization, branch)
                or self.tip(path, confirmed) != head):
            raise ValueError("The GitHub scope changed during synchronization")
        result = {"scope":scope, "repository_id":repository, "official_revision":head, "records":rows}
        return (result, documents) if collect else result

    def perform(self,op,body):
        if op == "github-sync":
            shape(body, ("scope", "repository", "organization", "expected_actor", "branch"))
            if self.account != positive(body["expected_actor"]):
                raise PermissionError("The current GitHub user differs from the connected scope")
            return self.sync_inventory(body["scope"], positive(body["repository"]), positive(body["organization"]),
                                       identifier(body["branch"]))
        candidate=op in {"github-policy","github-verify"}
        if op=="github-record":
            shape(body,("scope","id"),("revision",))
            reg,path,_=self.repo(body["scope"])
            tip=self.tip(path,reg)
            revision=oid(body.get("revision",tip))
            self.descendant(path,revision,tip)
            return {"scope":body["scope"],"repository_id":reg["id"],"commit":revision,
                    "record":self.registered_record(reg,path,body["id"],revision)}
        shape(body, ("scope","pull","head") if candidate else ("scope",))
        reg,path,current=self.repo(body["scope"])
        result={"scope":body["scope"],"destination":reg["slug"],"actor":self.login}
        if op=="github-status":
            return {**result,"repository_id":reg["id"],"organization_id":reg["owner_id"],"actor_id":self.account,
                    "official_branch":reg["branch"],"official_revision":self.tip(path,reg),
                    "visibility":current["visibility"],"observed_permissions":current["permissions"],
                    "repository_settings":{key:current[key] for key in ("has_pull_requests","pull_request_creation_policy","allow_forking","role_name") if key in current},
                    "pull_request_creation":"requires provider decision","merge":"requires provider decision"}
        if op=="github-reviews":
            return {**result,"visibility":current["visibility"],"requested":self.inbox(path,reg)}
        if not candidate:
            raise ValueError("Unknown GitHub governance operation")
        number,head=positive(body["pull"]),oid(body["head"])
        pr,dependencies=self.policy(path,reg,number,head)
        observed=self.verify_protection(path,reg,number,head,pr) if op=="github-verify" else {}
        for dep in dependencies:
            if "record" in dep or "new_record" in dep:
                continue
            owner,owner_path,_=self.repo(dep["owner_scope"])
            if self.tip(owner_path,owner)!=dep["owner_revision"]:
                raise ValueError("Governing dependency changed during verification")
        if self.pull(path,reg,number,head)["base"]["sha"]!=pr["base"]["sha"]:
            raise ValueError("Candidate base changed during verification")
        return {**result,"head":head,"base":pr["base"]["sha"],"dependencies":dependencies,**observed}


def human_confirmation(intent):
    from oryx.review.cli import confirm_effect

    return confirm_effect("Merge the independently approved GitHub candidate.", intent, "MERGE")


def transfer_binding(value):
    shape(value,("scope","pull","head","base","id","repository_id","owner_id","source_revision","workspace_id"))
    identifier(value["scope"])
    positive(value["pull"])
    for key in ("repository_id","owner_id"):
        positive(value[key])
    for key in ("base","head"):
        oid(value[key])
    record_id(value["id"])
    from uuid import UUID
    if str(UUID(value["workspace_id"]))!=value["workspace_id"] or not SHA.fullmatch(value["source_revision"]):
        raise ValueError("Invalid GitHub transfer binding")
    return digest(canonical(value))


def binding_path(private,rid,create=False):
    return directory(private,".oryx/state/github-transfers",create)/(digest(record_id(rid).encode())+".json")


def verify_marker(private,binding):
    from oryx.sharing import transfer
    from oryx.workspace.location import workspace_id
    marker=transfer.status(private,binding["id"])
    if (not marker or marker["proposal"]!=transfer_binding(binding) or marker["workspace_id"]!=workspace_id(private)
            or marker["workspace_id"]!=binding["workspace_id"] or marker["source_revision"]!=binding["source_revision"]
            or marker["organization"]!="github-"+str(binding["owner_id"]) or marker["scope"]!=binding["scope"]):
        raise ValueError("Workspace transfer marker and GitHub destination binding differ")
    return marker


def fence_transfer(private,body,reg,source_revision):
    from oryx.sharing import transfer
    from oryx.workspace.location import workspace_id
    from storage import writer_lock
    rid=body["id"]
    binding={**body,"repository_id":reg["id"],"owner_id":reg["owner_id"],"source_revision":source_revision,"workspace_id":workspace_id(private)}
    commitment=transfer_binding(binding)
    with writer_lock(private):
        marker=transfer.status(private,rid)
        path=binding_path(private,rid,True)
        prior=read(path) if path.exists() else None
        if marker and marker["status"]!="closed":
            if prior!=binding:
                raise ValueError("Reconcile the existing owner transfer first")
            return verify_marker(private,binding)
        row,data,_=transfer.source(private,rid)
        if row["id"]!=rid or row["revision"]!=source_revision or digest(data)!=source_revision:
            raise ValueError("Private source changed; inspect both revisions before transfer")
        current={"id":rid,"workspace_id":binding["workspace_id"],"source_path":row["path"],"source_revision":source_revision,
                 "organization":"github-"+str(reg["owner_id"]),"scope":body["scope"],"proposal":commitment,"status":"pending","official_commit":None}
        # Write the recovery address before the fence. No provider call can occur between these writes.
        save(path,binding,expected=prior)
        save(transfer.location(private,rid,True),current,expected=marker)
        return current


def merge_state(client,reg,path,body):
    pr=client.api.fetch(path+"/pulls/"+str(positive(body["pull"])))
    if (pr["base"]["repo"]["id"]!=reg["id"] or pr["head"]["repo"]["id"]!=reg["id"]
            or pr["base"]["ref"]!=reg["branch"] or pr["head"]["sha"]!=oid(body["head"])):
        raise ValueError("GitHub PR no longer matches the bound repository, branch and candidate")
    result={"repository_id":reg["id"],"pull":body["pull"],"head":body["head"]}
    if pr["state"]=="open" and pr.get("merged") is False:
        return {**result,"status":"open"}
    if pr["state"]!="closed" or type(pr.get("merged")) is not bool:
        raise ValueError("GitHub PR outcome is uncertain")
    if not pr["merged"] and pr.get("merged_at") is None:
        return {**result,"status":"closed"}
    if not pr["merged"] or not pr.get("merged_at"):
        raise ValueError("GitHub merge evidence is inconsistent")
    merged=oid(pr["merge_commit_sha"])
    commit=client.api.fetch(path+"/git/commits/"+merged)
    if commit["sha"]!=merged or [p["sha"] for p in commit["parents"]]!=[oid(body["base"]),body["head"]]:
        raise ValueError("Merge commit does not have the approved base and candidate parents")
    client.descendant(path,merged,client.tip(path,reg))
    return {**result,"status":"merged","official_commit":merged}


def reconcile_transfer(client,private,scope,rid):
    from oryx.sharing import transfer
    from storage import writer_lock
    local=transfer.status(private,rid)
    if local and local["status"]=="pending" and proposal_stage(private,local["proposal"]).is_file():
        pending=read(proposal_stage(private,local["proposal"]))
        if pending.get("intent",{}).get("operation")=="github-propose":
            observed=resume_transfer_proposal(client,private,pending)
            if observed["status"]=="pending-disclosure":
                return observed
    binding=read(binding_path(private,rid))
    marker=verify_marker(private,binding)
    reg,path,_=client.repo(scope)
    if (scope!=binding["scope"] or reg["id"]!=binding["repository_id"] or reg["owner_id"]!=binding["owner_id"]
            or rid!=binding["id"] or "transfer" not in client.human_effects.get(scope,[])):
        raise PermissionError("Cannot verify the enrolled transfer destination or recovery identity")
    result=merge_state(client,reg,path,binding)
    if result["status"]=="open":
        return {**result,"transfer_status":marker["status"]}
    official=result.get("official_commit")
    if official:
        record=client.registered_record(reg,path,rid,official)
        if record["source_revision"]!=marker["source_revision"]:
            raise ValueError("Verified merge differs from the fenced source revision")
        tip=client.tip(path,reg)
        if tip!=official:
            client.registered_record(reg,path,rid,tip)
    updated={**marker,"status":"transferred" if official else "closed","official_commit":official}
    if marker["status"]=="transferred" and updated!=marker:
        raise ValueError("GitHub evidence conflicts with a completed ownership transfer")
    with writer_lock(private):
        save(transfer.location(private,rid),updated,expected=marker)
    return {**result,"transfer_status":updated["status"],"record_id":rid,"scope":scope}


def effect(client,op,body,private=None,confirm=human_confirmation,reauthenticate=None):
    is_transfer=op=="github-transfer"
    if op=="github-reconcile":
        if "id" in body:
            shape(body,("scope","id"))
            return reconcile_transfer(client,private,body["scope"],body["id"])
        shape(body,("scope","pull","head","base"))
        reg,path,_=client.repo(body["scope"])
        return merge_state(client,reg,path,body)
    if op not in {"github-merge","github-transfer"}:
        raise ValueError("Unknown GitHub effect")
    shape(body,("scope","pull","head","base","id") if is_transfer else ("scope","pull","head","base"))
    params={key:body[key] for key in ("scope","pull","head")}
    scope=body["scope"]
    rights=set(client.human_effects.get(scope,[]))
    if "merge" not in rights or (is_transfer and "transfer" not in rights):
        raise PermissionError("This OS principal is not separately enrolled for the requested human GitHub effect")
    reg,path,current=client.repo(scope)
    if current["permissions"].get("push") is not True or current.get("allow_merge_commit") is not True or current["visibility"]!="private":
        raise PermissionError("Private repository, acting account write permission and merge-commit support required")
    state=merge_state(client,reg,path,body)
    if state["status"]!="open":
        return reconcile_transfer(client,private,scope,body["id"]) if is_transfer else state
    proof=client.perform("github-verify",params)
    if proof["base"]!=oid(body["base"]) or not proof["require_current_base"]:
        raise ValueError("A strictly current base and its exact approved revision are required")
    docs=[dep for dep in proof["dependencies"] if "record" in dep]
    if bool(docs)!=is_transfer or (is_transfer and (len(docs)!=1 or docs[0]["record"]!=body["id"])):
        raise ValueError("The approved effect differs from the registered candidate type")
    if is_transfer:
        from oryx.sharing import transfer
        marker=transfer.status(private,body["id"])
        if not marker or marker["status"]=="closed":
            _,source,_=transfer.source(private,body["id"])
            if digest(source)!=docs[0]["source_revision"]:
                raise ValueError("The private record and proposed GitHub content differ")
    intent={**proof,"operation":op,"branch":reg["branch"],"repository_id":reg["id"],"visibility":current["visibility"]}
    intent["reviewed_files"]=[]
    for dep in proof["dependencies"]:
        filename=dep.get("report") or dep["path"]
        doc,_=client.content(path,filename,body["head"])
        intent["reviewed_files"].append({"path":filename,"document":doc})
    if not confirm(intent):
        return {"status":"no-decision","head":body["head"]}
    if is_transfer:
        fence_transfer(private,body,reg,docs[0]["source_revision"])
    actor=reauthenticate() if reauthenticate else client
    current_rights=set(actor.human_effects.get(scope,[]))
    if (actor.account!=client.account or "merge" not in current_rights
            or (is_transfer and "transfer" not in current_rights)):
        raise PermissionError("Customer merge principal or enrollment changed after review")
    client=actor
    refreshed=client.perform("github-verify",params)
    new_reg,_,latest=client.repo(scope)
    if new_reg!=reg:
        raise ValueError("Customer repository registration changed after review")
    if refreshed!=proof or latest["permissions"].get("push") is not True or latest["visibility"]!="private":
        raise ValueError("GitHub authority or exact candidate changed after local review")
    # The server independently enforces permission, fresh required checks and the supplied head SHA.
    response=client.api.merge(reg["slug"],body["pull"],body["head"])
    if response.get("merged") is not True or not OID.fullmatch(str(response.get("sha"))):
        raise ValueError("GitHub has not confirmed the merge; reconcile before retrying")
    result=reconcile_transfer(client,private,scope,body["id"]) if is_transfer else merge_state(client,reg,path,body)
    if result.get("official_commit")!=response["sha"]:
        raise ValueError("Cannot verify the provider's merge response; reconcile before retrying")
    return result


def connect():
    return Connection(load_enrollment(), GitHubAPI(), os.geteuid())


def verify_binding(client, binding):
    reg, path, _ = client.repo(binding["scope"])
    if (client.account != binding["actor"] or reg["id"] != binding["authority"]["repository"]
            or reg["owner_id"] != binding["authority"]["organization"] or reg["branch"] != binding["branch"]):
        raise PermissionError("GitHub actor, branch or repository differs from the connected authority")
    return reg, path


def fetch_replica(binding):
    client = connect()
    first, _ = verify_binding(client, binding)
    current, documents = client.sync_inventory(binding["scope"], first["id"], first["owner_id"],
                                              first["branch"], collect=True)
    latest = connect()
    confirmed, path = verify_binding(latest, binding)
    if confirmed != first or latest.tip(path, confirmed) != current["official_revision"]:
        raise ValueError("GitHub registration or revision changed while collecting the replica")
    return current, documents


def run(op,body,private=None):
    if private is not None and op == "github-record":
        from oryx.workspace import connections
        binding = connections.recorded(private, "github", body.get("scope"))
        if binding is not None:
            return connections.github_record(private, body, binding)
    client=connect()
    if op=="github-propose":
        return propose(client,private,body,reauthenticate=connect)
    if op in {"github-merge","github-transfer","github-reconcile"}:
        return effect(client,op,body,private,reauthenticate=connect)
    return client.perform(op,body)


def pages(api,path):
    entries=[]
    for number in range(1,11):
        separator="&" if "?" in path else "?"
        page=api.fetch(path+separator+urlencode({"per_page":100,"page":number}))
        if not isinstance(page,list):
            raise PermissionError("GitHub did not provide a complete access inventory")
        entries.extend(page)
        if len(page)<100:
            return entries
    raise PermissionError("GitHub access inventory exceeds the supported bound")


def disclosure_audience(client,reg,path,current):
    anchor=shape(reg["disclosure"],("readers","apps","deploy_keys","other_readers","valid_until"))
    expires=datetime.fromisoformat(anchor["valid_until"].replace("Z","+00:00"))
    other=anchor["other_readers"]
    if (expires.utcoffset() is None or datetime.now(timezone.utc)>=expires or
            not isinstance(other,list) or any(not isinstance(name,str) or not name.strip() for name in other)):
        raise PermissionError("Customer audience enrollment is invalid or expired")
    for group in ("readers","apps","deploy_keys"):
        if not isinstance(anchor[group],list) or sorted(set(map(positive,anchor[group])))!=sorted(anchor[group]):
            raise ValueError("Invalid customer-enrolled audience identifiers")
    if (current["visibility"]!="private" or current.get("allow_forking") is not False or current.get("forks_count")!=0
            or current.get("archived") is not False or current.get("disabled") is not False):
        raise PermissionError("Initial disclosure requires an active private destination without forks or forking")
    owner=reg["slug"].split("/")[0]
    if client.api.fetch(path+"/actions/permissions").get("enabled") is not False:
        raise PermissionError("First disclosure needs a destination without automatic Actions access")
    for endpoint in (path+"/hooks","/orgs/"+owner+"/hooks"):
        if any(hook.get("active") is not False for hook in pages(client.api,endpoint)):
            raise PermissionError("Active GitHub webhooks make this disclosure audience unverified")
    people=[{"id":positive(row["id"]),"login":identifier(row["login"])} for row in pages(client.api,path+"/collaborators?affiliation=all")]
    keys=[{"id":positive(row["id"]),"title":row["title"]} for row in pages(client.api,path+"/keys")]
    # GitHub exposes organization installations with total_count. Include every installation
    # including metadata readers, even when its selected repositories cannot be enumerated.
    installations=client.api.fetch("/orgs/"+owner+"/installations?per_page=100")
    if len(installations["installations"])!=installations["total_count"]:
        raise PermissionError("Incomplete organization GitHub App installation inventory")
    apps=[]
    for app in installations["installations"]:
        if app["account"]["id"]!=reg["owner_id"]:
            raise PermissionError("Installation belongs to another GitHub organization")
        apps.append({"id":positive(app["id"]),"app":identifier(app["app_slug"])})
    for actual,key in ((people,"readers"),(apps,"apps"),(keys,"deploy_keys")):
        actual.sort(key=lambda item:item["id"])
        if [a["id"] for a in actual]!=sorted(anchor[key]):
            raise PermissionError("Live GitHub audience differs from customer disclosure enrollment")
    if client.account not in anchor["readers"]:
        raise PermissionError("Current proposer is outside the permitted destination audience")
    return {"readers":people,"app_installations":apps,"deploy_keys":keys,"other_enrolled_readers":sorted(other)}


def proposal_stage(private,key,create=False):
    if not isinstance(key,str) or not SHA.fullmatch(key):
        raise ValueError("Invalid GitHub proposal commitment")
    return directory(private,".oryx/staging/sharing",create)/(key+".json")


def checked_draft(draft):
    shape(draft,("organization","actor","intent","commitment"))
    intent=draft["intent"]
    shape(intent,("operation","scope","repository_id","owner_id","repository","branch","base","workspace_id","id",
                  "source","filename","record","actor","author","last_updated","audience"))
    if (intent["operation"]!="github-propose" or intent["source"] not in {"private","draft"}
            or digest(canonical(intent))!=draft["commitment"] or draft["actor"]!=str(intent["actor"])
            or draft["organization"]!="github-"+str(intent["owner_id"])):
        raise ValueError("Invalid staged GitHub disclosure")
    return intent


def proposal_access(client,scope,rid):
    if "propose" not in client.human_effects.get(scope,[]):
        raise PermissionError("A separately enrolled human proposal account is required")
    reg,path,current=client.repo(scope)
    if current["permissions"].get("push") is not True or current.get("has_pull_requests") is False:
        raise PermissionError("GitHub destination denies branch contribution or pull requests")
    filename=relative_path(reg.get("records",{})[record_id(rid)])
    if not filename.startswith("context/records/"):
        raise ValueError("Disclose only to a registered record path")
    return reg,path,filename,disclosure_audience(client,reg,path,current)


def draft_input(client,private,body):
    from oryx.sharing import transfer
    from oryx.workspace.location import workspace_id
    source=body.get("source")
    shape(body,("scope","id","base","source","content","last_updated") if source=="draft" else ("scope","id","base","source"))
    reg,path,filename,audience=proposal_access(client,body["scope"],body["id"])
    if client.tip(path,reg)!=oid(body["base"]):
        raise ValueError("Official GitHub base changed before staging")
    if source=="draft" and body["id"] in reg.get("destination_drafts",[]):
        from oryx.workspace.identity import load
        if body["id"] in load(private)["records"]:
            raise ValueError("This record is already privately owned; register and review an ownership transfer")
        data=body["content"]
        when=datetime.fromisoformat(body["last_updated"].replace("Z","+00:00"))
    elif source=="private" and body["id"] not in reg.get("destination_drafts",[]):
        if "transfer" not in client.human_effects.get(body["scope"],[]):
            raise PermissionError("Private promotion requires the enrolled transfer permission")
        row,raw,stamp=transfer.source(private,body["id"])
        if row["id"]!=body["id"]:
            raise ValueError("Supply the stable private source ID")
        data=raw.decode("utf-8")
        if stamp is None:
            raise ValueError("The earlier portable archive did not record the source update time")
        when=datetime.fromtimestamp(stamp,timezone.utc)
    else:
        raise ValueError("Choose the enrolled destination-first draft or private transfer source")
    if not isinstance(data,str) or not data.strip() or len(data.encode())>250000 or when.utcoffset() is None:
        raise ValueError("Review bounded UTF-8 record prose and its source timestamp")
    record={"id":body["id"],"kind":"record","source_revision":digest(data.encode()),"content":data}
    intent={"operation":"github-propose","scope":body["scope"],"repository_id":reg["id"],"owner_id":reg["owner_id"],
            "repository":reg["slug"],"branch":reg["branch"],"base":body["base"],"workspace_id":workspace_id(private),
            "id":body["id"],"source":source,"filename":filename,"record":record,"actor":client.account,"author":client.login,
            "last_updated":when.astimezone(timezone.utc).isoformat(timespec="seconds"),"audience":audience}
    key=digest(canonical(intent))
    draft={"organization":"github-"+str(reg["owner_id"]),"actor":str(client.account),"intent":intent,"commitment":key}
    save(proposal_stage(private,key,True),draft)
    return draft


def branch_name(draft):
    return "oryx-proposal-"+draft["commitment"]


def observe_proposal(client,reg,path,draft):
    intent=checked_draft(draft)
    branch=branch_name(draft)
    ref=client.api.lookup(path+"/git/ref/heads/"+branch)
    params=urlencode({"state":"all","head":reg["slug"].split("/")[0]+":"+branch,"base":intent["branch"],"per_page":2})
    pulls=client.api.fetch(path+"/pulls?"+params)
    if not isinstance(pulls,list) or len(pulls)>1:
        raise ValueError("Uncertain or duplicate GitHub proposal; inspect the destination")
    pr=pulls[0] if pulls else None
    if pr and (pr["user"]["id"]!=intent["actor"] or pr["title"]!="Oryx record "+intent["id"]
               or pr["body"]!="Reviewed Oryx proposal "+draft["commitment"] or pr["head"]["ref"]!=branch or pr["base"]["ref"]!=intent["branch"]
               or pr["head"]["repo"]["id"]!=reg["id"] or pr["base"]["repo"]["id"]!=reg["id"]):
        raise ValueError("GitHub returned a proposal for another repository or branch")
    if ref and (ref["ref"]!="refs/heads/"+branch or ref["object"]["type"]!="commit"):
        raise ValueError("GitHub proposal ref does not identify an ordinary commit")
    head=oid(ref["object"]["sha"]) if ref else (oid(pr["head"]["sha"]) if pr else None)
    if not head:
        return {"status":"absent"}
    if pr and pr["head"]["sha"]!=head:
        raise ValueError("Existing PR or proposal branch changed")
    verify_candidate(client,reg,path,draft,head)
    result={"scope":intent["scope"],"repository_id":reg["id"],"base":intent["base"],"head":head,
            "branch":branch,"commitment":draft["commitment"],"status":"branch"}
    if pr:
        if pr["state"] not in {"open","closed"}:
            raise ValueError("Cannot establish GitHub proposal state")
        result.update(pull=positive(pr["number"]),status=pr["state"],draft=pr["draft"])
    return result


def verify_candidate(client,reg,path,draft,head):
    intent=draft["intent"]
    commit=client.api.fetch(path+"/git/commits/"+oid(head))
    if (commit["sha"]!=head or [p["sha"] for p in commit["parents"]]!=[intent["base"]]
            or commit["message"]!="Reviewed Oryx proposal "+draft["commitment"]):
        raise ValueError("Existing candidate differs from the reviewed destination history")
    compare=client.api.fetch(path+"/compare/"+intent["base"]+"..."+head+"?per_page=1")
    files=compare.get("files",[])
    if (compare["status"]!="ahead" or compare["ahead_by"]!=1 or compare["behind_by"]!=0 or len(files)!=1
            or files[0]["filename"]!=intent["filename"] or files[0]["status"]!="added"):
        raise ValueError("Candidate carries changes outside the exact reviewed file addition")
    data=canonical(intent["record"])
    expected_blob=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
    if files[0].get("sha")!=expected_blob:
        raise ValueError("Candidate blob differs from the exact reviewed bytes")
    expected_email=str(intent["actor"])+"+"+intent["author"]+"@users.noreply.github.com"
    date=datetime.fromisoformat(intent["last_updated"])
    for key in ("author","committer"):
        who=commit[key]
        if (who["name"]!=intent["author"] or who["email"]!=expected_email
                or datetime.fromisoformat(who["date"].replace("Z","+00:00"))!=date):
            raise ValueError("Candidate Git metadata differs from the review")
    if client.registered_record(reg,path,intent["id"],head)!=intent["record"]:
        raise ValueError("Candidate bytes differ from the reviewed record")


def disclosure_confirmation(draft):
    from oryx.review.cli import confirm_effect

    intent = draft["intent"]
    actor_email = f"{intent['actor']}+{intent['author']}@users.noreply.github.com"
    metadata = {
        "parents": [intent["base"]],
        "message": "Reviewed Oryx proposal " + draft["commitment"],
        "author_and_committer": {"name": intent["author"], "email": actor_email, "date": intent["last_updated"]},
        "pull_title": "Oryx record " + intent["id"],
        "pull_body": "Reviewed Oryx proposal " + draft["commitment"],
    }
    displayed = {"branch": branch_name(draft), "draft_pull_request": True, "review": draft, "metadata": metadata}
    return confirm_effect("This exposes the reviewed material to the repository audience before merge.",
                          displayed, "DISCLOSE")


def proposal_fence(private,draft):
    from oryx.sharing import transfer
    from storage import writer_lock
    intent=draft["intent"]
    with writer_lock(private):
        marker=transfer.status(private,intent["id"])
        if marker and marker["status"]!="closed":
            if marker["proposal"]!=draft["commitment"] or marker["status"]!="pending":
                raise ValueError("Resolve the other ownership transfer first")
            return
        row,data,_=transfer.source(private,intent["id"])
        if (digest(data)!=intent["record"]["source_revision"] or row["workspace_id"]!=intent["workspace_id"]
                or row["id"]!=intent["id"]):
            raise ValueError("Private source changed before first disclosure")
        value={"id":intent["id"],"workspace_id":row["workspace_id"],"source_path":row["path"],"source_revision":row["revision"],
               "organization":draft["organization"],"scope":intent["scope"],"proposal":draft["commitment"],
               "status":"pending","official_commit":None}
        save(transfer.location(private,row["id"],True),value,expected=marker)


def bind_observed(private,draft,result):
    from oryx.sharing import transfer
    from storage import writer_lock
    intent=draft["intent"]
    binding={k:intent[k] for k in ("scope","id","owner_id","repository_id","workspace_id","base")}
    binding.update(pull=result["pull"],head=result["head"],source_revision=intent["record"]["source_revision"])
    commitment=transfer_binding(binding)
    with writer_lock(private):
        marker=transfer.status(private,intent["id"])
        if marker and marker["proposal"]==commitment:
            return verify_marker(private,binding)
        if (not marker or marker["proposal"]!=draft["commitment"] or marker["status"]!="pending"
                or marker["workspace_id"]!=binding["workspace_id"] or marker["source_revision"]!=binding["source_revision"]):
            raise ValueError("Cannot verify the private proposal's ownership fence")
        path=binding_path(private,intent["id"],True)
        prior=read(path) if path.exists() else None
        save(path,binding,expected=prior)
        value={**marker,"proposal":commitment}
        save(transfer.location(private,intent["id"]),value,expected=marker)
        return value


def resume_transfer_proposal(client,private,draft):
    intent=checked_draft(draft)
    if "transfer" not in client.human_effects.get(intent["scope"],[]):
        raise PermissionError("Customer transfer recovery permission unavailable")
    reg,path,_=client.repo(intent["scope"])
    if (reg["id"]!=intent["repository_id"] or reg["owner_id"]!=intent["owner_id"]
            or reg["slug"]!=intent["repository"] or reg["branch"]!=intent["branch"]):
        raise ValueError("Registered destination changed")
    result=observe_proposal(client,reg,path,draft)
    if "pull" not in result:
        return {"status":"pending-disclosure","commitment":draft["commitment"]}
    bind_observed(private,draft,result)
    return result


def propose(client,private,body,confirm=disclosure_confirmation,reauthenticate=None):
    from oryx.workspace.location import workspace_id
    if set(body)=={"commitment"}:
        draft=read(proposal_stage(private,body["commitment"]))
        if draft.get("commitment")!=body["commitment"]:
            raise ValueError("Staged GitHub proposal differs from the requested review")
    else:
        draft=draft_input(client,private,body)
    intent=checked_draft(draft)
    if intent["workspace_id"]!=workspace_id(private):
        raise ValueError("GitHub proposal belongs to another Workspace")
    scope,rid=intent["scope"],intent["id"]
    def authorized():
        actor=reauthenticate() if reauthenticate else client
        reg,path,filename,audience=proposal_access(actor,scope,rid)
        if (actor.account!=intent["actor"] or actor.login!=intent["author"] or reg["id"]!=intent["repository_id"] or reg["owner_id"]!=intent["owner_id"]
                or reg["slug"]!=intent["repository"] or reg["branch"]!=intent["branch"] or filename!=intent["filename"]
                or ((intent["id"] in reg.get("destination_drafts",[]))!=(intent["source"]=="draft"))
                or audience!=intent["audience"] or (intent["source"]=="private" and "transfer" not in actor.human_effects.get(scope,[]))):
            raise PermissionError("Reviewed actor, destination, reader list or customer enrollment changed")
        return actor,reg,path
    actor,reg,path=authorized()
    observed=observe_proposal(actor,reg,path,draft)
    if "pull" in observed:
        if intent["source"]=="private":
            bind_observed(private,draft,observed)
        return observed
    def before_write():
        actor,reg,path=authorized()
        if actor.tip(path,reg)!=intent["base"]:
            raise ValueError("Official destination base changed; inspect and review the current revision")
        return actor,reg,path
    before_write()
    if not confirm(draft):
        return {"status":"no-new-write",
                "commitment":draft["commitment"]}
    before_write()
    if intent["source"]=="private":
        proposal_fence(private,draft)
    else:
        from oryx.workspace.identity import load
        if intent["id"] in load(private)["records"]:
            raise ValueError("The staged draft now conflicts with an authoritative private record")
    slug=reg["slug"]
    branch=branch_name(draft)
    if observed["status"]=="absent":
        actor,reg,path=before_write()
        base=actor.api.fetch(path+"/git/commits/"+intent["base"])
        if base["sha"]!=intent["base"] or actor.api.lookup(path+"/contents/"+intent["filename"]+"?ref="+intent["base"]) is not None:
            raise ValueError("Expected a new record on the reviewed official base")
        data=canonical(intent["record"])
        tree=actor.api.create(slug,"tree",{"base_tree":oid(base["tree"]["sha"]),"tree":[
            {"path":intent["filename"],"mode":"100644","type":"blob","content":data.decode()}]})
        actor,reg,path=before_write()
        author={"name":intent["author"],"email":str(intent["actor"])+"+"+intent["author"]+"@users.noreply.github.com","date":intent["last_updated"]}
        commit=actor.api.create(slug,"commit",{"message":"Reviewed Oryx proposal "+draft["commitment"],"tree":oid(tree["sha"]),
            "parents":[intent["base"]],"author":author,"committer":author})
        head=oid(commit["sha"])
        verify_candidate(actor,reg,path,draft,head)
        actor,reg,path=before_write()
        observed=observe_proposal(actor,reg,path,draft)
        if observed["status"]=="absent":
            actor.api.create(slug,"ref",{"ref":"refs/heads/"+branch,"sha":head})
    actor,reg,path=before_write()
    observed=observe_proposal(actor,reg,path,draft)
    if observed["status"]=="branch":
        actor.api.create(slug,"draft",{"title":"Oryx record "+rid,"head":branch,"base":intent["branch"],
                         "body":"Reviewed Oryx proposal "+draft["commitment"],"draft":True})
        observed=observe_proposal(actor,reg,path,draft)
    if "pull" not in observed:
        raise ValueError("GitHub proposal is uncertain; reconcile the saved commitment")
    if intent["source"]=="private":
        bind_observed(private,draft,observed)
    return observed
