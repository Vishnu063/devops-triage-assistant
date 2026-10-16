"""Opt-in checks against a newly created, explicitly named disposable kind cluster."""
import json
import os
import subprocess
import tempfile
import time
import unittest
import uuid
from triage.experience import ExperienceEngine
from triage.integrations import ToolAdapter
from triage.tool_engine import ToolEngine

CONTEXT='kind-triage-lab'


@unittest.skipUnless(os.environ.get('TRIAGE_RUN_K8S_LAB')=='1','Opt-in disposable kind lab')
class LiveKubernetesTests(unittest.TestCase):
    def test_deployment_owned_failure_bundle_and_revision_comparison(self):
        namespace='triage-'+uuid.uuid4().hex[:10]
        def kubectl(*args,document=None):
            run=subprocess.run(['kubectl','--context',CONTEXT,'--namespace',namespace,*args],input=None if document is None else json.dumps(document),text=True,capture_output=True,timeout=60)
            if run.returncode:raise RuntimeError('Disposable kubectl lab command failed: '+run.stderr[:300])
            return run.stdout
        config=json.loads(kubectl('config','view','--minify','-o','json'))
        server=config['clusters'][0]['cluster']['server']
        self.assertTrue(server.startswith(('https://127.0.0.1:','https://localhost:')),'Lab context must address local kind')
        kubectl('create','-f','-',document={'apiVersion':'v1','kind':'Namespace','metadata':{'name':namespace,'labels':{'triage-disposable-lab':'true'}}})
        identity=json.loads(kubectl('get','namespace',namespace,'-o','json'))['metadata']['uid']
        def cleanup():
            try:
                obj=json.loads(kubectl('get','namespace',namespace,'-o','json'))
                if obj['metadata']['uid']==identity and obj['metadata']['labels'].get('triage-disposable-lab')=='true':kubectl('delete','namespace',namespace,'--wait=false')
            except (RuntimeError,ValueError,KeyError):pass
        self.addCleanup(cleanup)
        deployment={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'app'},'spec':{'replicas':1,'selector':{'matchLabels':{'app':'demo'}},'template':{'metadata':{'labels':{'app':'demo'}},'spec':{'containers':[{'name':'app','image':'busybox:1.37','imagePullPolicy':'IfNotPresent','command':['sh','-c','sleep 3600'],'readinessProbe':{'exec':{'command':['sh','-c','exit 1']},'periodSeconds':1,'initialDelaySeconds':0}}]}}}}
        kubectl('apply','-f','-',document=deployment)
        kubectl('apply','-f','-',document={'apiVersion':'v1','kind':'Service','metadata':{'name':'web'},'spec':{'selector':{'app':'wrong'},'ports':[{'port':80}]}})
        adapter=ToolAdapter('kubernetes',{'context':CONTEXT,'namespace':namespace,'resource':'app','service':'web'})
        with tempfile.TemporaryDirectory() as folder:
            engine=ExperienceEngine(ToolEngine(adapter,folder))
            first=None
            for _ in range(30):
                first=engine.scan(True)
                if any(f['code']=='kubernetes:probe' for f in first['findings']):break
                time.sleep(1)
            self.assertIn('kubernetes:probe',{f['code'] for f in first['findings']})
            deployment['spec']['template']['spec']['containers'][0]['image']='invalid.invalid/triage/no-image:v2'
            deployment['spec']['template']['spec']['containers'][0]['env']=[{'name':'KEY','valueFrom':{'secretKeyRef':{'name':'intentionally-missing','key':'key'}}}]
            kubectl('apply','-f','-',document=deployment)
            report=None
            for _ in range(20):
                report=engine.scan(True);codes={f['code'] for f in report['findings']}
                if 'kubernetes:image-pull' in codes and report['deep_evidence'].get('deployment_changes',{}).get('available'):break
                time.sleep(1)
            codes={f['code'] for f in report['findings']}
            self.assertIn('kubernetes:image-pull',codes);self.assertIn('kubernetes:missing-configuration',codes);self.assertIn('kubernetes:service-selector',codes)
            self.assertTrue(report['deep_evidence']['deployment_changes']['available'])
            self.assertIn('images',report['deep_evidence']['deployment_changes']['changed_fields'])
            self.assertEqual(engine.history(),[],'Deep diagnosis must not execute repairs')
