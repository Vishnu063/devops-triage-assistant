"""Synthetic provider responses; these are not live provider acceptance tests."""
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from triage.catalog import PROFILES
from triage.integrations import ToolAdapter, catalog, requirements, LIMIT
from triage.tool_engine import ToolEngine


def j(value):
    return json.dumps(value)


# Handwritten response shapes, intentionally independent of collector projections.
FIXTURES = {
    'aws': (j({'InstanceStatuses':[{'InstanceId':'i-123','InstanceState':{'Name':'running'},'SystemStatus':{'Status':'impaired'},'InstanceStatus':{'Status':'ok'}}]}),'system','impaired'),
    'azure': (j({'name':'vm','provisioningState':'Failed','instanceView':{'statuses':[{'code':'PowerState/running'}]}}),'provisioning','Failed'),
    'gcp': (j({'id':'123','name':'vm','status':'TERMINATED','zone':'zone'}),'status','TERMINATED'),
    'digitalocean': (j([{'id':123,'name':'droplet','status':'off','region':{'slug':'blr1'}}]),'status','off'),
    'oci': (j({'data':{'id':'ocid1.test','display-name':'vm','lifecycle-state':'STOPPED'}}),'state','STOPPED'),
    'docker': (j([{'Id':'container-id','Name':'app','State':{'Status':'exited','ExitCode':1,'OOMKilled':False,'StartedAt':'2026-01-01'},'Config':{'Env':['PASSWORD=private-value']}}]),'state','exited'),
    'podman': (j([{'Id':'podman-id','Name':'app','State':{'Status':'exited','ExitCode':137,'OOMKilled':True,'StartedAt':'2026-01-01'}}]),'oom',True),
    'containerd': ('TASK PID STATUS\napp 0 STOPPED\n','state','STOPPED'),
    'compose': (j({'Service':'web','State':'exited','Health':'','ExitCode':1,'ID':'id'})+'\n'+j({'Service':'db','State':'running','ID':'dbid'}),'state','exited'),
    'buildah': (j({'Container':'working','ContainerID':'build-id','FromImageID':'base'}),'id','build-id'),
    'kubernetes': (j({'metadata':{'uid':'uid','resourceVersion':'1','generation':1},'spec':{'replicas':2,'template':{'spec':{'containers':[{'env':[{'name':'TOKEN','value':'private-value'}]}]}}},'status':{'availableReplicas':0,'observedGeneration':1,'conditions':[{'type':'Progressing','status':'False','reason':'ProgressDeadlineExceeded'}]}}),'desired',2),
    'helm': (j({'name':'app','version':2,'namespace':'default','info':{'status':'failed'},'manifest':'SECRET: private-value'}),'status','failed'),
    'kustomize': ('apiVersion: v1\nkind: Secret\ndata:\n  password: private-value\n---\nkind: Deployment\n','kind','Secret'),
    'argocd': (j({'metadata':{'uid':'uid'},'status':{'sync':{'status':'OutOfSync','revision':'sha'},'health':{'status':'Degraded'}}}),'health','Degraded'),
    'flux': (j({'metadata':{'uid':'uid','generation':1,'resourceVersion':'2'},'status':{'conditions':[{'type':'Ready','status':'False','reason':'BuildFailed'}],'lastAppliedRevision':'sha'}}),'reason','BuildFailed'),
    'jenkins': (j({'number':8,'result':'FAILURE','building':False}),'result','FAILURE'),
    'github-actions': (j({'id':123,'status':'completed','conclusion':'failure','head_sha':'sha','run_attempt':1}),'conclusion','failure'),
    'gitlab-ci': (j({'id':123,'status':'failed','sha':'sha','ref':'main'}),'status','failed'),
    'azure-pipelines': (j({'id':123,'status':'completed','result':'failed','sourceVersion':'sha'}),'result','failed'),
    'tekton': (j({'metadata':{'uid':'uid','resourceVersion':'1'},'status':{'conditions':[{'type':'Succeeded','status':'False','reason':'Failed'}]}}),'reason','Failed'),
    'terraform': (j({'valid':False,'error_count':1,'warning_count':0,'diagnostics':[{'severity':'error','summary':'Unsupported argument','detail':'private-value'}]}),'valid',False),
    'opentofu': (j({'valid':False,'error_count':1,'warning_count':0,'diagnostics':[{'severity':'error','summary':'Missing reference'}]}),'errors',1),
    'pulumi': (j({'deployment':{'resources':[{'urn':'urn:test','type':'aws:ec2:Instance','inputs':{'password':'private-value'}}],'pending_operations':[{'type':'creating'}]}}),'pending','creating'),
    'cloudformation': (j({'Stacks':[{'StackId':'stack-id','StackName':'app','StackStatus':'UPDATE_ROLLBACK_FAILED','Outputs':[{'OutputValue':'private-value'}]}]}),'status','UPDATE_ROLLBACK_FAILED'),
    'cdk': (j({'Stacks':[{'StackId':'stack-id','StackName':'app','StackStatus':'CREATE_FAILED'}]}),'status','CREATE_FAILED'),
    'ansible': (j({'_meta':{'hostvars':{'server':{'password':'private-value'}}},'web':{'hosts':['server']}}),'host_count',1),
    'puppet': ("service { 'app':\n  ensure => 'stopped',\n}\n",'ensure','stopped'),
    'chef': (j({'ohai_time':1600000000}),'observed',1600000000),
    'salt': (j({'minion':False}),'responsive',False),
    'cloud-init': (j({'status':'error','extended_status':'error - done','stage':None,'errors':['private-value']}),'status','error'),
    'prometheus': (j({'status':'success','data':{'activeTargets':[{'health':'down','labels':{'job':'app'},'lastError':'private-value'}]}}),'target_health','down'),
    'grafana': (j({'database':'failing','version':'12.0'}),'database','failing'),
    'datadog': (j({'id':123,'name':'app','overall_state':'Alert','query':'private-value'}),'state','Alert'),
    'zabbix': (j({'jsonrpc':'2.0','result':[{'hostid':'1','host':'app','status':'0','interfaces':[{'available':'2','type':'1'}]}],'id':1}),'availability','2'),
    'cloudwatch': (j({'MetricAlarms':[{'AlarmName':'app','StateValue':'ALARM'}]}),'state','ALARM'),
    'elasticsearch': (j({'cluster_name':'app','status':'red','number_of_nodes':1,'unassigned_shards':2,'timed_out':False}),'status','red'),
    'logstash': (j({'pipelines':{'main':{'events':{'in':20,'out':10},'plugins':{'password':'private-value'}}}}),'events_in',20),
    'kibana': (j({'status':{'overall':{'level':'degraded'}},'version':{'number':'9.0'}}),'level','degraded'),
    'loki': ('Ingester not ready','ready',False),
    'jaeger': (j({'data':['app'],'errors':None}),'services','app'),
    'trivy': (j({'Results':[{'Vulnerabilities':[{'VulnerabilityID':'CVE-1','Severity':'CRITICAL','PkgName':'lib','FixedVersion':'2'}]}]}),'severity','CRITICAL'),
    'snyk': (j({'ok':False,'vulnerabilities':[{'id':'SNYK-1','severity':'high','packageName':'lib','code':'private-value'}]}),'severity','high'),
    'sonarqube': (j({'projectStatus':{'status':'ERROR','conditions':[{'metricKey':'bugs','status':'ERROR'}]}}),'status','ERROR'),
    'gitleaks': (j([{'RuleID':'aws-key','File':'app.env','StartLine':1,'Fingerprint':'hash','Secret':'private-value','Match':'private-value'}]),'rule','aws-key'),
    'semgrep': (j({'results':[{'check_id':'unsafe','path':'app.py','start':{'line':1},'extra':{'severity':'ERROR','lines':'private-value'}}],'errors':[]}),'rule','unsafe'),
    'vault': (j({'initialized':True,'sealed':True,'standby':False,'version':'1.20'}),'sealed',True),
    'secrets-manager': (j({'ARN':'arn:test','Name':'app','RotationEnabled':True,'DeletedDate':1700000000,'SecretString':'private-value'}),'deletion',1700000000),
    'azure-key-vault': (j([{'id':'secret-version','attributes':{'enabled':False,'expires':1700000000},'value':'private-value'}]),'enabled',False),
    'keycloak': (j({'status':'DOWN','checks':[{'name':'database','status':'DOWN'}]}),'status','DOWN'),
    'teleport': (j({'server_version':'18.0','proxy':{'ssh':{'public_addr':'proxy:3023'}}}),'version','18.0'),
    'nginx': ('Active connections: 12\nserver accepts handled requests\n 20 20 30\nReading: 1 Writing: 2 Waiting: 9\n','active_connections',12),
    'haproxy': ('# pxname,svname,status\nweb,server1,DOWN\n','state','DOWN'),
    'traefik': (j({'http':{'routers':{'errors':2},'services':{'errors':0}},'tcp':{'routers':{'errors':0},'services':{'errors':0}}}),'http_router_errors',2),
    'istio': (j({'items':[{'metadata':{'name':'istiod'},'status':{'phase':'Pending','containerStatuses':[{'ready':False,'state':{'waiting':{'reason':'ImagePullBackOff'}}}]}}]}),'ready',False),
    'envoy': ('PRE_INITIALIZING\n','ready',False),
    'postgresql': ('in_recovery,numbackends,deadlocks\nf,2,0\n','in_recovery','f'),
    'mysql': ('read_only\tversion\tmax_connections\n1\t8.4\t150\n','read_only','1'),
    'redis': (j('# Memory\r\nused_memory:1024\r\nmaxmemory:2048\r\nmaxmemory_policy:noeviction\r\n'),'used_memory','1024'),
    'mongodb': (j({'ok':1,'isWritablePrimary':False,'secondary':True,'setName':'rs0','electionId':'election'}),'secondary',True),
    'kafka': ('Topic: app\tPartition: 0\tLeader: -1\tReplicas: 1,2\tIsr: 1\n','leader',-1),
}


