"""Profiles, incident reporting/comparison, setup hints and CI policy behavior."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_experience
from test_triage import FakeLinux
from triage import ai, cli
from triage.benchmark import benchmark
from triage.connections import ConnectionWizard
from triage.engine import Engine
from triage.evidence import IncidentStore, annotate
from triage.experience import ExperienceEngine
from triage.operations import compare, escalation, setup_status, ci_exit_code
from triage.profiles import Profiles
from triage.web import make_handler


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'connections.json';self.path.write_text(json.dumps({'tools':{'docker':{'context':'dev','resource':'app'}},'notes':'keep'}))
        self.manager=Profiles(self.path)
    def test_copy_select_and_profile_wizard_preserve_other_environments(self):
        self.manager.create('prod','production');self.manager.select('prod');tools=self.manager.tools()
        wizard=ConnectionWizard(self.path,tools,'prod');wizard.save('docker',{'context':'production','resource':'app'})
        self.assertEqual(self.manager.tools('default')['docker']['context'],'dev')
        self.assertEqual(self.manager.tools()['docker']['context'],'production')
        self.assertEqual(self.manager.context()['environment'],'production')
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertEqual(json.loads(self.path.read_text())['notes'],'keep')
    def test_invalid_names_duplicates_and_environments(self):
        for name in ('../prod','default',None,'a'*41):
            with self.assertRaises(ValueError):self.manager.create(name,'production')
        with self.assertRaises(ValueError):self.manager.create('prod','not-real')
        self.manager.create('prod','production')
        with self.assertRaises(ValueError):self.manager.create('prod','production')
        with self.assertRaises(ValueError):self.manager.select('missing')
        with self.assertRaises(ValueError):self.manager.select(None)
        self.assertEqual(self.manager.current,'default')
    def test_identical_targets_in_different_profiles_cannot_share_approval(self):
        args=cli.parser().parse_args(['--state-dir',self.tmp.name,'diagnose'])
        args.profile_context={'profile':'dev','environment':'development'}
        with patch.object(cli,'Linux',return_value=FakeLinux()):dev=cli.make_engine(args,{})
        dev.scan();plan=dev.plan('example.service')
        args.profile_context={'profile':'prod','environment':'production'}
        with patch.object(cli,'Linux',return_value=FakeLinux()):prod=cli.make_engine(args,{})
        self.assertNotEqual(dev.adapter.target,prod.adapter.target)
        with self.assertRaises(ValueError):prod.approve(plan['id'])
        self.assertEqual(prod.adapter.calls,0)

    def test_named_profile_keeps_local_linux_transport_local(self):
        args=cli.parser().parse_args(['--state-dir',self.tmp.name,'diagnose'])
        args.profile_context={'profile':'staging','environment':'staging'}
        engine=cli.make_engine(args,{})
        report=engine.scan()
        self.assertEqual(engine.adapter._adapter.target,'local')
        self.assertIn(':profile:',engine.adapter.target)
        self.assertIn('disk_used_percent',report['snapshot'])
        self.assertEqual(report['setup_help']['configured_target'],'local')


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.adapter=FakeLinux();self.engine=ExperienceEngine(Engine(self.adapter,self.tmp.name))
    def test_scan_comparison_and_approved_repair_recheck(self):
        before=self.engine.scan();plan=self.engine.plan('example.service');self.engine.approve(plan['id'])
        result=self.engine.apply(plan['id']);self.assertEqual(result['status'],'verified')
        self.assertTrue(result['comparison']['resolved_codes'])
        self.assertIsNone(result['comparison']['after_health'])
        self.assertEqual(self.adapter.calls,1)
        _,latest=self.engine.store.latest(self.adapter.target)
        self.assertEqual(self.engine.store.handoff(latest['incident_id'],self.adapter.target)['attempted_repairs'][0]['status'],'verified')
        entries=self.engine.store.search(self.adapter.target,status='verified')['results']
        self.assertTrue(any(r['incident']==before['incident_id'] for r in entries))
        report=escalation(before,self.engine.store.timeline(before['incident_id']))
        self.assertEqual(report['attempted_repairs'][0]['status'],'verified')
        self.assertNotIn('example.service',json.dumps(report))
    def test_comparison_rejects_different_targets_and_tracks_incomplete_after(self):
        a=self.engine.scan();b=copy.deepcopy(a);b['target']='other'
        with self.assertRaises(ValueError):compare(a,b)
        b['target']=a['target'];b['snapshot']['errors']=['denied'];b['findings']=[]
        self.assertEqual(compare(a,b)['after_collection'],'incomplete')
    def test_incident_search_literal_query_and_target_isolation(self):
        report=self.engine.scan()
        self.assertTrue(self.engine.store.search(self.adapter.target,'service')['results'])
        self.assertEqual(self.engine.store.search('other')['results'],[])
        self.assertEqual(self.engine.store.search(self.adapter.target,"' OR 1=1 --")['results'],[])
        with self.assertRaises(ValueError):self.engine.store.get_scan(report['incident_id'],'other')
        with self.assertRaises(ValueError):self.engine.store.search(self.adapter.target,'x'*101)
    def test_ci_policy_incomplete_takes_precedence(self):
        report=annotate(self.engine.scan())
        self.assertEqual(ci_exit_code(report,'none'),0)
        self.assertEqual(ci_exit_code(report,'warning'),3)
        self.assertEqual(ci_exit_code(report,'any'),3)
        self.assertEqual(ci_exit_code(report,'critical'),3)
        report['findings'][0]['severity']='warning';self.assertEqual(ci_exit_code(report,'critical'),0)
        report['findings'][0]['severity']='critical';self.assertEqual(ci_exit_code(report,'critical'),3)
        report['deep_evidence']={'errors':['permission denied']};self.assertEqual(ci_exit_code(report,'any'),2)
    def test_setup_hints_are_scoped_and_identify_the_missing_cli(self):
        with patch('triage.operations.shutil.which',return_value=None):
            hints=setup_status('kubernetes',{'context':'dev'},['permission denied'])
        self.assertFalse(hints['ready_for_attempt']);text=json.dumps(hints)
        self.assertIn('kubectl',text);self.assertIn('namespace',text);self.assertIn('pods/log',text)
        self.assertNotIn('permission denied',text)  # raw errors are not copied into the hint report
    def test_cli_exit_code_and_bundle_path(self):
        for action,code in [(['diagnose','--fail-on','any'],3),(['diagnose'],0),(['bundle'],0)]:
            args=['devops-triage','--config',str(Path(self.tmp.name)/'none.json'),*action]
            with patch('sys.argv',args),patch.object(cli,'make_engine',return_value=self.engine),contextlib.redirect_stdout(io.StringIO()):
                if code:
                    with self.assertRaises(SystemExit) as exc:cli.main()
                    self.assertEqual(exc.exception.code,code)
                else:cli.main()


class BenchmarkTests(unittest.TestCase):
    def test_unavailable_model_does_not_claim_a_measurement(self):
        with patch.object(ai,'status',return_value={'available':False,'models':[]}):result=benchmark()
        self.assertEqual(result['status'],'unavailable');self.assertEqual(result['cases'],[])
        self.assertIsNone(result['peak_ollama_process_tree_rss_bytes'])
    def test_synthetic_benchmark_records_latency_and_manual_review(self):
        with patch.object(ai,'status',return_value={'available':True,'models':[ai.DEFAULT_MODEL]}),patch.object(ai,'explain',return_value={'status':'ok','explanation':'Memory may be exhausted. Verify evidence.'}),patch.object(ai,'_request',return_value={'models':[]}):
            result=benchmark(cases=1)
        self.assertEqual(result['status'],'completed');self.assertTrue(result['cases'][0]['topic_keyword_present'])
        self.assertTrue(result['cases'][0]['review_required']);self.assertIn('not answer-quality',result['scope'])

    def test_completed_benchmark_does_not_mark_rejected_answers_usable(self):
        with patch.object(ai,'status',return_value={'available':True,'models':[ai.DEFAULT_MODEL]}),patch.object(ai,'explain',return_value={'status':'unreliable','validation_flags':['unsupported_application_health_claim']}),patch.object(ai,'_request',return_value={'models':[]}):
            result=benchmark(cases=1)
        self.assertEqual(result['status'],'completed');self.assertEqual(result['accepted_explanations'],0)
        self.assertEqual(result['quality_gate'],'known_contradictions_detected')


class OperationAPITests(unittest.TestCase):
    setUp=test_experience.FeatureAPITests.setUp
    stop=test_experience.FeatureAPITests.stop
    request=test_experience.FeatureAPITests.request
    def test_bundle_recheck_handoff_and_search_are_bound_to_target(self):
        code,report=self.request('bundle',{'tool':'linux'});self.assertEqual(code,200);self.assertIn('handoff',report)
        code,after=self.request('recheck',{'incident':report['incident_id']});self.assertEqual(code,200);self.assertIn('comparison',after)
        self.assertEqual(self.request('recheck',{'incident':'invalid'})[0],400)
        self.assertEqual(self.request('handoff',{'incident':report['incident_id']})[0],200)
        code,result=self.request('incidents',{});self.assertEqual(code,200);self.assertEqual(len(result['results']),2)
        self.assertEqual(self.root.history(),[])
    def test_doctor_handles_unconfigured_tools_without_factory(self):
        code,result=self.request('doctor',{'tool':'kubernetes'});self.assertEqual(code,200);self.assertFalse(result['ready_for_attempt'])
        self.assertEqual(self.request('doctor',{'tool':'kubernetes'},'wrong')[0],403)
    def test_profile_api_switch_blocks_active_plans(self):
        manager=Profiles(self.wizard.path);manager.create('prod','production')
        def selected(name):manager.select(name);return manager.listing()
        self.server.RequestHandlerClass=make_handler(self.root,'session',self.server.server_port,None,self.configs,self.wizard,manager,selected)
        code,result=self.request('profiles/select',{'name':'prod'});self.assertEqual(code,200);self.assertEqual(result['current'],'prod')
        self.root.scan();plan=self.root.plan('example.service')
        self.assertEqual(self.request('profiles/select',{'name':'default'})[0],400)
        self.root.cancel(plan['id']);self.assertEqual(self.request('profiles/select',{'name':'default'})[0],200)
    def test_demo_blocks_new_live_routes(self):
        for route in ('bundle','recheck','handoff','incidents','profiles/select','benchmark','doctor'):
            self.assertEqual(self.request(route,{'demo':True})[0],400)
