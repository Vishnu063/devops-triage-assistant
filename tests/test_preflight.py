"""Offline preflight behavior, policy and disclosure boundaries."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from triage.preflight import load, review, exit_code, matches, amount

ROOT = Path(__file__).resolve().parents[1]


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.dep = json.loads((ROOT/'examples/preflight-deployment.json').read_text())
        self.pod = self.dep['spec']['template']['spec']
        self.pod['containers'][0]['image'] = 'example/web@sha256:' + 'a'*64

    def codes(self, report):
        return {f['code'] for f in report['findings']}

    def test_clean_scope_still_explains_unverified_live_checks(self):
        r = review([self.dep])
        self.assertEqual(r['status'], 'reviewed')
        self.assertEqual(r['findings'], [])
        self.assertEqual(exit_code(r), 0)
        self.assertEqual(r['unverified'][0]['code'], 'live-checks-required')

    def test_images_probes_requests_and_rollout(self):
        c = self.pod['containers'][0]
        c['image'] = '${PRIVATE_IMAGE}'
        del c['readinessProbe']; del c['resources']
        self.dep['spec']['strategy'] = {'type': 'Recreate'}
        r = review([self.dep])
        self.assertTrue({'invalid-image','readiness-missing','requests-missing','recreate'} <= self.codes(r))
        self.assertEqual(exit_code(r), 3)
        self.assertEqual(exit_code(r, 'none'), 0)

    def test_selector_mismatch_and_budget_rounding(self):
        self.dep['spec']['selector']['matchLabels']['app'] = 'different'
        rolling = self.dep['spec']['strategy']['rollingUpdate']
        rolling.update(maxUnavailable=0, maxSurge=0)
        r = review([self.dep])
        self.assertTrue({'selector-mismatch', 'rollout-blocked'} <= self.codes(r))
        self.assertEqual(amount('25%', 3), 0)
        self.assertEqual(amount('25%', 3, True), 1)
        self.assertTrue(matches({'matchExpressions':[{'key':'env','operator':'NotIn','values':['prod']}]}, {}))
        self.assertFalse(matches({'matchExpressions':[{'key':'app','operator':'Exists'}]}, {}))

    def test_references_namespace_and_no_secret_content(self):
        self.pod['containers'][0]['envFrom'] = [{'secretRef': {'name': 'credentials'}}]
        secret = {'kind':'Secret','metadata':{'name':'credentials','namespace':'elsewhere'},'data':{'password':'SENSITIVE'}}
        self.assertIn('external-configuration', {x['code'] for x in review([self.dep, secret])['unverified']})
        secret['metadata']['namespace'] = 'default'
        r = review([self.dep, secret])
        self.assertNotIn('external-configuration', {x['code'] for x in r['unverified']})
        self.assertNotIn('SENSITIVE', json.dumps(r)); self.assertNotIn('credentials', json.dumps(r))
        self.assertIn('keys and values', json.dumps(r))

    def test_optional_reference_and_service_scope(self):
        self.pod['imagePullSecrets'] = []
        self.pod['containers'][0]['envFrom'] = [{'configMapRef': {'name':'optional', 'optional':True}}]
        service = {'kind':'Service','metadata':{'namespace':'default'},'spec':{'selector':{'app':'other'}}}
        r = review([self.dep, service])
        self.assertIn('service-selector-mismatch', self.codes(r))
        self.assertNotIn('external-configuration', {x['code'] for x in r['unverified']})
        self.assertEqual(exit_code(r), 0); self.assertEqual(exit_code(r, 'warning'), 3)
        service['metadata']['namespace'] = 'different'
        self.assertNotIn('service-selector-mismatch', self.codes(review([self.dep, service])))

    def test_invalid_structures_never_pass_or_disclose(self):
        variants = [None, [], 'SENSITIVE', {'containers': []}, {'containers': [{'name':'x', 'resources':None}]}]
        for variant in variants:
            dep = copy.deepcopy(self.dep); dep['spec']['template']['spec'] = variant
            r = review([dep])
            self.assertEqual(exit_code(r, 'none'), 2)
            self.assertNotIn('SENSITIVE', json.dumps(r))
        self.dep['spec']['replicas'] = True
        self.assertEqual(exit_code(review([self.dep])), 2)

    def test_input_boundaries_and_cli_independent_of_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'input.json'
            path.write_text(json.dumps({'apiVersion':'v1','kind':'List','items':[self.dep]}))
            self.assertEqual(len(load(path)), 1)
            p = subprocess.run([sys.executable,'-m','triage.cli','--config',str(Path(tmp)/'does-not-exist'),'preflight',str(path)],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)['status'], 'reviewed')
            path.write_text('x'*(1024*1024+1))
            with self.assertRaisesRegex(ValueError,'1 MiB'): load(path)
            path.write_text('kind: Deployment')
            with self.assertRaisesRegex(ValueError,'JSON'): load(path)
            path.write_text('{"kind":"List","items":[]}')
            with self.assertRaises(ValueError): load(path)

    def test_missing_deployment_and_unsupported_version(self):
        with self.assertRaises(ValueError): review([{'kind':'Job'}])
        self.dep['apiVersion'] = 'extensions/v1beta1'
        self.assertEqual(exit_code(review([self.dep])), 2)


if __name__ == '__main__': unittest.main()