def adapter_for(tool):
    config = {key: 'sample' for key in requirements(PROFILES[tool])}
    if PROFILES[tool]['endpoint']:
        config['base_url'] = 'http://127.0.0.1:19876'
    with patch.dict(os.environ, {'TRIAGE_MONGODB_URI':'mongodb://127.0.0.1:27017'}):
        return ToolAdapter(tool, config)


def fixture_collect(adapter, raw=None):
    data = FIXTURES[adapter.tool][0] if raw is None else raw
    with patch.object(adapter, 'command', return_value=(data,0)), patch.object(adapter, 'request', return_value=(data,200)):
        return adapter.collect()


class ProfileTests(unittest.TestCase):
    def test_fixture_inventory_covers_exactly_all_profiles(self):
        self.assertEqual(set(FIXTURES), set(PROFILES))
        self.assertEqual(len(FIXTURES), 60)
    def test_clean_scans_are_evidence_not_missing_results(self):
        for key, raw in [('gitleaks','[]'),('trivy','{"Results":[]}'),('semgrep','{"results":[],"errors":[]}')]:
            with self.subTest(tool=key):
                adapter = adapter_for(key)
                snapshot = fixture_collect(adapter, raw)
                self.assertFalse(snapshot['empty'])
                self.assertEqual(snapshot['observations']['finding_count'], [0])
                self.assertEqual(adapter.findings(snapshot), [])
    def test_kafka_empty_isr_is_underreplicated(self):
        adapter = adapter_for('kafka')
        raw = 'Topic: app\tPartition: 0\tLeader: 1\tReplicas: 1\tIsr: \tElr: \tLastKnownElr: \n'
        self.assertEqual(adapter.parse(raw)['under_replicated'], [True])
    def test_semgrep_scan_errors_are_findings(self):
        adapter = adapter_for('semgrep')
        snapshot = fixture_collect(adapter, '{"results":[],"errors":[{"type":"ParseError"}]}')
        self.assertTrue(adapter.findings(snapshot), 'Scanner errors must not appear as a clean scan')
    def test_truncated_evidence_cannot_offer_repairs(self):
        adapter = adapter_for('docker')
        raw = j([{'Id':str(i),'State':{'Status':'exited'}} for i in range(201)])
        snapshot = fixture_collect(adapter,raw)
        self.assertTrue(snapshot['truncated'])
        self.assertFalse(adapter.repair_allowed(snapshot))
    def test_missing_identity_cannot_offer_repair(self):
        adapter = adapter_for('docker')
        snapshot = fixture_collect(adapter,j([{'State':{'Status':'exited'}}]))
        self.assertIn('id',snapshot['missing_evidence'])
        self.assertFalse(adapter.repair_allowed(snapshot))
    def test_projection_rejects_arbitrary_error_payload(self):
        adapter = adapter_for('docker')
        snapshot = fixture_collect(adapter,j({'error':'private-value'}))
        self.assertTrue(snapshot['empty'])
        self.assertTrue(adapter.findings(snapshot))
    def test_all_required_fields_are_explicit(self):
        for tool,p in PROFILES.items():
            if requirements(p):
                with self.subTest(tool=tool), self.assertRaises(ValueError): ToolAdapter(tool,{})
    def test_bad_header_binding_is_validation_error(self):
        for binding in ({'env':None},{'env':123}):
            with self.subTest(binding=binding), self.assertRaises(ValueError):
                ToolAdapter('grafana',{'base_url':'https://example.invalid','headers':{'Authorization':binding}}).headers()
    def test_connection_rejects_secret_fields_and_unsafe_urls(self):
        with self.assertRaises(ValueError): ToolAdapter('grafana',{'base_url':'https://example.invalid','password':'secret'})
        for url in ('http://remote.example','https://u:p@example.invalid','https://example.invalid/?token=x','file:///tmp/x'):
            with self.subTest(url=url), self.assertRaises(ValueError): ToolAdapter('grafana',{'base_url':url})
    def test_catalog_does_not_leak_configuration_or_connect(self):
        with patch.object(ToolAdapter,'collect',side_effect=AssertionError('must not collect')):
            result = catalog({'grafana':{'base_url':'https://example.invalid','headers':{'Authorization':{'env':'TOKEN'}}}})
        self.assertEqual(len(result),60)
        self.assertNotIn('https://example.invalid',j(result))
    def test_failed_collection_is_actionable_and_cannot_offer_repairs(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = ToolEngine(adapter_for('docker'),directory)
            with patch.object(engine.adapter,'collect',side_effect=RuntimeError('permission denied')):
                report = engine.scan()
            self.assertEqual(report['actions'],[])
            self.assertEqual(report['findings'][0]['code'],'collection-failed')


def profile_test(tool):
    def test(self):
        adapter = adapter_for(tool)
        snapshot = fixture_collect(adapter)
        _, field, value = FIXTURES[tool]
        self.assertIn(value,snapshot['observations'][field])
        self.assertFalse(snapshot['missing_evidence'])
        self.assertFalse(snapshot['empty'])
        self.assertNotIn('private-value',j(snapshot))
        findings = adapter.findings(snapshot)
        for finding in findings:
            self.assertTrue(finding['title'])
            self.assertTrue(finding['likely_cause'])
            self.assertTrue(finding['next_steps'])
    return test


for _tool in FIXTURES:
    setattr(ProfileTests, 'test_profile_'+_tool.replace('-','_'), profile_test(_tool))


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adapter = adapter_for('docker')
        self.snapshot = fixture_collect(self.adapter)
        self.engine = ToolEngine(self.adapter,self.tmp.name)
        self.calls = 0
        self.patch_collect = patch.object(self.adapter,'collect',side_effect=lambda: json.loads(j(self.snapshot)))
        self.patch_collect.start()
        self.addCleanup(self.patch_collect.stop)
        self.patch_execute = patch.object(self.adapter,'execute_repair',side_effect=self.execute)
        self.patch_execute.start()
        self.addCleanup(self.patch_execute.stop)
    def execute(self):
        self.calls += 1
        self.snapshot['observations']['state'] = ['running']
    def plan(self):
        return self.engine.plan('restart')['id']
    def test_apply_without_approval_never_dispatches(self):
        with self.assertRaises(ValueError): self.engine.apply(self.plan())
        self.assertEqual(self.calls,0)
    def test_review_approve_apply_and_replay(self):
        pid=self.plan()
        self.assertEqual(self.engine.show(pid)['command'][-1],'sample')
        self.engine.approve(pid)
        self.assertEqual(self.engine.apply(pid)['status'],'verified')
        with self.assertRaises(ValueError): self.engine.apply(pid)
        self.assertEqual(self.calls,1)
    def test_evidence_change_after_approval(self):
        pid=self.plan();self.engine.approve(pid)
        self.snapshot['observations']['id']=['replacement-container']
        with self.assertRaises(ValueError): self.engine.apply(pid)
        self.assertEqual(self.calls,0)
    def test_expiry_after_approval(self):
        pid=self.plan();self.engine.approve(pid)
        with patch('triage.tool_engine.time.time',return_value=10**12):
            with self.assertRaises(ValueError): self.engine.apply(pid)
        self.assertEqual(self.calls,0)
    def test_changed_tool_or_command_blocks_apply(self):
        pid=self.plan();self.engine.approve(pid)
        with patch.object(self.adapter,'repair_description',return_value={'command':['different']}):
            with self.assertRaises(ValueError): self.engine.apply(pid)
        self.assertEqual(self.calls,0)
    def test_cancelled_approval_cannot_run(self):
        pid=self.plan();self.engine.approve(pid);self.engine.cancel(pid)
        with self.assertRaises(ValueError): self.engine.apply(pid)
    def test_duplicate_plan_rejected(self):
        self.plan()
        with self.assertRaises(ValueError): self.plan()
    def test_transport_timeout_consumes_approval(self):
        pid=self.plan();self.engine.approve(pid)
        with patch.object(self.adapter,'execute_repair',side_effect=RuntimeError('unknown outcome')) as call:
            result=self.engine.apply(pid)
        self.assertEqual(result['status'],'needs_attention')
        self.assertIn('unknown outcome',result['failure_reason'])
        self.assertEqual(call.call_count,1)
        with self.assertRaises(ValueError): self.engine.apply(pid)
    def test_concurrent_execution_dispatches_once(self):
        pid=self.plan();self.engine.approve(pid)
        def run(_):
            try: return self.engine.apply(pid)['status']
            except ValueError: return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,range(2)))
        self.assertEqual(sorted(results),['blocked','verified'])
        self.assertEqual(self.calls,1)
    def test_all_five_actions_have_distinct_preconditions_and_verification(self):
        for tool in ('docker','podman','kubernetes','github-actions','gitlab-ci'):
            with self.subTest(tool=tool):
                adapter=adapter_for(tool);snapshot=fixture_collect(adapter)
                self.assertTrue(adapter.repair_allowed(snapshot))
                self.assertFalse(adapter.verify(snapshot))
                self.assertTrue(adapter.repair_description())
    def test_unsupported_tools_cannot_execute_arbitrary_action(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=ToolEngine(adapter_for('aws'),directory)
            with self.assertRaises(ValueError): engine.plan('restart')


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.request_log=[]
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_GET(self):
                owner.request_log.append((self.path,self.headers.get('Authorization')))
                if self.path=='/redirect':
                    self.send_response(302);self.send_header('Location','/stolen');self.end_headers();return
                code=403 if self.path=='/forbidden' else 200
                body=b'x'*(LIMIT+1) if self.path=='/large' else b'{"database":"ok","version":"12"}'
                self.send_response(code);self.send_header('Content-Length',str(len(body)));self.end_headers()
                try: self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError): pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
        self.adapter=ToolAdapter('grafana',{'base_url':f'http://127.0.0.1:{self.server.server_port}'})
    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def test_real_loopback_http_request_and_projection(self):
        snapshot=self.adapter.collect()
        self.assertEqual(snapshot['observations']['database'],['ok'])
    def test_credential_binding_is_not_persisted(self):
        self.adapter=ToolAdapter('grafana',{'base_url':self.adapter.base_url,'headers':{'Authorization':{'env':'TRIAGE_FAKE_TOKEN','prefix':'Bearer '}}})
        with patch.dict(os.environ,{'TRIAGE_FAKE_TOKEN':'synthetic-credential'}):
            snapshot=self.adapter.collect()
        self.assertEqual(self.request_log[0][1],'Bearer synthetic-credential')
        self.assertNotIn('synthetic-credential',j(snapshot))
        self.assertNotIn('synthetic-credential',j(self.adapter.config))
    def test_redirect_never_forwards_credentials(self):
        with self.assertRaises(RuntimeError): self.adapter.request('/redirect')
        self.assertEqual([path for path,_ in self.request_log],['/redirect'])
    def test_http_permission_error_is_actionable(self):
        with self.assertRaisesRegex(RuntimeError,'permission denied'): self.adapter.request('/forbidden')
    def test_http_size_limit(self):
        with self.assertRaisesRegex(RuntimeError,'exceeded'): self.adapter.request('/large')
    def test_real_subprocess_streams_successfully(self):
        result,code=self.adapter.command([sys.executable,'-c',"print('ok')"])
        self.assertEqual((result.strip(),code),('ok',0))
    def test_subprocess_stderr_is_withheld(self):
        with self.assertRaises(RuntimeError) as error:
            self.adapter.command([sys.executable,'-c',"import sys;sys.stderr.write('private-value');sys.exit(3)"])
        self.assertNotIn('private-value',str(error.exception))
    def test_subprocess_size_limit(self):
        with self.assertRaisesRegex(RuntimeError,'exceeded'):
            self.adapter.command([sys.executable,'-c',f"print('x'*{LIMIT+1})"])


