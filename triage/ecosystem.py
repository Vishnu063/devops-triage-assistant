"""Versioned optional ecosystem contracts, bounded transport and read-only analysis.

No model, server, broker or command execution is needed to use these functions.
Ops Pilot owns remediation authorization; this module can never grant it.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler
import uuid
from .integrations import NoRedirect, redact
from .evidence import log_signals
from .health import check_health

VERSION='1.0'
LIMIT=65536
KINDS={
 'DeploymentEvent': {'release_id','status'},
 'MonitoringAlert': {'fingerprint','status','alertname'},
 'Incident': {'status','event_ids'},
 'Evidence': {'observations','references'},
 'Diagnosis': {'hypotheses','evidence_refs','uncertainty'},
 'RemediationProposal': {'incident_id','plan_id','action','risk','rollback','verification'},
 'ApprovalDecision': {'incident_id','plan_id','decision','actor'},
 'ExecutionResult': {'incident_id','plan_id','status'},
 'VerificationResult': {'status','checks'},
 'IncidentReport': {'incident_id','timeline','unresolved'},
}
FIELDS={'schema_version','type','id','source','service','correlation_id','timestamp','data'}
IDENT=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}\Z')


def utc():return datetime.now(timezone.utc).isoformat(timespec='seconds')


def bounded(value, depth=0):
    if depth>12:raise ValueError('Contract nesting exceeds limit')
    if isinstance(value,dict):
        if len(value)>100:raise ValueError('Too many object fields')
        for key,item in value.items():
            if not isinstance(key,str) or len(key)>100:raise ValueError('Invalid object key')
            if re.search(r'(?i)^(password|secret|token|authorization|api_key|credentials)$',key):raise ValueError('Credential fields are forbidden')
            bounded(item,depth+1)
    elif isinstance(value,list):
        if len(value)>200:raise ValueError('Contract array exceeds limit')
        for item in value:bounded(item,depth+1)
    elif isinstance(value,str):
        if len(value)>8000 or any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError('Invalid contract text')
    elif isinstance(value,float) and not math.isfinite(value):raise ValueError('Nonfinite numbers are forbidden')
    elif value is not None and type(value) not in (int,float,bool):raise ValueError('Use JSON values only')


def validate(event):
    if not isinstance(event,dict) or set(event)!=FIELDS or event.get('schema_version')!=VERSION or event.get('type') not in KINDS:
        raise ValueError('Unsupported versioned ecosystem envelope')
    for key in ('id','source','service','correlation_id'):
        if not isinstance(event[key],str) or not IDENT.fullmatch(event[key]):raise ValueError('Invalid '+key)
    try:
        when=datetime.fromisoformat(event['timestamp'].replace('Z','+00:00'))
        if when.tzinfo is None:raise ValueError()
    except (ValueError,TypeError,AttributeError) as exc:raise ValueError('Timestamp requires ISO timezone') from exc
    if not isinstance(event['data'],dict) or not KINDS[event['type']]<=set(event['data']):raise ValueError('Missing contract payload fields')
    bounded(event)
    if len(json.dumps(event,allow_nan=False).encode())>LIMIT:raise ValueError('Contract exceeds 64 KiB')
    if event['type']=='DeploymentEvent' and event['data']['status'] not in ('started','healthy','failed','rollback_started','rollback_verified','rollback_failed','security_failed'):
        raise ValueError('Unknown deployment status')
    if event['type']=='MonitoringAlert' and event['data']['status'] not in ('firing','resolved'):raise ValueError('Invalid alert status')
    if event['type']=='MonitoringAlert' and not isinstance(event['data']['fingerprint'],str):raise ValueError('Invalid alert fingerprint')
    return event


def envelope(kind, source, service, data, correlation_id=None, event_id=None):
    return validate(dict(schema_version=VERSION,type=kind,id=event_id or uuid.uuid4().hex,
        source=source,service=service,correlation_id=correlation_id or uuid.uuid4().hex,timestamp=utc(),data=data))


def schema():
    variants=[]
    for kind,required in KINDS.items():
        variants.append(dict(type='object',additionalProperties=False,required=sorted(FIELDS),properties={
          'schema_version':{'const':VERSION},'type':{'const':kind},'id':{'type':'string','pattern':IDENT.pattern},
          'source':{'type':'string','pattern':IDENT.pattern},'service':{'type':'string','pattern':IDENT.pattern},
          'correlation_id':{'type':'string','pattern':IDENT.pattern},'timestamp':{'type':'string','format':'date-time'},
          'data':{'type':'object','required':sorted(required)}}))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://github.com/Vishnu063/devops-triage-assistant/ecosystem/1.0',
            'title':'DevOps ecosystem v1.0 (runtime additionally enforces bounds and semantic enums)','oneOf':variants}


def endpoint(url):
    p=urlsplit(url)
    if not p.hostname or p.username or p.password or p.fragment or p.query or p.scheme not in ('http','https'):
        raise ValueError('Use a configured HTTPS URL without credentials, query or fragment')
    if p.scheme=='http' and p.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Plain HTTP is loopback-only')
    return url.rstrip('/')


def transport(url, token, value=None, retries=2):
    endpoint(url)
    if not isinstance(token,str) or not 32<=len(token)<=512 or any(ord(c)<33 for c in token):raise ValueError('Configure a private bearer token of at least 32 characters')
    if type(retries) is not int or not 0<=retries<=2:raise ValueError('Retry bound is zero through two')
    body=None if value is None else json.dumps(value,allow_nan=False).encode()
    if body and len(body)>LIMIT:raise ValueError('Request too large')
    for attempt in range(retries+1):
        try:
            request=Request(url,data=body,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=5) as response:
                raw=response.read(LIMIT+1)
                if len(raw)>LIMIT:raise ValueError('Response too large')
                return json.loads(raw)
        except HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==retries:raise ValueError('Ecosystem HTTP request refused: '+str(exc.code)) from None
        except (URLError,TimeoutError,OSError):
            if attempt==retries:raise ValueError('Ecosystem transport failed; inspect the private local outbox') from None
        if attempt<retries:time.sleep(0.2*(attempt+1))


def emit(event, url, token, outbox=None):
    event=validate(event)
    if outbox:
        path=Path(outbox);path.mkdir(mode=0o700,parents=True,exist_ok=True)
        path.chmod(0o700);file=path/(hashlib.sha256(event['id'].encode()).hexdigest()+'.json')
        if file.exists():
            if json.loads(file.read_text())!=event:raise ValueError('Outbox event identity collision')
        else:
            fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream:json.dump(event,stream)
    result=transport(url,token,event)
    if outbox:file.unlink()
    return result


def diagnose(event, report=None):
    """Summarize the existing collectors/findings; treat causes as hypotheses."""
    validate(event);report=report or {};findings=redact(report.get('findings',[]))[:20]
    observations=report.get('snapshot',{}).get('observations',{})
    refs=[event['id']]
    if report.get('incident_id'):refs.append(report['incident_id'])
    hypotheses=[dict(summary=f.get('likely_cause') or f.get('title') or 'Condition needs investigation',evidence_refs=refs,confidence='hypothesis') for f in findings]
    if not hypotheses:hypotheses=[dict(summary='Alert/deployment failure is reported; collection is needed before attributing cause.',evidence_refs=refs,confidence='insufficient_evidence')]
    commands=[dict(command=['docker','--context','CONFIGURED_CONTEXT','inspect','EXACT_CONTAINER_ID'],
        does='Reads the explicitly selected container state',why='Corroborates running state, exit status and identity',
        access='read-only',problem_output='Stopped/restarting state, nonzero exit or changed identity'),
        dict(command=['kubectl','--context','CONFIGURED_CONTEXT','--namespace','CONFIGURED_NAMESPACE','get','events','--field-selector','involvedObject.name=CONFIGURED_RESOURCE','-o','json'],
        does='Reads namespace-scoped events for one configured resource',why='Correlates rollout, image and scheduling symptoms',
        access='read-only',problem_output='BackOff, FailedScheduling, FailedMount or rollout warnings')]
    return envelope('Diagnosis','triage-assistant',event['service'],dict(hypotheses=hypotheses,evidence_refs=refs,
         observations=redact(observations),log_signals=report.get('deep_evidence',{}).get('log_signals',{}),commands=commands,
         uncertainty='Observed symptoms and temporal correlation do not prove root cause. Commands are suggestions only; placeholders require owner review.'),event['correlation_id'])


def verify(checks, health=None):
    """Combine independent typed criteria. Missing required evidence is inconclusive."""
    allowed={'container','kubernetes_readiness','rollout','prometheus','error_rate'}
    if not isinstance(checks,dict) or set(checks)-allowed or any(type(v) is not bool and v is not None for v in checks.values()):
        raise ValueError('Verification checks require bool or unknown values')
    started=time.monotonic();values=dict(checks)
    if health is not None:values['http']=check_health(health)['healthy']
    status='failed' if False in values.values() else 'verified' if values and all(v is True for v in values.values()) else 'inconclusive'
    return dict(status=status,checks=values,seconds=round(time.monotonic()-started,3),scope='Configured success criteria only; missing or failed required evidence prevents recovery.')


def k8sgpt(context, namespace, enabled=False):
    if not enabled:return {'status':'disabled','executable':False,'explanation':'Optional analysis; no AI provider configured'}
    if not shutil.which('k8sgpt'):return {'status':'unavailable','executable':False}
    for value in (context,namespace):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',value):raise ValueError('Exact Kubernetes scope required')
    # No --explain: deterministic analyzer output, no configured provider is invoked.
    try:
      with tempfile_output() as output:
        result=subprocess.run(['k8sgpt','analyze','--kubecontext',context,'--namespace',namespace,'--output','json'],
            stdout=output,stderr=subprocess.DEVNULL,timeout=20,check=False)
        output.seek(0);raw=output.read(LIMIT+1)
    except (OSError,subprocess.TimeoutExpired):return {'status':'inconclusive','executable':False}
    if result.returncode or len(raw)>LIMIT:return {'status':'inconclusive','executable':False}
    return {'status':'observed','executable':False,'untrusted':True,'evidence':redact(json.loads(raw))}


def tempfile_output():
    import tempfile
    return tempfile.TemporaryFile()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['schema','validate','diagnose','emit'])
    p.add_argument('--file',type=Path);p.add_argument('--url');p.add_argument('--token-env',default='OPS_PILOT_EVENT_TOKEN');p.add_argument('--outbox',type=Path)
    args=p.parse_args()
    try:
        if args.operation=='schema':print(json.dumps(schema(),indent=2));return
        if args.file is None or args.file.stat().st_size>LIMIT:raise ValueError('Use a bounded event JSON file')
        value=json.loads(args.file.read_text())
        if args.operation=='validate':validate(value);print('Versioned event valid')
        elif args.operation=='diagnose':print(json.dumps(diagnose(value),indent=2))
        else:emit(value,args.url,os.environ.get(args.token_env,''),args.outbox);print('Event delivered; no credentials printed')
    except (OSError,ValueError,TypeError) as exc:p.exit(2,'Integration refused: '+str(exc)+'\n')

if __name__=='__main__':main()
