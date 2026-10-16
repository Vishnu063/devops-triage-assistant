"""Private incident evidence and local alerts. No raw log bodies are persisted."""
import json
import re
import time
import uuid
from .engine import fingerprint
from .integrations import redact

SIGNALS={
 'memory':r'out of memory|oomkilled|cannot allocate memory',
 'disk':r'no space left on device|disk quota exceeded',
 'dns':r'no such host|name or service not known|temporary failure in name resolution',
 'dependency':r'connection refused|connection reset|upstream.*unavailable',
 'timeout':r'timed? out|deadline exceeded',
 'authorization':r'permission denied|accessdenied|unauthorized|forbidden',
 'image':r'imagepullbackoff|errimagepull|manifest unknown',
}


def log_signals(raw):
    return {key:len(re.findall(pattern,raw,re.I)) for key,pattern in SIGNALS.items() if re.search(pattern,raw,re.I)}


def annotate(report):
    signals=report.get('deep_evidence',{}).get('log_signals',{})
    for finding in report['findings']:
        observed=finding['code'] not in ('collection-failed','no-evidence','missing-evidence','incomplete')
        cause='possible';basis='The condition is observed; the underlying cause is a hypothesis.'
        if finding['code'].endswith(':oom'):
            cause='corroborated';basis='The runtime reports an OOM termination. The source of memory growth is not established.'
        elif signals and observed:
            cause='possible';basis='Log signature counts are available. A matching signature alone does not establish causation.'
        finding['confidence']={'observation':'confirmed' if observed else 'insufficient_evidence','cause':cause,'basis':basis,
            'missing_evidence':['Confirm the causal sequence and relevant configuration before treating a hypothesis as root cause.']}
    return report


def deep_evidence(adapter):
    tool=getattr(adapter,'tool','linux')
    result={'supported':tool in ('docker','podman','kubernetes'),'log_signals':{},'events':[],'errors':[]}
    if not result['supported']:
        result['scope']='No bounded deep collector implemented for this profile; baseline metrics/state and scan-to-scan changes remain available.'
        return result
    try:
        if tool in ('docker','podman'):
            prefix=['docker','--context','$context'] if tool=='docker' else ['podman','--connection','$context']
            raw,_=adapter.command(prefix+['logs','--tail','100','$resource'],include_stderr=True)
            result['log_signals']=log_signals(raw)
            result['scope']='Signature counts from the last 100 stdout/stderr log lines; raw log content is discarded.'
        else:
            prefix=['kubectl','--context','$context','--namespace','$namespace']
            snapshot=adapter.collect();uid=snapshot['observations'].get('uid',[])
            if not uid or not re.fullmatch(r'[A-Za-z0-9-]+',uid[0]):raise ValueError('Deployment UID unavailable')
            raw,_=adapter.command(prefix+['get','events','--field-selector','involvedObject.uid='+uid[0],'-o','json'])
            obj=json.loads(raw)
            result['events']=[{k:event[k] for k in ('type','reason','count','lastTimestamp') if k in event} for event in obj.get('items',[])[:100]]
            raw,_=adapter.command(prefix+['logs','deployment/$resource','--all-containers','--tail=100','--max-log-requests=5'],include_stderr=True)
            result['log_signals']=log_signals(raw)
            result['scope']='Deployment-owned event metadata and bounded workload log signatures; pod-owned events and raw messages are not retained.'
    except (ValueError,RuntimeError,KeyError,TypeError):
        result['errors'].append('Deep collection was incomplete; check read/log/event permissions and native CLI support.')
    return redact(result)