class AllRepairLifecycleTests(unittest.TestCase):
    def test_each_supported_action_requires_approval_and_verifies_its_state(self):
        for tool in ('docker','podman','kubernetes','github-actions','gitlab-ci'):
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as directory:
                adapter=adapter_for(tool)
                snapshot=fixture_collect(adapter)
                engine=ToolEngine(adapter,directory)
                def execute():
                    obs=snapshot['observations']
                    if tool in ('docker','podman'): obs['state']=['running']
                    elif tool=='kubernetes':
                        obs.update(available=[2],updated=[2],generation=[2],observed=[2])
                    else: obs['status']=['in_progress' if tool=='github-actions' else 'running']
                with patch.object(adapter,'collect',side_effect=lambda: json.loads(j(snapshot))), patch.object(adapter,'execute_repair',side_effect=execute) as action:
                    plan=engine.plan(adapter.profile['repair']['id'])
                    with self.assertRaises(ValueError): engine.apply(plan['id'])
                    action.assert_not_called()
                    engine.approve(plan['id'])
                    self.assertEqual(engine.apply(plan['id'])['status'],'verified')
                    action.assert_called_once()
                    with self.assertRaises(ValueError): engine.apply(plan['id'])


class WebToolTests(unittest.TestCase):
    def setUp(self):
        from triage.web import make_handler
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.adapter=adapter_for('docker');self.snapshot=fixture_collect(self.adapter)
        self.engine=ToolEngine(self.adapter,self.tmp.name)
        self.collect=patch.object(self.adapter,'collect',side_effect=lambda:json.loads(j(self.snapshot)))
        self.collect.start();self.addCleanup(self.collect.stop)
        self.action=patch.object(self.adapter,'execute_repair',side_effect=lambda:self.snapshot['observations'].update(state=['running']))
        self.execute=self.action.start();self.addCleanup(self.action.stop)
        def factory(tool):
            if tool!='docker':raise ValueError('No configured connection')
            return self.engine
        self.server=ThreadingHTTPServer(('127.0.0.1',0),BaseHTTPRequestHandler)
        self.server.RequestHandlerClass=make_handler(self.engine,'session',self.server.server_port,factory,{'docker':self.adapter.config})
        self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop)
    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,route,body):
        conn=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        conn.request('POST','/api/'+route,body=j(body),headers={'X-Triage-Token':'session','Content-Type':'application/json'})
        response=conn.getresponse();code=response.status;data=json.loads(response.read());conn.close();return code,data
    def test_tool_catalog_and_scoped_scan(self):
        code,data=self.request('tools',{})
        self.assertEqual(code,200);self.assertEqual(len(data['tools']),60)
        code,data=self.request('scan',{'tool':'docker','base_url':'https://attacker.invalid'})
        self.assertEqual(code,200);self.assertEqual(data['tool'],'docker')
        self.assertNotIn('attacker',j(data))
    def test_browser_cannot_select_unconfigured_connection(self):
        self.assertEqual(self.request('scan',{'tool':'aws'})[0],400)
        self.execute.assert_not_called()
    def test_browser_plan_review_approve_execute_replay(self):
        code,p=self.request('plan',{'tool':'docker','action':'restart'})
        self.assertEqual(code,200)
        body={'tool':'docker','id':p['id']}
        self.assertEqual(self.request('show',body)[1]['status'],'pending')
        self.assertEqual(self.request('apply',body)[0],400)
        self.assertEqual(self.request('approve',body)[0],200)
        self.assertEqual(self.request('apply',body)[1]['status'],'verified')
        self.assertEqual(self.request('apply',body)[0],400)
        self.execute.assert_called_once()
    def test_browser_cancel_blocks_execution(self):
        p=self.request('plan',{'tool':'docker','action':'restart'})[1]
        body={'tool':'docker','id':p['id']}
        self.assertEqual(self.request('cancel',body)[0],200)
        self.assertEqual(self.request('apply',body)[0],400)
        self.execute.assert_not_called()

class CredentialConfigTests(unittest.TestCase):
    def test_header_bindings_cannot_hide_literal_secret_values(self):
        with self.assertRaises(ValueError):
            ToolAdapter('grafana',{'base_url':'https://example.invalid','headers':{'Authorization':{'env':'TOKEN','value':'private-value'}}})
    def test_native_profiles_reject_unused_api_authentication(self):
        with self.assertRaises(ValueError):
            ToolAdapter('docker',{'context':'default','resource':'app','base_url':'https://user:password@example.invalid'})


if __name__=='__main__':
    unittest.main()
