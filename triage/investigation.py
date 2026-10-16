"""Grounded incident guidance and isolated samples; no collectors or mutations."""
import copy
import re
from .ai import evidence_summary

DEMOS = {
    'docker-oom': {
        'name': 'Docker: container stopped after OOM', 'tool': 'docker',
        'code': 'docker:oom', 'title': 'Runtime reports an OOM termination',
        'evidence': 'Sample: OOMKilled=true, running=false, exit_code=137',
        'cause': 'The container exceeded available memory or its configured limit. The source of memory growth is not established.',
        'steps': ['Compare the container memory limit with peak usage and host capacity.',
                  'Check recent application changes and bounded logs for memory growth.',
                  'Confirm the workload can fit before considering a reviewed restart.'],
        'signals': {'memory': 3},
    },
    'kubernetes-image': {
        'name': 'Kubernetes: image pull failure', 'tool': 'kubernetes',
        'code': 'kubernetes:image', 'title': 'Image pull failure appears in sample log signatures',
        'evidence': 'Sample: unavailable replicas=2; image-pull signature count=4',
        'cause': 'An incorrect image reference, registry access, missing pull credentials or connectivity could explain the failure.',
        'steps': ['Inspect the affected pod events to distinguish missing image from authorization or connectivity failures.',
                  'Verify the exact image tag or digest exists in the registry.',
                  'Check imagePullSecret references and registry reachability without exposing secret values.'],
        'signals': {'image': 4},
    },
    'linux-disk': {
        'name': 'Linux: root disk nearly full', 'tool': 'linux',
        'code': 'disk-pressure', 'title': 'Root disk usage is high',
        'evidence': 'Sample: root disk used=96%; disk log signature count=2',
        'cause': 'Logs, container layers, application data or other files may be growing. The sample does not identify the owner.',
        'steps': ['Measure filesystem and inode usage before changing anything.',
                  'Identify the largest directories and confirm data ownership and retention requirements.',
                  'Review targeted cleanup or capacity changes with the service owner; avoid blind deletion.'],
        'signals': {'disk': 2},
    },
}
QUESTIONS = {
    'summary': 'What happened?', 'cause': 'What is the likely cause?',
    'checks': 'What should I check next?', 'changes': 'What changed?',
    'safety': 'Can I safely repair this?', 'health': 'Is the application healthy?',
}


def demo_report(scenario='docker-oom'):
    if not isinstance(scenario, str) or scenario not in DEMOS:
        raise ValueError('Choose docker-oom, kubernetes-image or linux-disk')
    item = DEMOS[scenario]
    snapshot = {'collected_at': 0, 'errors': []}
    if item['tool'] == 'linux':
        snapshot.update(disk_used_percent=96, memory_used_percent=38, load1=0.4, cpu_count=2)
    return {'demo': True, 'scenario': scenario, 'tool': item['tool'], 'target': 'SAMPLE DATA — no live target',
            'incident_id': 'demo:'+scenario, 'snapshot': snapshot,
            'coverage': 'Synthetic demonstration only. No infrastructure is inspected or changed.',
            'findings': [{'code': item['code'], 'title': item['title'], 'evidence': item['evidence'],
                          'likely_cause': item['cause'], 'next_steps': list(item['steps']), 'service': None,
                          'confidence': {'observation': 'sample_only', 'cause': 'possible',
                                         'basis': 'Synthetic data for learning, not live evidence.'}}],
            'deep_evidence': {'log_signals': dict(item['signals'])},
            'application_health': {'healthy': None}, 'actions': [], 'changes_since_previous_scan': []}


def overview(report):
    snapshot = report.get('snapshot', {})
    incomplete = bool(snapshot.get('errors') or snapshot.get('empty') or report.get('deep_evidence', {}).get('errors'))
    findings = report.get('findings', [])
    health = report.get('application_health', {}).get('healthy')
    if report.get('demo'):
        headline = 'Sample incident — no live checks performed'
    elif incomplete:
        headline = 'Evidence is incomplete'
    elif findings:
        headline = 'Findings need investigation'
    else:
        headline = 'No rule findings in this sample'
    next_step = ('Resolve collector errors and rerun checks before considering repairs.' if incomplete else
                 next((step for finding in findings for step in finding.get('next_steps', [])),
                      'Confirm application health and the collector scope; no findings does not prove overall health.'))
    return {'headline': headline, 'finding_count': len(findings), 'collection': 'incomplete' if incomplete else 'completed_for_scope',
            'application': 'healthy_for_policy' if health is True else 'failed_policy' if health is False else 'not_verified',
            'next_step': next_step, 'demo': bool(report.get('demo'))}


