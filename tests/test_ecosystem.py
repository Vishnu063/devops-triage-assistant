import unittest
from triage.ecosystem import diagnosis, k8sgpt
from triage.integrations import ToolAdapter


class EcosystemTests(unittest.TestCase):
    def test_existing_findings_keep_evidence_and_uncertainty_without_ai(self):
        result = diagnosis({'incident_id': 'incident-1', 'findings': [{'title': 'Stopped', 'evidence': 'token=private', 'likely_cause': 'Unknown'}]})
        self.assertEqual(['findings/0'], result['hypotheses'][0]['evidence_refs'])
        self.assertNotIn('private', str(result))
        self.assertFalse(result['ai_enabled'])
        self.assertEqual([], result['suggested_commands'])
        with self.assertRaises(ValueError): diagnosis({'findings': []})

    def test_optional_k8sgpt_is_bounded_read_only_and_never_explains_with_ai(self):
        adapter = ToolAdapter('kubernetes', {'context': 'lab', 'namespace': 'disposable', 'resource': 'demo'})
        calls = []
        def command(recipe):
            calls.append(recipe)
            return '{"results":[{"kind":"Pod","name":"demo","error":["private"]}]}', 0
        adapter.command = command
        self.assertEqual('disabled', k8sgpt(adapter)['status'])
        self.assertEqual([], calls)
        self.assertEqual('observed', k8sgpt(adapter, True)['status'])
        self.assertNotIn('--explain', calls[0])
        self.assertIn('$context', calls[0])
        self.assertNotIn('private', str(k8sgpt(adapter, True)))
        def fail(recipe): raise RuntimeError('unavailable')
        adapter.command = fail
        self.assertEqual('unavailable', k8sgpt(adapter, True)['status'])


class RecoveryWindowTests(unittest.TestCase):
    def test_readiness_requires_consecutive_success_and_never_retries_repair(self):
        from unittest.mock import patch
        from triage.health import verify_health
        clock = [0]
        def sleep(seconds): clock[0] += seconds
        def sample(ok): return {'healthy': ok, 'samples': [{'passed': ok}]}
        config = {'url': 'http://127.0.0.1/health', 'recovery_timeout_seconds': 10}
        with patch('triage.health.time.monotonic', side_effect=lambda: clock[0]), patch('triage.health.time.sleep', side_effect=sleep), patch('triage.health.check_health', side_effect=[sample(False),sample(True),sample(False),sample(True),sample(True)]) as probe:
            result = verify_health(config)
        self.assertTrue(result['healthy'])
        self.assertEqual(5, probe.call_count)
        self.assertEqual(4, result['elapsed_seconds'])
        clock[0] = 0
        with patch('triage.health.time.monotonic', side_effect=lambda: clock[0]), patch('triage.health.time.sleep', side_effect=sleep), patch('triage.health.check_health', return_value=sample(False)) as probe:
            result = verify_health(dict(config, recovery_timeout_seconds=3))
        self.assertFalse(result['healthy'])
        self.assertEqual(3, probe.call_count)
