"""CLI for connection setup, evidence, approved recovery and incident follow-up."""
import argparse
import json
from pathlib import Path
from .engine import Engine
from .linux import Linux
from .integrations import ToolAdapter, catalog, load_configuration
from .tool_engine import ToolEngine
from .experience import ExperienceEngine
from .connections import ConnectionWizard
from .evidence import correlate
from .health import check_health
from .profiles import Profiles
from .operations import setup_status, compare, escalation, ci_exit_code


def parser():
    p=argparse.ArgumentParser(description='Live DevOps triage. Repairs and rollback always need explicit approval.')
    p.add_argument('--tool',default='linux')
    p.add_argument('--profile',default='default',help='Saved environment profile')
    p.add_argument('--config',help='Private JSON connection file')
    p.add_argument('--target',default='local',help='Linux: local or trusted SSH target')
    p.add_argument('--service',action='append',default=[],help='Linux: allowlisted systemd service')
    p.add_argument('--health-url',help='Optional application endpoint; HTTPS or loopback HTTP')
    p.add_argument('--state-dir',help='Private local state directory')
    sub=p.add_subparsers(dest='action',required=True)
    demo=sub.add_parser('demo',help='Show isolated sample incidents without infrastructure or AI');demo.add_argument('--scenario',choices=['docker-oom','kubernetes-image','linux-disk'],default='docker-oom')
    profile=sub.add_parser('profiles',help='List or save a copy of the current connection profile')
    profile.add_argument('--save');profile.add_argument('--environment',choices=['development','staging','production'])
    sub.add_parser('doctor',help='Check local prerequisites without authenticating')
    bench=sub.add_parser('ai-benchmark',help='Run synthetic cases on an already installed local Ollama model')
    bench.add_argument('--model',default='qwen2.5:0.5b');bench.add_argument('--cases',type=int,choices=[1,2,3],default=3);bench.add_argument('--ollama-pid',type=int)
    sub.add_parser('bundle',help='Collect bounded deep evidence and a filtered escalation summary')
    incidents=sub.add_parser('incidents',help='Search recent incidents for the exact selected target/profile')
    incidents.add_argument('--query',default='');incidents.add_argument('--status',choices=['all','findings','clear','verified','needs_attention'],default='all')
    handoff=sub.add_parser('handoff',help='Export a filtered escalation report');handoff.add_argument('--incident')
    comparison=sub.add_parser('compare',help='Compare two stored scans of the same target');comparison.add_argument('--before');comparison.add_argument('--after')
    recheck=sub.add_parser('recheck',help='Collect a fresh sample and compare it with an earlier scan');recheck.add_argument('--before');recheck.add_argument('--deep',action='store_true')
    sub.add_parser('tools');sub.add_parser('setup',help='Interactive connection wizard')
    sub.add_parser('validate',help='Validate scoped read access without changing resources')
    sub.add_parser('health',help='Check the configured application endpoint')
    diagnose=sub.add_parser('diagnose');diagnose.add_argument('--deep',action='store_true');diagnose.add_argument('--ai',action='store_true',help='Ask local Ollama to explain filtered findings');diagnose.add_argument('--ai-model',default='qwen2.5:0.5b',help='Installed local Ollama model')
    diagnose.add_argument('--fail-on',choices=['none','warning','critical','any'],default='none',help='CI policy; 2=incomplete evidence, 3=matching findings')
    group=sub.add_parser('correlate',help='Compare up to four explicitly selected sources')
    group.add_argument('tools',nargs='+');group.add_argument('--deep',action='store_true')
    plan=sub.add_parser('plan');plan.add_argument('action_name')
    for name in ('approve','apply','show','cancel','rollback'):
        cmd=sub.add_parser(name);cmd.add_argument('plan_id')
    sub.add_parser('history')
    timeline=sub.add_parser('timeline');timeline.add_argument('--incident')
    alerts=sub.add_parser('alerts');alerts.add_argument('--ack')
    web=sub.add_parser('web');web.add_argument('--port',type=int,default=8765)
    return p


def make_engine(args,configurations,tool=None):
    selected=tool or args.tool
    override={'url':args.health_url} if getattr(args,'health_url',None) else None
    context=getattr(args,'profile_context',None)
    if selected=='linux':
        adapter=Linux(args.target,args.service);core_type=Engine;health=override
    else:
        if args.target!='local' or args.service:raise ValueError('--target/--service apply only to Linux; other profiles use their configured contexts')
        if selected not in configurations:raise ValueError(f'No configuration for {selected}; run --tool {selected} setup or doctor')
        config=configurations[selected];adapter=ToolAdapter(selected,config);core_type=ToolEngine;health=override or config.get('application_health')
    if context and context['profile']!='default':
        from .engine import fingerprint
        adapter.target+=':profile:'+fingerprint(context['profile'])[:12]
    return ExperienceEngine(core_type(adapter,args.state_dir),health,context)