class IncidentStore:
    def __init__(self,engine):
        self.engine=engine
        with engine.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS incident_steps (id INTEGER PRIMARY KEY, incident TEXT, target TEXT, time REAL, kind TEXT, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, time REAL, incident TEXT, severity TEXT, message TEXT, dedupe TEXT, acknowledged INTEGER DEFAULT 0)')
    def record(self,incident,target,kind,payload):
        with self.engine.connect() as db:
            db.execute('INSERT INTO incident_steps (incident,target,time,kind,payload) VALUES (?,?,?,?,?)',(incident,target,time.time(),kind,json.dumps(payload)))
    def latest(self,target,kind='scan'):
        with self.engine.connect() as db:
            row=db.execute('SELECT incident,payload FROM incident_steps WHERE target=? AND kind=? ORDER BY id DESC LIMIT 1',(target,kind)).fetchone()
        return (row[0],json.loads(row[1])) if row else (None,None)
    def scan(self,report):
        target=report['target'];_,previous=self.latest(target)
        def view(value):
            snapshot=(value or {}).get('snapshot',{})
            if 'hostname' in snapshot:
                return {key:snapshot[key] for key in ('disk_used_percent','memory_used_percent','load1','services') if key in snapshot}
            return snapshot.get('observations',{})
        before=view(previous)
        after=view(report)
        changes=[{'field':key,'before':before.get(key,[]),'after':after.get(key,[])} for key in sorted(set(before)|set(after)) if previous and before.get(key)!=after.get(key)]
        incident=uuid.uuid4().hex
        report['incident_id']=incident;report['changes_since_previous_scan']=changes
        report['change_scope']='Differences between collected samples, not an audit log or proof of who changed the resource.'
        self.record(incident,target,'scan',report)
        if changes:self.record(incident,target,'observed_changes',changes)
        if report['findings']:
            self.alert(incident,'warning','Scan needs attention: '+', '.join(sorted({f['code'] for f in report['findings']})),target)
        return report
    def alert(self,incident,severity,message,target):
        dedupe=fingerprint({'target':target,'severity':severity,'message':message})
        with self.engine.connect() as db:
            if db.execute('SELECT 1 FROM alerts WHERE dedupe=? AND time>?',(dedupe,time.time()-600)).fetchone():return
            db.execute('INSERT INTO alerts VALUES (?,?,?,?,?,?,0)',(uuid.uuid4().hex,time.time(),incident,severity,message,dedupe))
    def alerts(self,acknowledge=None):
        with self.engine.connect() as db:
            if acknowledge:
                cursor=db.execute('UPDATE alerts SET acknowledged=1 WHERE id=?',(acknowledge,))
                if cursor.rowcount!=1:raise ValueError('Unknown alert')
            return [dict(zip(('id','time','incident','severity','message','acknowledged'),row)) for row in db.execute('SELECT id,time,incident,severity,message,acknowledged FROM alerts ORDER BY time DESC LIMIT 100')]
    def timeline(self,incident=None):
        with self.engine.connect() as db:
            rows=db.execute('SELECT incident,target,time,kind,payload FROM incident_steps '+('WHERE incident=? ' if incident else '')+'ORDER BY id DESC LIMIT 100',(incident,) if incident else ()).fetchall()
        return [dict(incident=i,target=t,time=stamp,kind=k,data=json.loads(p)) for i,t,stamp,k,p in rows]


def correlate(reports,store):
    if not 1<=len(reports)<=4:raise ValueError('Select between one and four configured tools')
    incident=uuid.uuid4().hex
    observations=[]
    for report in reports:
        observations.append({'target':report['target'],'incident_id':report['incident_id'],'codes':[f['code'] for f in report['findings']],
                             'signals':report.get('deep_evidence',{}).get('log_signals',{}),'changed_fields':[c['field'] for c in report.get('changes_since_previous_scan',[])]})
    memory=[r for r in reports if any('memory' in f['code'] or f['code'].endswith(':oom') for f in r['findings']) or r.get('deep_evidence',{}).get('log_signals',{}).get('memory')]
    hypotheses=[]
    if len(memory)>=2:
        hypotheses.append({'cause':'Memory-related evidence appears in multiple selected sources.','confidence':'corroborated',
            'evidence_targets':[r['target'] for r in memory],'limitation':'Selection does not prove these targets share a node or dependency; verify topology and timestamps.'})
    if any(r.get('changes_since_previous_scan') for r in reports) and any(r['findings'] for r in reports):
        hypotheses.append({'cause':'Observed changes coexist with reported problems.','confidence':'possible','limitation':'This is temporal context, not proof that a change caused the problem.'})
    result={'incident_id':incident,'sources':observations,'hypotheses':hypotheses,'scope':'Operator-selected sources; no automatic topology or causal attribution.'}
    store.record(incident,'multiple','correlation',result)
    return result
