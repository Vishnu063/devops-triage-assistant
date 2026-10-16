"""Incident comparison, actionable setup hints, filtered handoff and CI policy."""
import json
import shutil
from .catalog import PROFILES
from .integrations import requirements
from .investigation import overview, share_summary


def setup_status(tool,config=None,errors=None,linux_target="local"):
    if tool=='linux':
        remote=linux_target!='local';available=not remote or shutil.which('ssh') is not None
        return {'tool':tool,'configured_target':linux_target,'ready_for_attempt':available,
                'checks':[{'name':'SSH client' if remote else 'local metrics','status':'ready' if available else 'missing'}],
                'next_steps':['Run validation to check the configured SSH target, noninteractive authentication, remote Python and any required systemd permissions.' if remote else 'Run diagnose for local metrics. Service checks require an explicit allowlist.']}
    if tool not in PROFILES:raise ValueError('Unknown tool ID')
    profile=PROFILES[tool];config=config or {};checks=[];steps=[]
    fields=requirements(profile)+(['base_url'] if profile['endpoint'] else [])
    missing=[field for field in fields if config.get(field) is None or str(config.get(field,'')).strip()=='']
    if missing:steps.append('Open Connection wizard and fill: '+', '.join(missing)+'.')
    checks.append({'name':'required settings','status':'missing' if missing else 'present','fields':missing})
    if profile['command']:
        binary=profile['command'][0];available=shutil.which(binary) is not None
        checks.append({'name':'native CLI','binary':binary,'status':'available' if available else 'missing'})
        if not available:steps.append('Install '+binary+' on the computer running this assistant, then verify '+binary+' --version locally.')
    errors=' '.join(str(error).lower() for error in errors or [])
    if any(term in errors for term in ('permission','forbidden','unauthorized','authentication','403','401')):
        steps.append('Check the selected account/context and its scoped read permissions. Do not grant administrator access just to clear this error.')
        if tool=='kubernetes':steps.append('Ask your administrator to review get Deployment, list owned ReplicaSets/pods/events, get named Service/config objects and pods/log permissions for the configured namespace.')
    if any(term in errors for term in ('timed out','unreachable','tls','connection')):steps.append('Check routing, local service readiness, proxy/tunnel settings and certificate trust; rerun validation after correcting the connection.')
    if any(term in errors for term in ('schema','invalid json','incompatible','expected evidence')):steps.append('Check the native tool/API version and supported output schema. Missing evidence must not be treated as healthy.')
    if not steps:steps.append('Validate scoped read access, then run live checks. Saved settings do not establish connection health.')
    return {'tool':tool,'ready_for_attempt':not missing and all(c['status']!='missing' for c in checks),
            'checks':checks,'next_steps':steps,'scope':'Local prerequisites and sanitized error categories only; no authentication or network request performed.'}


def compare(before,after):
    if not before or not after or before['target']!=after['target']:raise ValueError('Choose two scans of the same exact target and profile')
    a={f['code'] for f in before.get('findings',[])};b={f['code'] for f in after.get('findings',[])}
    return {'before_incident':before['incident_id'],'after_incident':after['incident_id'],
            'before_collected_at':before.get('snapshot',{}).get('collected_at'),
            'after_collected_at':after.get('snapshot',{}).get('collected_at'),
            'resolved_codes':sorted(a-b),'new_codes':sorted(b-a),'remaining_codes':sorted(a&b),
            'before_health':before.get('application_health',{}).get('healthy'),
            'after_health':after.get('application_health',{}).get('healthy'),
            'before_collection':overview(before)['collection'],'after_collection':overview(after)['collection'],
            'scope':'Two observed samples only. Disappearing findings do not prove a repair caused recovery; missing/incomplete evidence limits comparison.'}


def escalation(report,steps):
    attempts=[]
    for step in sorted(steps,key=lambda item:item['time']):
        if step['kind'] in ('repair_result','rollback_result'):
            data=step['data'];attempts.append({'time':step['time'],'kind':step['kind'],'status':data.get('status'),
                'infrastructure_status':data.get('infrastructure_status'),
                'application_healthy':data.get('application_health',{}).get('healthy')})
    questions=['Confirm the causal sequence before treating a hypothesis as the root cause.']
    if overview(report)['collection']=='incomplete':questions.append('Resolve missing collection permissions, incompatible schemas or bounded-scope errors.')
    if report.get('application_health',{}).get('healthy') is not True:questions.append('Application health remains failed or unverified; validate the configured probe or a business transaction.')
    if report.get('findings'):questions.append('Investigate unresolved finding codes and confirm whether changes align with incident timing.')
    return {'summary':share_summary(report),'collected_at':report.get('snapshot',{}).get('collected_at'),
            'attempted_repairs':attempts[:20],'unresolved_questions':questions,
            'scope':'Filtered handoff; identifiers, commands, configuration and raw logs are excluded. No repair result means no recorded completed attempt, not proof that nothing happened.'}


def ci_exit_code(report,fail_on='none'):
    if overview(report)['collection']=='incomplete':return 2
    findings=report.get('findings',[])
    if fail_on=='any' and findings:return 3
    if fail_on=='critical' and any(f.get('severity')=='critical' for f in findings):return 3
    if fail_on=='warning' and any(f.get('severity') in ('critical','warning') for f in findings):return 3
    return 0


def severity(finding):
    code=finding['code']
    critical={'application-health','failed-service','docker:state','docker:health','podman:state','podman:health','kubernetes:available','kubernetes:reason','kubernetes:image-pull','kubernetes:crash-loop','kubernetes:missing-configuration',
              'kubernetes:configuration','kubernetes:service-selector','kubernetes:resource-shortage'}
    return 'critical' if code in critical or code.endswith(':oom') else 'warning'