def main():
    p=parser();args=p.parse_args()
    try:
        if args.action=='demo':
            from .investigation import demo_report, overview
            sample=demo_report(args.scenario);sample['overview']=overview(sample)
            print(json.dumps(sample,indent=2));return
        if args.action=='ai-benchmark':
            from .benchmark import benchmark
            result=benchmark(args.model,args.cases,args.ollama_pid);print(json.dumps(result,indent=2))
            if result['status']!='completed':p.exit(2,'Local model benchmark incomplete.\n')
            return
        config_path=args.config or 'connections.json'
        profiles=Profiles(config_path,args.profile);configurations=profiles.tools();args.profile_context=profiles.context()
        wizard=ConnectionWizard(config_path,configurations,args.profile)
        if args.action=='profiles':
            if args.save:
                if not args.environment:raise ValueError('--save requires --environment')
                result=profiles.create(args.save,args.environment)
            else:result=profiles.listing()
            print(json.dumps(result,indent=2));return
        if args.action=='doctor':
            print(json.dumps(setup_status(args.tool,configurations.get(args.tool)),indent=2));return
        if args.action=='tools':print(json.dumps(catalog(configurations),indent=2));return
        if args.action=='setup':
            schema=wizard.schema(args.tool);print(schema['name']+': '+schema['scope'])
            config=dict(schema['current'])
            for field in schema['required']+schema.get('optional',[]):
                answer=input(f'{field} [{config.get(field, "")}]: ').strip()
                if answer:config[field]=answer
            endpoint=input('Application health URL (optional; no credentials in URL): ').strip()
            if endpoint:config['application_health']={'url':endpoint}
            print(json.dumps(wizard.save(args.tool,config),indent=2));return
        engine=make_engine(args,configurations)
        if args.action=='web':
            from .web import serve
            def select_profile(name):
                updated=profiles.select(name);configurations.clear();configurations.update(updated)
                args.profile_context=profiles.context();wizard.profile=name
                return profiles.listing()
            serve(engine,args.port,lambda tool:make_engine(args,configurations,tool),configurations,wizard,profiles,select_profile);return
        if args.action=='diagnose':
            result=engine.scan(args.deep)
            if args.ai:
                from .ai import explain
                result['ai']=explain(result,args.ai_model)
        elif args.action=='bundle':
            report=engine.scan(True)
            result={'report':report,'handoff':engine.store.handoff(report['incident_id'],engine.adapter.target)}
        elif args.action=='incidents':result=engine.store.search(engine.adapter.target,args.query,args.status)
        elif args.action=='handoff':
            _,latest=engine.store.latest(engine.adapter.target)
            if not latest:raise ValueError('Run checks before exporting a handoff')
            report=engine.store.get_scan(args.incident,engine.adapter.target) if args.incident else latest
            result=engine.store.handoff(report['incident_id'],engine.adapter.target)
        elif args.action in ('compare','recheck'):
            _,latest=engine.store.latest(engine.adapter.target)
            if not latest:raise ValueError('Run checks before comparing incidents')
            if args.action=='recheck':
                before=engine.store.get_scan(args.before,engine.adapter.target) if args.before else latest
                after=engine.scan(args.deep or bool(before.get('deep_evidence')))
            else:
                after=engine.store.get_scan(args.after,engine.adapter.target) if args.after else latest
                before_id=args.before or after.get('previous_incident_id')
                if not before_id:raise ValueError('A second stored scan is required for comparison')
                before=engine.store.get_scan(before_id,engine.adapter.target)
            result=compare(before,after)
        elif args.action=='validate':result=engine.validate_connection()
        elif args.action=='health':result=check_health(engine.health)
        elif args.action=='correlate':
            if len(args.tools)>4 or len(set(args.tools))!=len(args.tools):raise ValueError('Select up to four distinct tool IDs')
            result=correlate([make_engine(args,configurations,tool).scan(args.deep) for tool in args.tools],engine.store)
        elif args.action=='plan':result=engine.plan(args.action_name)
        elif args.action=='rollback':result=engine.rollback_plan(args.plan_id)
        elif args.action=='approve':
            print(json.dumps(engine.show(args.plan_id),indent=2))
            if input('Review target, operation and impact. Type the full plan ID to approve: ')!=args.plan_id:raise ValueError('Approval cancelled')
            result=engine.approve(args.plan_id)
        elif args.action in ('show','apply','cancel'):result=getattr(engine,args.action)(args.plan_id)
        elif args.action=='timeline':result=engine.store.timeline(args.incident)
        elif args.action=='alerts':result=engine.store.alerts(args.ack)
        else:result=engine.history()
        print(json.dumps(result,indent=2))
        if args.action=='apply' and result.get('status')!='verified':p.exit(2,'Recovery needs attention.\n')
        if args.action=='validate' and result.get('read_access')!='verified_for_collector_scope':p.exit(2,'Connection validation incomplete.\n')
        if args.action=='health' and result.get('healthy') is not True:p.exit(2,'Application health is not verified.\n')
        if args.action=='diagnose':
            code=ci_exit_code(result,args.fail_on)
            if code:p.exit(code,'Evidence collection incomplete.\n' if code==2 else 'Findings matched the CI failure policy.\n')
        if args.action=='bundle' and ci_exit_code(result['report'])==2:p.exit(2,'Evidence bundle is incomplete.\n')
    except (ValueError,RuntimeError,OSError,EOFError) as exc:p.exit(1,f'Error: {exc}\n')


if __name__=='__main__':main()
