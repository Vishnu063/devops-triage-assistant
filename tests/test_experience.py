"""Recovery experience tests using disposable local endpoints and simulated resources."""
import copy
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from triage.connections import ConnectionWizard
from triage.engine import Engine
from triage.evidence import IncidentStore, annotate, correlate, deep_evidence, log_signals
from triage.experience import ExperienceEngine
from triage.health import check_health, validate_health
from triage.integrations import ToolAdapter
from triage.tool_engine import ToolEngine
from triage.web import make_handler
from test_integrations import adapter_for, fixture_collect, FIXTURES
from test_triage import FakeLinux


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.sequence=[200,200];self.seen=[];owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):
                owner.seen.append(self.path)
                status=owner.sequence.pop(0) if owner.sequence else 200
                self.send_response(status)
                if status==302:self.send_header('Location','/stolen')
                body=json.dumps({'status':'ok','password':'private-value'}).encode()
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop)
        self.config={'url':f'http://127.0.0.1:{self.server.server_port}/health','interval':0}
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def test_consecutive_successes(self):
        result=check_health(self.config)
        self.assertTrue(result['healthy']);self.assertEqual(len(result['samples']),2)
        self.assertNotIn('private-value',json.dumps(result))
    def test_intermittent_success_is_not_stable_health(self):
        self.sequence=[200,503,200]
        self.assertFalse(check_health(self.config)['healthy'])
    def test_json_condition(self):
        self.assertTrue(check_health({**self.config,'json_path':'status','equals':'ok'})['healthy'])
    def test_json_condition_failure(self):
        self.assertFalse(check_health({**self.config,'json_path':'status','equals':'wrong'})['healthy'])
    def test_redirect_not_followed_or_treated_healthy(self):
        self.sequence=[302]
        self.assertFalse(check_health({**self.config,'expected_status':[302],'attempts':1,'successes':1})['healthy'])
        self.assertEqual(self.seen,['/health'])
    def test_missing_health_is_explicit(self):self.assertIsNone(check_health(None)['healthy'])
    def test_policy_bounds_and_secret_headers(self):
        for change in ({'attempts':100},{'successes':4},{'timeout':60},{'expected_status':[True]}, {'headers':{'Authorization':{'value':'private-value'}}}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_health({**self.config,**change})
    def test_provider_credentials_are_not_forwarded_to_health(self):
        config={**self.config,'headers':{'Authorization':{'env':'MISSING_HEALTH_TOKEN','prefix':'Bearer '}}}
        with patch.dict(os.environ,{},clear=True):result=check_health(config)
        self.assertFalse(result['healthy']);self.assertEqual(self.seen,[])


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'connections.json';self.configs={};self.wizard=ConnectionWizard(self.path,self.configs)
    def test_save_private_and_update_runtime(self):
        result=self.wizard.save('docker',{'context':'default','resource':'app'})
        self.assertTrue(result['saved']);self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertEqual(self.configs['docker']['resource'],'app')
        self.assertEqual(result['write_access'],'not_tested')
    def test_preserve_other_tools_and_top_level_fields(self):
        self.path.write_text(json.dumps({'tools':{'grafana':{'base_url':'https://example.invalid'}},'notes':'keep'}))
        self.wizard.save('docker',{'context':'default','resource':'app'})
        saved=json.loads(self.path.read_text());self.assertIn('grafana',saved['tools']);self.assertEqual(saved['notes'],'keep')
    def test_invalid_config_does_not_replace_file(self):
        self.path.write_text('{"tools":{}}');original=self.path.read_text()
        with self.assertRaises(ValueError):self.wizard.save('docker',{'context':'default','resource':'app','password':'private-value'})
        self.assertEqual(self.path.read_text(),original);self.assertEqual(self.configs,{})
    def test_schema_describes_requirements_without_connecting(self):
        with patch.object(ToolAdapter,'collect',side_effect=AssertionError('no connection')):
            schema=self.wizard.schema('docker')
        self.assertEqual(set(schema['required']),{'context','resource'})
    def test_health_policy_is_validated_before_save(self):
        with self.assertRaises(ValueError):self.wizard.save('docker',{'context':'default','resource':'app','application_health':{'url':'http://public.example'}})
        self.assertFalse(self.path.exists())
    def test_mongodb_can_be_configured_before_credentials_are_loaded(self):
        with patch.dict(os.environ,{},clear=True):result=self.wizard.save('mongodb',{})
        self.assertTrue(result['saved'])
        with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(RuntimeError,'TRIAGE_MONGODB_URI'):ToolAdapter('mongodb',{}).collect()


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.engine=Engine(FakeLinux(),self.tmp.name);self.store=IncidentStore(self.engine)
    def report(self,target='docker:test',state='exited'):
        return {'target':target,'snapshot':{'observations':{'state':[state]}},'findings':[], 'coverage':'test'}
    def test_sample_changes_are_recorded_as_context(self):
        first=self.store.scan(self.report());second=self.store.scan(self.report(state='running'))
        self.assertEqual(first['changes_since_previous_scan'],[])
        self.assertEqual(second['changes_since_previous_scan'][0]['field'],'state')
        self.assertTrue(self.store.timeline(second['incident_id']))
    def test_alert_deduplication_and_acknowledgement(self):
        self.store.alert('i','warning','needs attention','target');self.store.alert('i','warning','needs attention','target')
        alerts=self.store.alerts();self.assertEqual(len(alerts),1)
        self.assertEqual(self.store.alerts(alerts[0]['id'])[0]['acknowledged'],1)
    def test_unknown_alert_rejected(self):
        with self.assertRaises(ValueError):self.store.alerts('missing')
    def test_confidence_distinguishes_observation_and_cause(self):
        report=self.report();report['findings']=[{'code':'docker:state'}]
        confidence=annotate(report)['findings'][0]['confidence']
        self.assertEqual(confidence['observation'],'confirmed');self.assertEqual(confidence['cause'],'possible')
    def test_collection_failure_does_not_claim_observed_cause(self):
        report=self.report();report['findings']=[{'code':'collection-failed'}]
        self.assertEqual(annotate(report)['findings'][0]['confidence']['observation'],'insufficient_evidence')
    def test_log_signature_extraction_retains_no_lines(self):
        signals=log_signals('private-value: connection refused\nOOMKilled\npermission denied\n')
        self.assertEqual(signals['memory'],1);self.assertNotIn('private-value',json.dumps(signals))
    def test_unsupported_deep_collection_is_explicit(self):self.assertFalse(deep_evidence(adapter_for('aws'))['supported'])
    def test_container_deep_collection_includes_stderr_signals(self):
        adapter=adapter_for('docker')
        with patch.object(adapter,'command',return_value=('private-value: connection refused',0)) as command:
            result=deep_evidence(adapter)
        self.assertEqual(result['log_signals'],{'dependency':1});self.assertNotIn('private-value',json.dumps(result))
        self.assertTrue(command.call_args.kwargs['include_stderr'])
    def test_correlated_memory_is_not_presented_as_topology_proof(self):
        reports=[]
        for target,code in [('a','docker:oom'),('b','memory-pressure')]:
            report=self.report(target);report['findings']=[{'code':code}];reports.append(self.store.scan(report))
        result=correlate(reports,self.store)
        self.assertEqual(result['hypotheses'][0]['confidence'],'corroborated')
        self.assertIn('topology',result['hypotheses'][0]['limitation'])
    def test_correlation_has_a_bound(self):
        with self.assertRaises(ValueError):correlate([self.report()]*5,self.store)


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.adapter=adapter_for('docker');self.snapshot=fixture_collect(self.adapter)
        self.adapter.last_snapshot=self.snapshot
        self.core=ToolEngine(self.adapter,self.tmp.name);self.experience=ExperienceEngine(self.core)
        def collect():self.adapter.last_snapshot=copy.deepcopy(self.snapshot);return copy.deepcopy(self.snapshot)
        self.collection=patch.object(self.adapter,'collect',side_effect=collect);self.collection.start();self.addCleanup(self.collection.stop)
    def test_scan_records_confidence_and_timeline(self):
        report=self.experience.scan();self.assertIn('confidence',report['findings'][0])
        self.assertTrue(self.experience.store.timeline(report['incident_id']))
    def test_connection_check_does_not_claim_write_privileges(self):
        result=self.experience.validate_connection()
        self.assertEqual(result['read_access'],'verified_for_collector_scope');self.assertIn('not_tested',result['write_access'])
    def test_preview_is_not_a_provider_dry_run(self):
        plan=self.experience.plan('restart');self.assertFalse(plan['preview']['dry_run'])
        self.assertEqual(plan['preview']['operation'],plan['command'])
    def test_changed_health_policy_blocks_approval(self):
        plan=self.experience.plan('restart');other=ExperienceEngine(self.core,{'url':'http://127.0.0.1:9999/health'})
        with self.assertRaises(ValueError):other.approve(plan['id'])
    def test_failed_app_probe_downgrades_infrastructure_success(self):
        experience=ExperienceEngine(self.core,{'url':'http://127.0.0.1:9999/health'})
        plan=experience.plan('restart');experience.approve(plan['id'])
        with patch.object(self.adapter,'execute_repair',side_effect=lambda:self.snapshot['observations'].update(state=['running'])),patch('triage.experience.check_health',return_value={'configured':True,'healthy':False,'samples':[]}):
            result=experience.apply(plan['id'])
        self.assertEqual(result['infrastructure_status'],'verified');self.assertEqual(result['status'],'needs_attention')
        self.assertEqual(self.core.show(plan['id'])['status'],'needs_attention')
        self.assertEqual(experience.store.alerts()[0]['severity'],'warning')
    def test_unapproved_action_still_cannot_dispatch(self):
        plan=self.experience.plan('restart')
        with patch.object(self.adapter,'execute_repair') as action,self.assertRaises(ValueError):self.experience.apply(plan['id'])
        action.assert_not_called()
    def test_unsupported_rollback_has_no_fallback_shell(self):
        plan=self.experience.plan('restart')
        with self.assertRaises(ValueError):self.experience.rollback_plan(plan['id'])


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.adapter=adapter_for('kubernetes');self.resource=json.loads(FIXTURES['kubernetes'][0])
        self.resource['metadata']['annotations']={'deployment.kubernetes.io/revision':'1'}
        self.original=copy.deepcopy(self.resource['spec']['template']);self.repairs=0;self.undos=0
        def command(argv,repair=False,include_stderr=False):
            if repair and 'restart' in argv:
                self.repairs+=1;self.resource['metadata'].update(generation=2,resourceVersion='2')
                self.resource['metadata'].setdefault('annotations',{})['deployment.kubernetes.io/revision']='2'
                self.resource['spec']['template'].setdefault('metadata',{})['annotations']={'restartedAt':'new'}
                self.resource['status'].update(availableReplicas=0,observedGeneration=2)
            elif repair and 'undo' in argv:
                self.undos+=1;self.resource['spec']['template']=copy.deepcopy(self.original)
                self.resource['metadata'].update(generation=3,resourceVersion='3')
                self.resource['metadata']['annotations']['deployment.kubernetes.io/revision']='3'
                self.resource['status'].update(availableReplicas=2,observedGeneration=3)
            return json.dumps(self.resource),0
        self.commands=patch.object(self.adapter,'command',side_effect=command);self.commands.start();self.addCleanup(self.commands.stop)
        self.sleep=patch('triage.tool_engine.time.sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
        self.experience=ExperienceEngine(ToolEngine(self.adapter,self.tmp.name))
    def failed_recovery(self):
        plan=self.experience.plan('rollout-restart');self.experience.approve(plan['id'])
        result=self.experience.apply(plan['id']);self.assertTrue(result['rollback_available']);return plan
    def test_separate_review_approval_and_verification(self):
        parent=self.failed_recovery();rollback=self.experience.rollback_plan(parent['id'])
        self.assertIn('--to-revision=1',rollback['command'])
        with self.assertRaises(ValueError):self.experience.apply(rollback['id'])
        self.assertEqual(self.undos,0)
        self.experience.approve(rollback['id'])
        self.assertEqual(self.experience.apply(rollback['id'])['status'],'verified')
        self.assertEqual(self.undos,1)
        with self.assertRaises(ValueError):self.experience.apply(rollback['id'])
    def test_unrelated_generation_change_blocks_rollback_planning(self):
        parent=self.failed_recovery();self.resource['metadata']['generation']=4
        with self.assertRaises(ValueError):self.experience.rollback_plan(parent['id'])
        self.assertEqual(self.undos,0)
    def test_evidence_drift_after_approval_blocks_execution(self):
        parent=self.failed_recovery();rollback=self.experience.rollback_plan(parent['id']);self.experience.approve(rollback['id'])
        self.resource['metadata']['resourceVersion']='changed'
        with self.assertRaises(ValueError):self.experience.apply(rollback['id'])
        self.assertEqual(self.undos,0)
    def test_missing_retained_source_disables_rollback(self):
        del self.resource['metadata']['annotations']
        plan=self.experience.plan('rollout-restart');self.experience.approve(plan['id'])
        result=self.experience.apply(plan['id']);self.assertFalse(result['rollback_available'])
    def test_successful_parent_cannot_be_rolled_back_by_failure_workflow(self):
        plan=self.experience.plan('rollout-restart')
        with self.assertRaises(ValueError):self.experience.rollback_plan(plan['id'])


class FeatureAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.configs={};self.wizard=ConnectionWizard(Path(self.tmp.name)/'connections.json',self.configs)
        self.root=ExperienceEngine(Engine(FakeLinux(),self.tmp.name))
        self.adapter=adapter_for('docker');self.snapshot=fixture_collect(self.adapter)
        def factory(tool):
            if tool=='linux':return self.root
            if tool not in self.configs:raise ValueError('No configured connection')
            adapter=ToolAdapter(tool,self.configs[tool]);adapter.last_snapshot=copy.deepcopy(self.snapshot)
            adapter.collect=lambda:copy.deepcopy(self.snapshot)
            return ExperienceEngine(ToolEngine(adapter,self.tmp.name),self.configs[tool].get('application_health'))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),BaseHTTPRequestHandler)
        self.server.RequestHandlerClass=make_handler(self.root,'session',self.server.server_port,factory,self.configs,self.wizard)
        self.server.daemon_threads=True;self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,route,body,token='session'):
        conn=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        conn.request('POST','/api/'+route,body=json.dumps(body),headers={'X-Triage-Token':token,'Content-Type':'application/json'})
        response=conn.getresponse();data=json.loads(response.read());status=response.status;conn.close();return status,data
    def test_wizard_save_then_validate_without_mutation(self):
        code,schema=self.request('connection/schema',{'tool':'docker'});self.assertEqual(code,200)
        self.assertIn('context',schema['required'])
        code,result=self.request('connection/save',{'tool':'docker','config':{'context':'default','resource':'app'}})
        self.assertEqual(code,200);self.assertTrue(result['saved'])
        code,result=self.request('validate',{'tool':'docker'})
        self.assertEqual(code,200);self.assertEqual(result['read_access'],'verified_for_collector_scope')
        self.assertIn('not_tested',result['write_access'])
    def test_wizard_rejects_missing_session_and_literal_credentials(self):
        body={'tool':'docker','config':{'context':'default','resource':'app'}}
        self.assertEqual(self.request('connection/save',body,'wrong')[0],403)
        body['config']['password']='private-value'
        self.assertEqual(self.request('connection/save',body)[0],400)
        self.assertEqual(self.configs,{})
    def test_scan_timeline_alert_and_acknowledgement(self):
        code,report=self.request('scan',{'tool':'linux'});self.assertEqual(code,200)
        code,events=self.request('timeline',{'tool':'linux','incident':report['incident_id']})
        self.assertEqual(code,200);self.assertEqual(events[0]['kind'],'scan')
        code,alerts=self.request('alerts',{'tool':'linux'});self.assertEqual(code,200)
        self.assertTrue(alerts)
        code,alerts=self.request('alerts',{'tool':'linux','acknowledge':alerts[0]['id']})
        self.assertEqual(code,200);self.assertEqual(alerts[0]['acknowledged'],1)
    def test_correlation_rejects_unbounded_or_duplicate_selections(self):
        self.assertEqual(self.request('correlate',{'tool':'linux','tools':['linux','linux']})[0],400)
        self.assertEqual(self.request('correlate',{'tool':'linux','tools':['linux']})[0],200)


