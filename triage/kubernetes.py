"""Bounded Deployment-owned evidence; manifests and event/log bodies stay transient."""
import json
import re
import time
from datetime import datetime
from .engine import fingerprint
from .integrations import redact

NAME = re.compile(r'[a-z0-9]([-a-z0-9.]*[a-z0-9])?\Z')
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]*\Z')


def selector(spec):
    parts=[]
    def label(value):
        if not isinstance(value,str) or len(value)>253 or not LABEL.fullmatch(value):
            raise ValueError('Unsupported label selector')
        return value
    for key,value in sorted(spec.get('matchLabels',{}).items()):parts.append(label(key)+'='+label(value))
    for entry in spec.get('matchExpressions',[]):
        key=label(entry['key']);op=entry['operator'];values=entry.get('values',[])
        if op in ('In','NotIn') and values:
            parts.append(key+(' in ' if op=='In' else ' notin ')+'('+','.join(label(v) for v in values)+')')
        elif op=='Exists':parts.append(key)
        elif op=='DoesNotExist':parts.append('!'+key)
        else:raise ValueError('Unsupported label selector expression')
    if not parts:raise ValueError('Empty Deployment selector cannot scope deep evidence')
    return ','.join(parts)


def references(spec):
    found={}
    def add(kind,name,optional=False):
        if not isinstance(name,str) or not NAME.fullmatch(name) or len(name)>253:raise ValueError('Invalid configuration reference')
        found[(kind,name)]=found.get((kind,name),True) and optional is True
    for item in spec.get('imagePullSecrets',[]):add('secret',item['name'])
    for c in spec.get('containers',[])+spec.get('initContainers',[]):
        for env in c.get('env',[]):
            ref=env.get('valueFrom',{})
            for key,kind in [('secretKeyRef','secret'),('configMapKeyRef','configmap')]:
                if key in ref:add(kind,ref[key]['name'],ref[key].get('optional',False))
        for env in c.get('envFrom',[]):
            for key,kind in [('secretRef','secret'),('configMapRef','configmap')]:
                if key in env:add(kind,env[key]['name'],env[key].get('optional',False))
    for volume in spec.get('volumes',[]):
        for key,kind,namekey in [('secret','secret','secretName'),('configMap','configmap','name')]:
            if key in volume:add(kind,volume[key][namekey],volume[key].get('optional',False))
        for source in volume.get('projected',{}).get('sources',[]):
            for key,kind in [('secret','secret'),('configMap','configmap')]:
                if key in source:add(kind,source[key]['name'],source[key].get('optional',False))
    return found


def template_view(template):
    spec=template.get('spec',{});containers=spec.get('containers',[])+spec.get('initContainers',[])
    return {'template_hash':fingerprint(template),
            'images':{c['name']:redact(c.get('image','')) for c in containers},
            'resources_hash':fingerprint([c.get('resources',{}) for c in containers]),
            'probes_hash':fingerprint([{k:c[k] for k in ('readinessProbe','livenessProbe','startupProbe') if k in c} for c in containers]),
            'configuration_refs_hash':fingerprint(sorted((kind,name,optional) for (kind,name),optional in references(spec).items()))}


def deployment_changes(deployment,replicasets):
    current=str(deployment.get('metadata',{}).get('annotations',{}).get('deployment.kubernetes.io/revision',''))
    if not current.isdigit():return {'available':False,'scope':'Deployment revision annotation unavailable.'}
    previous=[rs for rs in replicasets if str(rs.get('metadata',{}).get('annotations',{}).get('deployment.kubernetes.io/revision','')).isdigit()
              and int(rs['metadata']['annotations']['deployment.kubernetes.io/revision'])<int(current)]
    if not previous:return {'available':False,'scope':'No retained prior owned ReplicaSet revision found.'}
    rs=max(previous,key=lambda r:int(r['metadata']['annotations']['deployment.kubernetes.io/revision']))
    before=template_view(rs.get('spec',{}).get('template',{}));after=template_view(deployment['spec']['template'])
    # Deployment controller injects pod-template-hash into ReplicaSet labels; exclude it from comparison.
    prior=json.loads(json.dumps(rs.get('spec',{}).get('template',{})))
    prior.get('metadata',{}).get('labels',{}).pop('pod-template-hash',None)
    current_template=json.loads(json.dumps(deployment['spec']['template']))
    current_template.get('metadata',{}).get('labels',{}).pop('pod-template-hash',None)
    return {'available':True,'previous_revision':str(rs['metadata']['annotations']['deployment.kubernetes.io/revision']),
            'current_revision':current,'previous_created_at':rs['metadata'].get('creationTimestamp'),
            'deployment_created_at':deployment['metadata'].get('creationTimestamp'),
            'template_changed':fingerprint(prior)!=fingerprint(current_template),
            'images_before':before['images'],'images_after':after['images'],
            'changed_fields':[key for key in before if before[key]!=after[key] and key!='template_hash'],
            'scope':'Comparison with the newest retained earlier owned ReplicaSet. Creation times are not deployment-change timestamps; differences do not prove causation.'}


