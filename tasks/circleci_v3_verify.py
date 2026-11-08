#!/usr/bin/env python3
"""Read-only CircleCI v3 acceptance: require real, individually verified 20-shard artifacts."""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tasks.circleci_worker import slot
from tasks.circleci_supervisor import token_from_file

API="https://circleci.com/api/v3/"
PROJECT_ID="92a7b55f-2fa6-4db1-88f2-7437c381c958"
PIPELINE_ID="e4883277-27dc-4756-9494-1394cc7c497e"
MAX_RESPONSE=512_000

class EvidenceError(Exception):pass

class DenyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not approved_url(newurl):raise EvidenceError("ARTIFACT_REDIRECT_HOST_DENIED")
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def approved_url(url):
    u=urllib.parse.urlsplit(url)
    host=(u.hostname or "").lower()
    return u.scheme=="https" and u.username is None and u.password is None and (host=="circleci.com" or host.endswith(".circleci.com")) and (u.port is None or u.port==443)

def fetch_json(token,url):
    if not approved_url(url):raise EvidenceError("UNAPPROVED_URL")
    request=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
    with urllib.request.build_opener(DenyRedirect).open(request,timeout=12) as response:
        data=response.read(MAX_RESPONSE+1)
    if len(data)>MAX_RESPONSE:raise EvidenceError("OVERSIZED_RESPONSE")
    return json.loads(data)

def get_items(token,resource,field,value):
    url=API+resource+"?"+urllib.parse.urlencode({"filter["+field+"]":value})
    result=fetch_json(token,url)
    if result.get("page",{}).get("next") is not None:
        raise EvidenceError("PAGINATION_NOT_ALLOWED_IN_CERTIFICATION")
    rows=result.get("data")
    if not isinstance(rows,list):raise EvidenceError("MALFORMED_COLLECTION")
    return rows

def validate_shards(records):
    if not isinstance(records,list) or len(records)!=20:
        raise EvidenceError("REQUIRES_20_REAL_ARTIFACTS")
    verified=set()
    for row in records:
        if not isinstance(row,dict):raise EvidenceError("MALFORMED_SHARD")
        n=row.get("slot")
        if type(n) is not int or n not in range(20) or n in verified:
            raise EvidenceError("DUPLICATE_OR_INVALID_SHARD")
        role,shard,source=slot(n,20)
        for key,value in {"total":20,"role":role,"shard":shard,"source":source,
                          "status":"preflight_pass","ai_inference":False,
                          "writes_to_repository":False}.items():
            if type(row.get(key)) is not type(value) or row.get(key)!=value:
                raise EvidenceError("SHARD_CONTENT_MISMATCH")
        verified.add(n)
    if verified!=set(range(20)):raise EvidenceError("MISSING_SHARDS")
    return sorted(verified)

def verify(run_id,fetch=fetch_json):
    if not re.fullmatch(r"[0-9a-fA-F-]{36}",run_id):raise EvidenceError("INVALID_RUN_ID")
    token=token_from_file()
    run=fetch(token,API+"runs/"+run_id).get("data",{})
    attrs=run.get("attributes",{})
    if run.get("id")!=run_id or attrs.get("phase")!="ended" or attrs.get("current_outcome")!="succeeded":
        raise EvidenceError("RUN_NOT_SUCCESSFULLY_ENDED")
    flows=get_items(token,"workflows","run_id",run_id)
    if len(flows)!=1 or flows[0].get("attributes",{}).get("name")!="manual_supervisor_preflight":
        raise EvidenceError("UNEXPECTED_WORKFLOW")
    workflow=flows[0]
    if workflow.get("attributes",{}).get("status") not in ("success","succeeded"):
        raise EvidenceError("WORKFLOW_NOT_SUCCESSFUL")
    jobs=get_items(token,"jobs","workflow_id",workflow["id"])
    if len(jobs)!=1 or jobs[0].get("attributes",{}).get("name")!="supervisor_worker_preflight":
        raise EvidenceError("UNEXPECTED_JOB")
    job=jobs[0]
    if job.get("attributes",{}).get("status") not in ("success","succeeded"):
        raise EvidenceError("JOB_NOT_SUCCESSFUL")
    artifact_data=fetch(token,API+"jobs/"+job["id"]+"/artifacts")
    artifacts=artifact_data.get("data")
    if not isinstance(artifacts,list) or len(artifacts)!=20:
        raise EvidenceError("NOT_EXACTLY_20_ARTIFACT_METADATA")
    values=[]
    for item in artifacts:
        attr=item.get("attributes",{})
        path=attr.get("path","")
        if not isinstance(path,str) or not path.endswith("worker-result.json"):
            raise EvidenceError("UNEXPECTED_ARTIFACT_PATH")
        uri=attr.get("url","")
        if not approved_url(uri):raise EvidenceError("UNAPPROVED_ARTIFACT_URL")
        values.append(fetch(token,uri))
    verified=validate_shards(values)
    return {"status":"PASS","run_id":run_id,"workflow_id":workflow["id"],
            "job_id":job["id"],"real_artifacts_verified":len(verified),"slots":verified,
            "model_inference":False,"production_deployment":False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id",help="actual CircleCI v3 run UUID")
    args=parser.parse_args()
    try:report=verify(args.run_id)
    except (EvidenceError,OSError,ValueError,KeyError,urllib.error.HTTPError,urllib.error.URLError) as exc:
        report={"status":"FAIL","reason":type(exc).__name__,"real_artifacts_verified":0}
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"]=="PASS" else 2

if __name__=="__main__":raise SystemExit(main())
