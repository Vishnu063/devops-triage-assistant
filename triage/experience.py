"""Incident workflow around the shared, fail-closed repair engine."""
import json
import re
import time
import uuid
from .engine import fingerprint
from .health import check_health, validate_health
from .evidence import IncidentStore, annotate, deep_evidence


class ExperienceEngine:
    def __init__(self,core,health=None,context=None):
        self.core=core
        self.context=context or {"profile":"default","environment":"unspecified"}
        self.health=validate_health(health)
        self.store=IncidentStore(core)
    def __getattr__(self,name):
        return getattr(self.core,name)
    def scan(self,deep=False):
        report=self.core.scan()
        report['context']=self.context
        if deep:
            report['deep_evidence']=deep_evidence(self.adapter)
            report['findings'].extend(report['deep_evidence'].get('findings',[]))
        from .operations import setup_status
        report['setup_help']=setup_status(getattr(self.adapter,'tool','linux'),getattr(self.adapter,'config',{}),report['snapshot'].get('errors',[])+report.get('deep_evidence',{}).get('errors',[]))
        report['application_health']=check_health(self.health)
        if report['application_health']['healthy'] is False:
            report['findings'].append({'code':'application-health','title':'Configured application endpoint did not meet its health policy',
                'evidence':json.dumps(report['application_health']['samples']),
                'likely_cause':'The application, a dependency, routing or authentication may be failing; the probe does not establish the cause.',
                'next_steps':['Inspect the configured endpoint and relevant dependency health','Check whether probe credentials and expected response match the application'], 'service':None})
        return self.store.scan(annotate(report))
    def validate_connection(self):
        report=self.scan()
        snapshot=report['snapshot']
        write_access='not_tested; repairs still require approval'
        if getattr(self.adapter,'tool',None)=='kubernetes' and not snapshot.get('errors'):
            try:
                answer,_=self.adapter.command(['kubectl','--context','$context','--namespace','$namespace','auth','can-i','patch','deployment/$resource'])
                write_access='allowed_by_authorization_review; no repair attempted' if answer.strip().lower()=='yes' else 'not_verified; no repair attempted'
            except (RuntimeError,ValueError,OSError):write_access='not_verified; authorization review unavailable or denied'
        return {'target':self.adapter.target,'read_access':'verified_for_collector_scope' if not snapshot.get('errors') and not snapshot.get('empty',False) else 'incomplete',
                'write_access':write_access,'scope':report['coverage'],
                'application_health':report['application_health'],'incident_id':report['incident_id'],
                'errors':snapshot.get('errors',[]),'note':'Read permission for this collector does not establish mutation privileges or complete tool health.'}
    def _save(self,p):
        with self.core.connect() as db:
            db.execute('UPDATE plans SET payload=? WHERE id=?',(json.dumps(p),p['id']))
    def _policy(self,p):
        if p.get('health_policy_hash')!=fingerprint(self.health):
            raise ValueError('Application health policy changed; review a fresh plan')
    def plan(self,action):
        p=self.core.plan(action)
        incident,_=self.store.latest(self.adapter.target)
        p['incident_id']=incident or uuid.uuid4().hex
        p['before_incident_id']=incident
        p['health_policy_hash']=fingerprint(self.health)
        p['application_health']=self.health
        snapshot=getattr(self.adapter,'last_snapshot',{})
        obs=snapshot.get('observations',{})
        p['preview']={'target':self.adapter.target,'before':obs or snapshot.get('services',{}).get(p.get('service'),{}) or {'service':p.get('service'),'required_state':'loaded and failed','observed_state_hash':p['state_hash']},
            'operation':p.get('command') or {'method':p.get('method'),'url':p.get('url')},
            'expected_effect':'Run the exact reviewed operation; then evaluate the state probe and configured application endpoint.',
            'impact':p['risk'],'dry_run':False,'scope':'Preview is descriptive. It does not simulate the provider operation.'}
        if getattr(self.adapter,'tool',None)=='kubernetes':
            p['rollback_source']={key:obs.get(key,[]) for key in ('uid','generation','revision','template_hash')}
            p['rollback']='A separate approved rollback may be proposed after a failed recovery if the captured revision/template and current generation can be verified.'
        self._save(p)
        self.store.record(p['incident_id'],self.adapter.target,'repair_planned',p)
        return p
    def approve(self,plan_id):
        p=self.core.show(plan_id);self._policy(p)
        if p.get('kind')=='rollback':
            with self.core.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT status FROM plans WHERE id=?',(plan_id,)).fetchone()
                if not row or row[0]!='pending':raise ValueError('Rollback is no longer pending')
                self._validate_rollback(p)
                db.execute("UPDATE plans SET status='approved' WHERE id=?",(plan_id,))
                self.core.event(db,plan_id,'approved','separate rollback approval')
            result={'id':plan_id,'status':'approved'}
        else:result=self.core.approve(plan_id)
        self.store.record(p['incident_id'],self.adapter.target,'approval',{'id':plan_id,'kind':p.get('kind','repair')})
        return result
    def cancel(self,plan_id):
        p=self.core.show(plan_id)
        if p['target']!=self.adapter.target:raise ValueError('Select the plan target before cancelling it')
        result=self.core.cancel(plan_id)
        self.store.record(p.get('incident_id',plan_id),self.adapter.target,'cancelled',result)
        return result
    def apply(self,plan_id):
        p=self.core.show(plan_id);self._policy(p)
        if p.get('kind')=='rollback':return self._apply_rollback(p)
        self.store.record(p['incident_id'],self.adapter.target,'execution_requested',{'id':plan_id})
        result=self.core.apply(plan_id)
        result['infrastructure_status']=result['status']
        result['application_health']=check_health(self.health)
        if result['application_health']['healthy'] is False:
            result['status']='needs_attention'
            result['failure_reason']='The configured application health policy failed after the repair.'
            with self.core.connect() as db:
                db.execute("UPDATE plans SET status='needs_attention' WHERE id=?",(plan_id,))
                self.core.event(db,plan_id,'application_health_failed')
        snapshot=getattr(self.adapter,'last_snapshot',None)
        result['verification_scope']='Configured state probe plus application endpoint policy' if self.health else 'Configured state probe only; application health is not configured'
        self.store.record(p['incident_id'],self.adapter.target,'outcome:'+plan_id,{'result':result,'snapshot':snapshot})
        self.store.record(p['incident_id'],self.adapter.target,'repair_result',result)
        self.store.alert(p['incident_id'],'info' if result['status']=='verified' else 'warning',
                         'Recovery '+result['status']+' for plan '+plan_id,self.adapter.target)
        result['incident_id']=p['incident_id']
        self._follow_up(p,result)
        result['rollback_available']=self._can_rollback(p,snapshot) and result['status']=='needs_attention'
        return result
    def _follow_up(self,p,result):
        if p.get('before_incident_id'):
            try:
                from .operations import compare
                before=self.store.get_scan(p['before_incident_id'],self.adapter.target)
                after=self.scan(bool(before.get('deep_evidence')))
                result['comparison']=compare(before,after)
                self.store.record(p['incident_id'],self.adapter.target,'post_repair_comparison',result['comparison'])
                self.store.record(after['incident_id'],self.adapter.target,'related_repair',{'incident':p['incident_id']})
            except (ValueError,RuntimeError,OSError):
                result['comparison_error']='Post-repair evidence could not be collected. Run fresh checks; the recorded repair result is unchanged.'
    def _can_rollback(self,p,snapshot):
        if getattr(self.adapter,'tool',None)!='kubernetes' or not snapshot:return False
        source=p.get('rollback_source',{});obs=snapshot.get('observations',{})
        try:
            revision=str(source['revision'][0])
            return bool(re.fullmatch(r'[1-9][0-9]*',revision)) and bool(source['template_hash']) and obs['uid']==source['uid'] and obs['generation'][0]==source['generation'][0]+1 and int(obs['revision'][0])>int(revision)
        except (KeyError,IndexError,TypeError,ValueError):return False
    def rollback_plan(self,parent_id):
        parent=self.core.show(parent_id)
        if parent.get('kind')=='rollback' or parent['status']!='needs_attention' or parent['target']!=self.adapter.target:
            raise ValueError('Rollback requires a failed recovery on this exact target')
        _,outcome=self.store.latest(self.adapter.target,'outcome:'+parent_id)
        if not outcome or not self._can_rollback(parent,outcome['snapshot']):
            raise ValueError('No verified prior revision is available; inspect target state and use your recovery runbook')
        current=self.adapter.collect();saved=outcome['snapshot']['observations'];obs=current['observations']
        if any(obs.get(key)!=saved.get(key) for key in ('uid','generation','template_hash','revision')):
            raise ValueError('Deployment changed after the repair; rollback must be reviewed manually')
        revision=str(parent['rollback_source']['revision'][0])
        command=['kubectl','--context','$context','--namespace','$namespace','rollout','undo','deployment/$resource','--to-revision='+revision]
        p={'id':uuid.uuid4().hex,'target':self.adapter.target,'service':'kubernetes','tool':'kubernetes','kind':'rollback',
           'parent_id':parent_id,'incident_id':parent['incident_id'],'before_incident_id':self.store.latest(self.adapter.target)[0],'state_hash':self.adapter.state_hash(current),
           'expires_at':time.time()+300,'command':[self.adapter.render(x) for x in command],
           'expected_template_hash':parent['rollback_source']['template_hash'],
           'health_policy_hash':fingerprint(self.health),'application_health':self.health,
           'risk':'Restores the captured earlier Deployment pod template. Pods will be replaced; availability may decrease. External database/schema changes are not reversed.',
           'verification':'Original template hash, observed generation/replica state, and configured application endpoint policy must pass.',
           'rollback':'No recursive or automatic rollback is supported.'}
        p['preview']={'before':obs,'after_template_hash':p['expected_template_hash'],'operation':p['command'],'dry_run':False,'impact':p['risk']}
        with self.core.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for raw,status in db.execute("SELECT payload,status FROM plans WHERE status IN ('pending','approved','executing')"):
                old=json.loads(raw)
                if old['target']==p['target'] and (status=='executing' or old['expires_at']>time.time()):
                    raise ValueError('Another active plan exists for this target')
            db.execute("INSERT INTO plans VALUES (?,?,'pending')",(p['id'],json.dumps(p)))
            self.core.event(db,p['id'],'planned','rollback')
        self.store.record(p['incident_id'],self.adapter.target,'rollback_planned',p)
        return p
    def _validate_rollback(self,p):
        self._policy(p)
        if p['target']!=self.adapter.target or getattr(self.adapter,'tool',None)!='kubernetes' or p['expires_at']<=time.time():
            raise ValueError('Rollback target changed or plan expired')
        parent=self.core.show(p['parent_id'])
        if parent['status']!='needs_attention':raise ValueError('Parent recovery no longer permits rollback')
        revision=str(parent['rollback_source']['revision'][0])
        expected=['kubectl','--context',self.adapter.config['context'],'--namespace',self.adapter.config['namespace'],'rollout','undo','deployment/'+self.adapter.config['resource'],'--to-revision='+revision]
        if p['command']!=expected or p['expected_template_hash']!=parent['rollback_source']['template_hash']:
            raise ValueError('Rollback command or captured template changed')
        snapshot=self.adapter.collect()
        if self.adapter.state_hash(snapshot)!=p['state_hash'] or not self._can_rollback(parent,snapshot):
            raise ValueError('Live Deployment evidence changed; review a fresh rollback')
    def _apply_rollback(self,p):
        with self.core.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status FROM plans WHERE id=?',(p['id'],)).fetchone()
            if not row or row[0]!='approved':raise ValueError('A separate unused rollback approval is required')
            self._validate_rollback(p)
            db.execute("UPDATE plans SET status='executing' WHERE id=?",(p['id'],))
            self.core.event(db,p['id'],'executing','rollback')
        state_ok=False;failure='Rollback state probe did not pass'
        try:
            self.adapter.command(p['command'],repair=True)
            for attempt in range(3):
                if attempt:time.sleep(1)
                snapshot=self.adapter.collect()
                if snapshot['observations'].get('template_hash')==p['expected_template_hash'] and self.adapter.verify(snapshot):
                    state_ok=True;break
        except (RuntimeError,ValueError,OSError):failure='Rollback dispatch or verification failed; inspect live state before another action'
        health=check_health(self.health)
        if state_ok and health['healthy'] is False:failure='Rollback restored the template, but the application health policy failed'
        status='verified' if state_ok and health['healthy'] is not False else 'needs_attention'
        result={'id':p['id'],'kind':'rollback','status':status,'application_health':health,
                'failure_reason':None if status=='verified' else failure,'note':'No further rollback or retry is automatic.','incident_id':p['incident_id']}
        with self.core.connect() as db:
            db.execute('UPDATE plans SET status=? WHERE id=?',(status,p['id']))
            self.core.event(db,p['id'],status,'rollback')
        self.store.record(p['incident_id'],self.adapter.target,'rollback_result',result)
        self._follow_up(p,result)
        self.store.alert(p['incident_id'],'info' if status=='verified' else 'warning','Rollback '+status+' for plan '+p['id'],self.adapter.target)
        return result