def collect(adapter):
    result={'supported':True,'log_signals':{},'events':[],'errors':[],'findings':[], 'configuration_checks':[], 'pods':[],
            'scope':'One Deployment, its owned ReplicaSets/pods, bounded events/log signatures, referenced object existence and optional explicitly named Service. No node-capacity prediction or secret values.'}
    deadline=time.monotonic()+40
    prefix=['kubectl','--context','$context','--namespace','$namespace','--request-timeout=5s']
    def command(args):
        remaining=deadline-time.monotonic()
        if remaining<1:raise RuntimeError('Deep evidence time budget exhausted')
        return adapter.command(prefix+args,read_timeout=min(6,max(1,int(remaining))))[0]
    def get(args):
        value=json.loads(command(['get']+args+['-o','json']))
        if not isinstance(value,dict):raise ValueError('Expected a Kubernetes object')
        return value
    def items(obj):
        value=obj.get('items')
        if not isinstance(value,list):raise ValueError('Expected a Kubernetes list')
        if len(value)>100 or obj.get('metadata',{}).get('continue'):raise ValueError('Kubernetes evidence exceeds the bounded list scope')
        return value
    def finding(code,title,cause,steps,evidence):
        if not any(f['code']=='kubernetes:'+code for f in result['findings']):
            result['findings'].append({'code':'kubernetes:'+code,'title':title,'evidence':json.dumps(evidence),
                'likely_cause':cause,'next_steps':steps,'service':None})
    try:
        dep=get(['deployment','$resource']);uid=dep['metadata']['uid']
        if not isinstance(uid,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}',uid):raise ValueError('Invalid Deployment UID')
        baseline=getattr(adapter,'last_snapshot',{}).get('observations',{})
        if baseline and (baseline.get('uid')!=[uid] or baseline.get('template_hash')!=[fingerprint(dep['spec']['template'])]
                         or baseline.get('generation')!=[dep['metadata']['generation']]):
            raise ValueError('Deployment changed while collecting evidence; rerun the bundle')
        sel=selector(dep['spec']['selector'])
        rss=[rs for rs in items(get(['replicasets','-l',sel,'--chunk-size=100'])) if any(o.get('uid')==uid and o.get('controller') is True for o in rs.get('metadata',{}).get('ownerReferences',[]))]
        rs_uids={rs['metadata']['uid'] for rs in rss}
        pods=[pod for pod in items(get(['pods','-l',sel,'--chunk-size=100'])) if any(o.get('uid') in rs_uids and o.get('controller') is True for o in pod.get('metadata',{}).get('ownerReferences',[]))]
        if len(pods)>20:raise ValueError('More than 20 owned pods; narrow the supported workload scope')
        result['deployment_changes']=deployment_changes(dep,rss)
        for pod in pods:
            status=pod.get('status',{});summary={'uid':pod['metadata']['uid'],'phase':status.get('phase'), 'waiting_reasons':[], 'termination_reasons':[], 'restart_counts':[], 'failed_exit_codes':[]}
            for c in status.get('containerStatuses',[])+status.get('initContainerStatuses',[]):
                wait=c.get('state',{}).get('waiting',{}).get('reason')
                termination=c.get('state',{}).get('terminated') or c.get('lastState',{}).get('terminated') or {}
                terminated=termination.get('reason')
                if isinstance(wait,str):summary['waiting_reasons'].append(wait[:80])
                if isinstance(terminated,str):summary['termination_reasons'].append(terminated[:80])
                restarts=c.get('restartCount',0);exit_code=termination.get('exitCode')
                if type(restarts) is int:summary['restart_counts'].append(restarts)
                recent_restart=False
                try:
                    started=datetime.fromisoformat(c.get('state',{}).get('running',{})['startedAt'].replace('Z','+00:00')).timestamp()
                    finished=datetime.fromisoformat(termination['finishedAt'].replace('Z','+00:00')).timestamp()
                    recent_restart=0<=time.time()-started<=60 and 0<=time.time()-finished<=120
                except (KeyError,TypeError,ValueError):pass
                if type(exit_code) is int and exit_code!=0 and type(restarts) is int and restarts>=2 and (c.get('state',{}).get('terminated') or recent_restart):summary['failed_exit_codes'].append(exit_code)
            result['pods'].append(summary)
            if any(v in ('ImagePullBackOff','ErrImagePull') for v in summary['waiting_reasons']):
                finding('image-pull','Owned pod cannot pull its image','Image reference, registry credentials or network access may be wrong.', ['Inspect this pod’s events to distinguish missing image, authorization and connectivity.','Verify the exact image tag/digest and imagePullSecret references.'],summary)
            if 'CrashLoopBackOff' in summary['waiting_reasons'] or summary['failed_exit_codes']:
                finding('crash-loop','Owned pod has restart backoff or repeated failed exits','The runtime records a restart backoff or at least two restarts with a nonzero prior exit. Samples between backoffs may show terminated/running state; the cause is not established.', ['Inspect previous container exit status and bounded logs.','Check configuration, dependencies and resource limits before a restart.'],summary)
            if 'OOMKilled' in summary['termination_reasons']:
                finding('oom','Runtime recorded an OOM termination','The cgroup or node memory pressure may have terminated the container.', ['Compare limits, requests and peak memory usage.','Investigate application memory growth.'],summary)
            if 'CreateContainerConfigError' in summary['waiting_reasons']:
                finding('configuration','Owned pod cannot create its container configuration','A referenced object/key or other runtime configuration may be unavailable.', ['Review pod events and referenced Secret/ConfigMap existence.','Object existence does not prove required keys or values are correct.'],summary)
            if any(c.get('type')=='PodScheduled' and c.get('status')=='False' for c in status.get('conditions',[])):
                finding('scheduling','Owned pod is not scheduled','Resources, taints, affinity, storage or another scheduler constraint may block placement.', ['Read scheduler event signatures and inspect resource requests.','Do not assume adding CPU or memory will resolve every scheduling constraint.'],{'pod_uid':summary['uid']})
        # Inspect names only. Never request Secret/ConfigMap data in CLI output.
        refs=references(dep['spec']['template'].get('spec',{}))
        if len(refs)>20:raise ValueError('More than 20 configuration references; bounded checks are incomplete')
        for (kind,name),optional in refs.items():
            try:
                exists=bool(command(['get',kind,name,'--ignore-not-found=true','-o','name']).strip())
                result['configuration_checks'].append({'kind':kind,'name':name,'exists':exists,'optional':optional})
                if not exists and not optional:
                    finding('missing-configuration','Required referenced configuration object is missing','The Deployment references a Secret or ConfigMap not found in its namespace.', ['Restore or correct the source reference through your normal deployment workflow.','Verify required keys and application configuration separately; no values are collected.'],{'kind':kind,'name':name})
            except (RuntimeError,ValueError,OSError):
                result['configuration_checks'].append({'kind':kind,'name':name,'exists':None,'optional':optional})
                result['errors'].append('Referenced object existence could not be verified; check get permission for '+kind+'.')
        service=adapter.config.get('service')
        if service:
            svc=get(['service',service]);ss=svc.get('spec',{}).get('selector',{});labels=dep['spec']['template'].get('metadata',{}).get('labels',{})
            matches=bool(ss) and all(labels.get(k)==v for k,v in ss.items())
            result['service_check']={'configured':True,'selector_matches_template':matches if ss else None,
                                     'scope':'Selected Service selector versus Deployment template labels only; endpoints, ports and traffic are not verified.'}
            if ss and not matches:finding('service-selector','Configured Service does not select this Deployment template','Service selectors and intended workload labels may have drifted.', ['Confirm this Service is intended for the selected Deployment.','Correct source labels/selectors and verify endpoints and application traffic.'],result['service_check'])
        else:result['service_check']={'configured':False,'scope':'Set the optional service field to inspect one Service selector.'}
        # Event messages are reduced to known signatures; they are never retained.
        for object_uid in [uid]+[p['metadata']['uid'] for p in pods[:5]]:
            try:
                if not isinstance(object_uid,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}',object_uid):raise ValueError('Invalid pod UID')
                events=items(get(['events','--field-selector','involvedObject.uid='+object_uid,'--chunk-size=100']))
                for event in events:
                    reason=event.get('reason','');message=event.get('message','')
                    if reason not in ('Unhealthy','FailedScheduling','Failed','BackOff','FailedMount','FailedCreate'):continue
                    stamp=event.get('lastTimestamp') or event.get('eventTime') or event.get('metadata',{}).get('creationTimestamp')
                    result['events'].append({'reason':reason,'time':stamp,'count':event.get('count',1)})
                    if reason=='Unhealthy' and re.search(r'(readiness|liveness|startup) probe failed',message,re.I):
                        finding('probe','Owned workload has probe-failure events','Probe configuration, application readiness or dependencies may be failing; events can describe an earlier state.', ['Check probe timing, endpoint behavior and application dependencies.','Compare event timestamps with current readiness; do not disable probes blindly.'],{'event_reason':reason,'time':stamp})
                    if reason=='FailedScheduling' and re.search(r'insufficient (cpu|memory|ephemeral-storage)|too many pods',message,re.I):
                        finding('resource-shortage','Scheduler reported insufficient resources','The scheduler reported a capacity constraint at the event time.', ['Compare requests, quotas and allocatable capacity on eligible nodes.','Review taints/affinity and current usage; this collector does not prove present schedulability.'],{'event_reason':reason,'time':stamp})
            except (RuntimeError,ValueError,OSError):result['errors'].append('Some owned-object events were unavailable; check list events permission.')
        if len(pods)>5:result['errors'].append('Pod events limited to five owned pods; remaining pod events were not inspected.')
        try:
            from .evidence import log_signals
            raw=command(['logs','deployment/$resource','--all-containers','--tail=100','--max-log-requests=5'])
            result['log_signals']=log_signals(raw)
        except (RuntimeError,ValueError,OSError):result['errors'].append('Workload log signatures unavailable; check pods/log access and runtime state.')
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,IndexError):
        result['errors'].append('Kubernetes deep evidence incomplete or changed during collection. Check scoped permissions, compatible schemas and bounded workload size; rerun the bundle.')
    result['events']=result['events'][:100]
    return redact(result)
