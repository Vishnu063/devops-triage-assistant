import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from triage.ecosystem import envelope,validate,diagnose,verify,emit,schema,k8sgpt

class EcosystemTests(unittest.TestCase):
 def event(self):return envelope('MonitoringAlert','prometheus','demo',dict(fingerprint='fixed',status='firing',alertname='AppDown'),correlation_id='release-1')
 def test_all_ten_contracts_and_unknown_fields(self):
  self.assertEqual(10,len(schema()['oneOf']));e=self.event();validate(e)
  for key,value in [('schema_version','2'),('timestamp','2026-01-01'),('data',{'command':'rm -rf /'})]:
   bad={**e,key:value}
   with self.assertRaises(ValueError):validate(bad)
  with self.assertRaises(ValueError):validate({**e,'execute':True})
 def test_secrets_nonfinite_and_unknown_checks_fail_closed(self):
  e=self.event();e['data']['token']='private'
  with self.assertRaises(ValueError):validate(e)
  e=self.event();e['data']['value']=float('nan')
  with self.assertRaises(ValueError):validate(e)
  with self.assertRaises(ValueError):verify({'container':'true'})
 def test_existing_evidence_explanations_and_no_model_required(self):
  d=diagnose(self.event(),{'findings':[dict(likely_cause='Observed OOM, cause unproven')], 'deep_evidence':{'log_signals':{'memory':1}}})
  self.assertEqual(self.event()['service'],d['service']);self.assertTrue(d['data']['evidence_refs'])
  self.assertTrue(all(c['access']=='read-only' and c['why'] and c['problem_output'] for c in d['data']['commands']))
  self.assertFalse(k8sgpt('unused','unused')['executable'])
 def test_verification_does_not_accept_missing_or_failed_evidence(self):
  self.assertEqual('inconclusive',verify({})['status'])
  self.assertEqual('inconclusive',verify({'container':True,'prometheus':None})['status'])
  self.assertEqual('failed',verify({'container':True,'rollout':False})['status'])
  self.assertEqual('verified',verify({'container':True,'rollout':True})['status'])
 def test_failed_delivery_preserves_private_stable_event_outbox(self):
  event=self.event()
  with tempfile.TemporaryDirectory() as root,patch('triage.ecosystem.transport',side_effect=ValueError('offline')):
   with self.assertRaises(ValueError):emit(event,'http://127.0.0.1:8767/webhooks/ecosystem','t'*40,root)
   file=next(Path(root).glob('*.json'));self.assertEqual(event,json.loads(file.read_text()));self.assertEqual(0o600,file.stat().st_mode&0o777)