def intent_for(question):
    if not isinstance(question, str) or not question.strip() or len(question) > 500:
        raise ValueError('Ask a question between 1 and 500 characters; do not include credentials')
    q = question.lower().strip()
    if q in QUESTIONS: return q
    if re.search(r'health|recover|working|resolved', q): return 'health'
    if re.search(r'change|different|since|before', q): return 'changes'
    if re.search(r'safe|repair|restart|fix|delete|execute|run command|approve', q): return 'safety'
    if re.search(r'check|next|investigat|steps|how', q): return 'checks'
    if re.search(r'cause|why|reason', q): return 'cause'
    if re.search(r'happen|summar|explain|wrong|status', q): return 'summary'
    return None


def answer(report, question):
    """Recognize a bounded question intent; never treat user text as an operation."""
    intent = intent_for(question)
    findings = report.get('findings', [])
    view = overview(report)
    prefix = 'SAMPLE DATA. ' if report.get('demo') else ''
    references = [{'code': f.get('code'), 'evidence': f.get('evidence'),
                   'confidence': f.get('confidence', {})} for f in findings[:10]]
    if intent == 'summary':
        text = view['headline']+'. '+(' '.join(f['title']+'.' for f in findings[:5]) or 'Review the collection scope and application probes before concluding the service is healthy.')
    elif intent == 'cause':
        text = '\n'.join(f.get('likely_cause', 'Cause not established.') for f in findings[:5]) or 'No underlying cause has been established by this sample.'
        text += '\nThese are investigation hypotheses, not confirmed root causes.'
    elif intent == 'checks':
        steps = list(dict.fromkeys(step for f in findings for step in f.get('next_steps', [])))[:8]
        text = '\n'.join(str(i+1)+'. '+step for i, step in enumerate(steps)) or view['next_step']
        if view['collection'] == 'incomplete': text = 'First resolve incomplete evidence collection.\n'+text
    elif intent == 'changes':
        changes = report.get('changes_since_previous_scan', [])
        fields = [str(c.get('field', 'unknown')) for c in changes[:12]]
        text = ('Changed sampled fields: '+', '.join(fields)+'.' if fields else 'No scan-to-scan changes are recorded for this sample.')
        text += ' This is not an audit log and does not prove what caused the incident.'
    elif intent == 'safety':
        text = 'This question does not authorize a repair. Review fresh evidence, target, impact and application checks. Only a supported exact plan can be approved and executed separately. A restart can interrupt traffic and repeat the failure.'
        if report.get('demo'): text = 'Demo mode never creates or executes repair plans. '+text
    elif intent == 'health':
        text = {'healthy_for_policy': 'The configured application probe passed its policy for this sample. This does not establish complete system health.',
                'failed_policy': 'The configured application probe did not pass its policy. Inspect the evidence before another action.',
                'not_verified': 'Application health is not verified in this sample. Configure an application endpoint and run fresh checks.'}[view['application']]
    else:
        text = 'I can explain this incident using six guided topics: what happened, likely cause, next checks, observed changes, repair safety and application health. Choose a topic below. This guided assistant is not an unrestricted AI chat.'
    return {'mode': 'guided_evidence', 'intent': intent, 'incident_id': report['incident_id'], 'demo': bool(report.get('demo')),
            'answer': prefix+text, 'references': references, 'questions': copy.deepcopy(QUESTIONS),
            'notice': 'Answers use the selected stored sample. No commands are run and no additional evidence is collected.'}


def share_summary(report):
    """Deliberately omit resource identifiers, raw evidence, URLs and user questions."""
    summary = evidence_summary(report)
    return {'demo': bool(report.get('demo')), 'overview': {
                key: value for key, value in overview(report).items() if key != 'next_step'},
            'evidence': summary, 'scope': 'Filtered incident summary. No credentials, identities or raw logs. Review before sharing.'}
