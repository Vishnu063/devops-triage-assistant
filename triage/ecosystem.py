"""Structured diagnostic view over existing evidence, never a repair executor."""
from datetime import datetime, timezone
from .integrations import redact, ToolAdapter


def diagnosis(report):
    if not isinstance(report, dict) or not isinstance(report.get('findings'), list) or not isinstance(report.get('incident_id'), str):
        raise ValueError('Use an ExperienceEngine incident report with findings and incident_id')
    evidence = []
    hypotheses = []
    for index, finding in enumerate(report['findings'][:100]):
        if not isinstance(finding, dict):
            raise ValueError('Findings must be objects')
        reference = f'findings/{index}'
        evidence.append({'id': reference, 'observation': redact(finding.get('evidence', 'Unavailable'))})
        hypotheses.append({'title': redact(finding.get('title', 'Unspecified finding')),
            'likely_cause': redact(finding.get('likely_cause', 'Cause remains unknown')),
            'evidence_refs': [reference], 'confidence': finding.get('confidence', {'cause': 'possible'}),
            'next_steps': redact(finding.get('next_steps', []))})
    return dict(schema_version=1, kind='Diagnosis', id=report['incident_id'] + ':diagnosis',
        source='devops-triage-assistant', timestamp=datetime.now(timezone.utc).isoformat(),
        correlation_id=report['incident_id'], incident_id=report['incident_id'],
        evidence=evidence, hypotheses=hypotheses, ai_enabled=False,
        uncertainty='Observed symptoms and rule-based hypotheses; causation is not guaranteed.',
        suggested_commands=[], scope='Commands are not inferred from prose or executed. Use the configured native collector.')


def k8sgpt(adapter, enabled=False):
    """Optional deterministic analysis of one explicitly configured namespace.

    Reuse the bounded native transport (timeout, output limit, no shell). No
    --explain/--anonymize/backend command: no paid or local model is required.
    """
    if not enabled:
        return {'status': 'disabled', 'findings': []}
    if not isinstance(adapter, ToolAdapter) or adapter.tool != 'kubernetes':
        raise ValueError('K8sGPT requires an explicitly configured Kubernetes adapter')
    import json
    try:
        raw, _ = adapter.command(['k8sgpt', 'analyze', '--kubecontext', '$context', '--namespace', '$namespace', '--output', 'json'])
        result = json.loads(raw)
        if not isinstance(result, dict) or not isinstance(result.get('results'), list):
            raise ValueError('Unexpected K8sGPT output')
        # Namespace-scoped reports can include messages containing private data.
        # Persist only identifiers/count, never raw analysis/error messages.
        findings = [{'kind': redact(row.get('kind')), 'name': redact(row.get('name'))}
                    for row in result['results'][:100] if isinstance(row, dict)]
        return {'status': 'observed', 'findings': findings, 'scope': 'Namespace-scoped deterministic K8sGPT; no AI explanation or execution'}
    except (OSError, RuntimeError, ValueError, TypeError):
        return {'status': 'unavailable', 'findings': [], 'error': 'Check K8sGPT version, explicit context and read-only namespace RBAC'}
