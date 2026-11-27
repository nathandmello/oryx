"""Read-only observations from enrolled GitHub.com repositories under the acting credential."""
import base64
import binascii
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import build_opener, HTTPRedirectHandler, Request

from .common import LIMIT, canonical, decode, digest, identifier, shape

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
    """Fixed HTTPS origin and immutable GraphQL query. No mutation transport."""
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
        req=Request("https://api.github.com"+path,data=data,headers={"Authorization":"Bearer "+self.token,
                    "Accept":"application/vnd.github+json","User-Agent":"oryx-customer-governance",
                    "Content-Type":"application/json","X-GitHub-Api-Version":"2022-11-28"})
        try:
            with self.http.open(req,timeout=15) as response:
                return decode(response.read(LIMIT+1))
        except (HTTPError,URLError,TimeoutError) as exc:
            raise PermissionError("GitHub could not confirm this operation under the acting credential") from exc


class Connection:
    def __init__(self,settings,api,uid):
        shape(settings, ("principals","repositories"))
        account=settings["principals"].get(str(uid))
        if not account:
            raise PermissionError("OS principal has no enrolled GitHub user")
        self.api=api
        user=api.fetch("/user")
        if positive(user["id"])!=positive(account):
            raise PermissionError("Active GitHub identity differs from customer enrollment")
        self.login=identifier(user["login"])
        self.config=settings["repositories"]

    def repo(self,scope):
        value=self.config[identifier(scope)]
        shape(value,("slug","id","owner_id","branch","reports"),("protection",))
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
        receipts=[]
        for entry in changed:
            filename=relative_path(entry["filename"])
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
        return {"ruleset":rule_id,"check_run":positive(trusted[0]["id"]),"github_review_decision":"APPROVED"}

    def perform(self,op,body):
        candidate=op in {"github-policy","github-verify"}
        shape(body, ("scope","pull","head") if candidate else ("scope",))
        reg,path,current=self.repo(body["scope"])
        result={"scope":body["scope"],"destination":reg["slug"],"actor":self.login}
        if op=="github-status":
            return {**result,"repository_id":reg["id"],"official_revision":self.tip(path,reg),
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
            owner,owner_path,_=self.repo(dep["owner_scope"])
            if self.tip(owner_path,owner)!=dep["owner_revision"]:
                raise ValueError("Governing dependency changed during verification")
        if self.pull(path,reg,number,head)["base"]["sha"]!=pr["base"]["sha"]:
            raise ValueError("Candidate base changed during verification")
        return {**result,"head":head,"base":pr["base"]["sha"],"dependencies":dependencies,**observed}


def run(op,body):
    settings=load_enrollment()
    return Connection(settings,GitHubAPI(),os.geteuid()).perform(op,body)