class PermissionReviewTests(unittest.TestCase):
    def test_kubernetes_write_review_is_non_mutating(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter=adapter_for('kubernetes');snapshot=fixture_collect(adapter)
            experience=ExperienceEngine(ToolEngine(adapter,directory))
            with patch.object(adapter,'collect',return_value=snapshot),patch.object(adapter,'command',return_value=('yes\n',0)) as command:
                result=experience.validate_connection()
            self.assertIn('allowed_by_authorization_review',result['write_access'])
            self.assertIn('can-i',command.call_args.args[0]);self.assertNotIn('repair',command.call_args.kwargs)
    def test_failed_write_review_does_not_infer_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter=adapter_for('kubernetes');snapshot=fixture_collect(adapter)
            experience=ExperienceEngine(ToolEngine(adapter,directory))
            with patch.object(adapter,'collect',return_value=snapshot),patch.object(adapter,'command',side_effect=RuntimeError('denied')):
                result=experience.validate_connection()
            self.assertTrue(result['write_access'].startswith('not_verified'))


class SetupCLITests(unittest.TestCase):
    def test_setup_can_create_an_explicit_new_config_file(self):
        import io
        from triage.cli import main
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'new-connections.json'
            with patch('sys.argv',['devops-triage','--config',str(path),'--tool','docker','setup']),patch('builtins.input',side_effect=['default','app','']),patch('sys.stdout',new=io.StringIO()):
                main()
            self.assertEqual(json.loads(path.read_text())['tools']['docker']['resource'],'app')
            self.assertEqual(path.stat().st_mode&0o777,0o600)


if __name__=='__main__':unittest.main()
