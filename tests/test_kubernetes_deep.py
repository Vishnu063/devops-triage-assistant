"""Structured Kubernetes failures are scoped by ownership and never retain raw bodies."""
import copy
import json
import unittest
from triage.kubernetes import collect, references, selector, deployment_changes
from triage.engine import fingerprint


def resource():
    template={'metadata':{'labels':{'app':'demo'}},'spec':{'containers':[{'name':'app','image':'demo:v2',
        'env':[{'name':'PRIVATE','value':'DO_NOT_RETAIN'},{'name':'KEY','valueFrom':{'secretKeyRef':{'name':'required','key':'private'}}}]}]}}
    return {'metadata':{'uid':'dep-1','generation':2,'annotations':{'deployment.kubernetes.io/revision':'2'},'creationTimestamp':'2026-01-01T00:00:00Z'},
            'spec':{'selector':{'matchLabels':{'app':'demo'}},'template':template}}


class Adapter:
    tool='kubernetes'
    def __init__(self):
        self.config={'context':'test','namespace':'test','resource':'app','service':'web'}
        self.dep=resource();old=copy.deepcopy(self.dep['spec']['template']);old['spec']['containers'][0]['image']='demo:v1'
        self.rs={'metadata':{'uid':'rs-1','creationTimestamp':'2026-01-01T00:00:00Z','ownerReferences':[{'uid':'dep-1','controller':True}], 'annotations':{'deployment.kubernetes.io/revision':'1'}},'spec':{'template':old}}
        self.pod={'metadata':{'uid':'pod-1','ownerReferences':[{'uid':'rs-1','controller':True}]},'status':{'phase':'Pending',
            'conditions':[{'type':'PodScheduled','status':'False'}],
            'containerStatuses':[{'state':{'waiting':{'reason':'ImagePullBackOff','message':'DO_NOT_RETAIN'}},'lastState':{'terminated':{'reason':'OOMKilled'}}}]}}
        self.events=[{'reason':'Unhealthy','message':'Readiness probe failed: DO_NOT_RETAIN','lastTimestamp':'2026-01-02T00:00:00Z'},
                     {'reason':'FailedScheduling','message':'0/2 nodes: Insufficient memory DO_NOT_RETAIN','count':2}]
        self.secret_exists=False;self.deny_secret=False;self.deny_pods=False;self.calls=[]
        self.last_snapshot={'observations':{'uid':['dep-1'],'generation':[2],'template_hash':[fingerprint(self.dep['spec']['template'])]}}
    def command(self,args,**kwargs):
        self.calls.append((args,kwargs))
        if 'logs' in args:return 'Out of memory DO_NOT_RETAIN',0
        index=args.index('get');kind=args[index+1]
        if kind=='deployment':obj=self.dep
        elif kind=='replicasets':obj={'items':[self.rs]}
        elif kind=='pods':
            if self.deny_pods:raise RuntimeError('permission denied')
            obj={'items':[self.pod,{'metadata':{'uid':'foreign-pod','ownerReferences':[{'uid':'foreign-rs','controller':True}]},'status':{}}]}
        elif kind=='service':obj={'spec':{'selector':{'app':'other'}}}
        elif kind=='events':obj={'items':self.events}
        elif kind in ('secret','configmap'):
            if self.deny_secret:raise RuntimeError('permission denied')
            return ('secret/required' if self.secret_exists else ''),0
        else:raise AssertionError(kind)
        return json.dumps(obj),0


class KubernetesDeepTests(unittest.TestCase):
    def test_specific_findings_owned_scope_and_private_body_exclusion(self):
        adapter=Adapter();result=collect(adapter)
        codes={f['code'] for f in result['findings']}
        for code in ('image-pull','oom','missing-configuration','service-selector','probe','resource-shortage','scheduling'):
            self.assertIn('kubernetes:'+code,codes)
        self.assertEqual(len(codes),len(result['findings']))
        self.assertEqual(len(result['pods']),1);self.assertNotIn('DO_NOT_RETAIN',json.dumps(result))
        self.assertTrue(result['deployment_changes']['available'])
        self.assertEqual(result['deployment_changes']['images_before']['app'],'demo:v1')
        for args,kwargs in adapter.calls:
            self.assertIn('--context',args);self.assertIn('--namespace',args);self.assertLessEqual(kwargs['read_timeout'],6)
            if 'secret' in args:self.assertEqual(args[-2:],['-o','name'])
    def test_permission_denied_is_unknown_not_missing(self):
        adapter=Adapter();adapter.deny_secret=True;result=collect(adapter)
        self.assertIsNone(result['configuration_checks'][0]['exists'])
        self.assertNotIn('kubernetes:missing-configuration',{f['code'] for f in result['findings']})
        self.assertTrue(result['errors'])
    def test_unavailable_pods_is_incomplete_not_healthy(self):
        adapter=Adapter();adapter.deny_pods=True;result=collect(adapter)
        self.assertTrue(result['errors']);self.assertEqual(result['pods'],[])
    def test_deployment_drift_invalidates_bundle(self):
        adapter=Adapter();adapter.dep['spec']['template']['spec']['containers'][0]['image']='other:v3'
        result=collect(adapter);self.assertTrue(result['errors']);self.assertEqual(len(adapter.calls),1)
    def test_crash_loop_and_configuration_error(self):
        adapter=Adapter();adapter.pod['status']['containerStatuses']=[{'state':{'waiting':{'reason':'CrashLoopBackOff'}}},{'state':{'waiting':{'reason':'CreateContainerConfigError'}}}]
        codes={f['code'] for f in collect(adapter)['findings']}
        self.assertIn('kubernetes:crash-loop',codes);self.assertIn('kubernetes:configuration',codes)
    def test_missing_optional_reference_is_not_an_incident(self):
        adapter=Adapter();adapter.dep['spec']['template']['spec']['containers'][0]['env'][1]['valueFrom']['secretKeyRef']['optional']=True
        adapter.last_snapshot['observations']['template_hash']=[fingerprint(adapter.dep['spec']['template'])]
        result=collect(adapter);self.assertNotIn('kubernetes:missing-configuration',{f['code'] for f in result['findings']})
    def test_service_is_explicit_and_selectorless_is_not_mismatch(self):
        adapter=Adapter();adapter.config.pop('service');result=collect(adapter)
        self.assertFalse(result['service_check']['configured']);self.assertFalse(any('service' in args for args,_ in adapter.calls))
    def test_no_retained_revision_is_explicit(self):
        self.assertFalse(deployment_changes(resource(),[])['available'])
    def test_selector_and_reference_bounds(self):
        self.assertEqual(selector({'matchExpressions':[{'key':'app','operator':'In','values':['a','b']}]}),'app in (a,b)')
        with self.assertRaises(ValueError):selector({})
        with self.assertRaises(ValueError):selector({'matchLabels':{'app':'a,b'}})
        with self.assertRaises(ValueError):references({'imagePullSecrets':[{'name':'--all'}]})
    def test_namespace_owned_list_too_large_is_not_truncated_silently(self):
        adapter=Adapter();original=adapter.command
        def command(args,**kwargs):
            if 'pods' in args:return json.dumps({'items':[adapter.pod]*101}),0
            return original(args,**kwargs)
        adapter.command=command;self.assertTrue(collect(adapter)['errors'])
