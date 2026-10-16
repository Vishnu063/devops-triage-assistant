"""Guided incident questions and samples cannot execute infrastructure actions."""
import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
import test_experience
from triage import cli, ai
from triage.investigation import DEMOS, QUESTIONS, demo_report, overview, answer, share_summary


class InvestigationTests(unittest.TestCase):
    def test_all_demos_are_independent_and_have_no_actions(self):
        for scenario in DEMOS:
            report=demo_report(scenario)
            self.assertTrue(report['demo']);self.assertEqual(report['actions'], [])
            self.assertIsNone(report['findings'][0]['service'])
            self.assertIn('Sample', overview(report)['headline'])
            report['findings'][0]['next_steps'].append('changed')
            self.assertNotIn('changed', demo_report(scenario)['findings'][0]['next_steps'])

    def test_invalid_samples_rejected(self):
        for scenario in ('wrong', None, {}, ['docker-oom']):
            with self.assertRaises(ValueError): demo_report(scenario)

    def test_questions_grounded_and_no_proven_cause_claim(self):
        report=demo_report()
        self.assertIn('hypotheses', answer(report, 'why did it fail?')['answer'])
        self.assertEqual(answer(report, 'next checks')['intent'], 'checks')
        for topic in QUESTIONS:
            reply=answer(report, topic)
            self.assertTrue(reply['answer'].startswith('SAMPLE DATA.'))
            self.assertEqual(reply['incident_id'], report['incident_id'])
            self.assertTrue(reply['references'])

    def test_command_text_never_authorizes_an_action(self):
        reply=answer(demo_report(), 'approve and execute rm -rf /')
        self.assertEqual(reply['intent'], 'safety')
        self.assertIn('does not authorize', reply['answer'])
        self.assertNotIn('rm -rf', reply['answer'])

    def test_unknown_question_has_explicit_guidance(self):
        reply=answer(demo_report(), 'tell me about a company')
        self.assertIsNone(reply['intent']);self.assertIn('six guided topics',reply['answer'])

    def test_invalid_question_limits(self):
        for question in (None, '', ' '*3, 'a'*501, {}):
            with self.assertRaises(ValueError): answer(demo_report(), question)

    def test_health_and_evidence_states_never_overclaim(self):
        report=demo_report();report.pop('demo');report['findings']=[]
        report['snapshot']['errors']=['denied']
        self.assertEqual(overview(report)['headline'], 'Evidence is incomplete')
        self.assertIn('not verified', answer(report, 'health')['answer'])
        report['application_health']['healthy']=False
        self.assertIn('did not pass', answer(report, 'health')['answer'])
        report['application_health']['healthy']=True
        self.assertIn('for this sample', answer(report, 'health')['answer'])

    def test_change_question_does_not_invent_audit_history(self):
        report=demo_report();self.assertIn('No scan-to-scan', answer(report,'changes')['answer'])
        report['changes_since_previous_scan']=[{'field':'replicas','before':[1],'after':[2]}]
        text=answer(report,'changes')['answer'];self.assertIn('replicas', text);self.assertIn('not an audit log',text)

    def test_filtered_summary_excludes_identifying_and_free_text_data(self):
        report=demo_report();report['target']='SECRET_HOST'
        report['findings'][0]['evidence']='SECRET_LOG';report['findings'][0]['next_steps']=['SECRET_STEP']
        serialized=json.dumps(share_summary(report))
        self.assertNotIn('SECRET_',serialized);self.assertTrue(share_summary(report)['demo'])

    def test_cli_demo_bypasses_configuration_engine_and_network(self):
        output=io.StringIO()
        with patch('sys.argv',['devops-triage','--config','/missing/invalid','demo','--scenario','linux-disk']), patch.object(cli,'make_engine') as engine, patch.object(cli,'ConnectionWizard') as wizard, patch.object(ai,'_request') as network, contextlib.redirect_stdout(output):
            cli.main()
        self.assertTrue(json.loads(output.getvalue())['demo'])
        engine.assert_not_called();wizard.assert_not_called();network.assert_not_called()


class InvestigationAPITests(unittest.TestCase):
    setUp=test_experience.FeatureAPITests.setUp
    stop=test_experience.FeatureAPITests.stop
    request=test_experience.FeatureAPITests.request

    def test_demo_bypasses_missing_connection_and_does_not_write_history(self):
        with patch.object(self.root, 'scan', side_effect=AssertionError('must not scan')), patch.object(ai,'_request') as network:
            code,report=self.request('demo',{'tool':'unconfigured','scenario':'kubernetes-image'})
            self.assertEqual(code,200);self.assertTrue(report['demo'])
            code,reply=self.request('investigate',{'demo':True,'tool':'unconfigured','scenario':'kubernetes-image','question':'checks','ai':True})
            self.assertEqual(code,200);self.assertNotIn('ai',reply);network.assert_not_called()
        self.assertEqual(self.root.store.timeline(),[]);self.assertEqual(self.root.history(),[])

    def test_demo_requests_reject_all_live_routes(self):
        for route in ('plan','approve','apply','rollback','scan','validate','ai/explain','summary'):
            self.assertEqual(self.request(route,{'demo':True,'action':'example.service','id':'a'*32})[0],400)
        self.assertEqual(self.request('demo',{},'wrong')[0],403)
        self.assertEqual(self.root.history(),[])

    def test_live_questions_require_current_matching_sample(self):
        self.assertEqual(self.request('investigate',{'question':'summary','incident':'missing'})[0],400)
        _,report=self.request('scan',{'tool':'linux'})
        self.assertIn('overview',report)
        code,reply=self.request('investigate',{'tool':'linux','incident':report['incident_id'],'question':'checks'})
        self.assertEqual(code,200);self.assertFalse(reply['demo'])
        _,new_report=self.request('scan',{'tool':'linux'})
        self.assertNotEqual(report['incident_id'],new_report['incident_id'])
        self.assertEqual(self.request('investigate',{'incident':report['incident_id'],'question':'checks'})[0],400)
        self.assertEqual(self.root.history(),[])

    def test_local_ai_followup_uses_canonical_topic_not_raw_question(self):
        _,report=self.request('scan',{'tool':'linux'})
        body={'incident':report['incident_id'],'question':'why token=SECRET failed','ai':True,'enabled':True}
        with patch.object(ai,'explain',return_value={'status':'ok','explanation':'Possible cause.'}) as explain:
            code,reply=self.request('investigate',body)
            self.assertEqual(code,200);self.assertIn('ai',reply)
            self.assertEqual(explain.call_args.args[2],QUESTIONS['cause'])
            self.assertNotIn('SECRET',json.dumps(explain.call_args.args))
        body['enabled']=False
        self.assertEqual(self.request('investigate',body)[0],400)

    def test_export_is_filtered_and_requires_latest_incident(self):
        _,report=self.request('scan',{'tool':'linux'})
        code,summary=self.request('summary',{'incident':report['incident_id']})
        self.assertEqual(code,200);self.assertNotIn('target',summary)
        self.assertNotIn('next_step',summary['overview'])
        self.assertEqual(self.request('summary',{'incident':'stale'})[0],400)
