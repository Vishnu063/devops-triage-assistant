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


def parser():
    p=argparse.ArgumentParser(description='Live DevOps triage. Repairs and rollback always need explicit approval.')
    p.add_argument('--tool',default='linux')
    p.add_argument('--config',help='Private JSON connection file')
    p.add_argument('--target',default='local',help='Linux: local or trusted SSH target')
    p.add_argument('--service',action='append',default=[],help='Linux: allowlisted systemd service')
    p.add_argument('--health-url',help='Optional application endpoint; HTTPS or loopback HTTP')
    p.add_argument('--state-dir',help='Private local state directory')
    sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('tools');sub.add_parser('setup',help='Interactive connection wizard')
    sub.add_parser('validate',help='Validate scoped read access without changing resources')
    sub.add_parser('health',help='Check the configured application endpoint')
    diagnose=sub.add_parser('diagnose');diagnose.add_argument('--deep',action='store_true')
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
    if selected=='linux':return ExperienceEngine(Engine(Linux(args.target,args.service),args.state_dir),override)
    if args.target!='local' or args.service:raise ValueError('--target/--service apply only to Linux; other profiles use their configured contexts')
    if selected not in configurations:raise ValueError(f'No configuration for {selected}; run --tool {selected} setup')
    config=configurations[selected]
    return ExperienceEngine(ToolEngine(ToolAdapter(selected,config),args.state_dir),override or config.get('application_health'))


def main():
    p=parser();args=p.parse_args()
    try:
        config_path=args.config or 'connections.json'
        configurations=load_configuration(config_path) if Path(config_path).expanduser().exists() else {}
        wizard=ConnectionWizard(config_path,configurations)
        if args.action=='tools':print(json.dumps(catalog(configurations),indent=2));return
        if args.action=='setup':
            schema=wizard.schema(args.tool);print(schema['name']+': '+schema['scope'])
            config=dict(schema['current'])
            for field in schema['required']:
                answer=input(f'{field} [{config.get(field, "")}]: ').strip()
                if answer:config[field]=answer
            endpoint=input('Application health URL (optional; no credentials in URL): ').strip()
            if endpoint:config['application_health']={'url':endpoint}
            print(json.dumps(wizard.save(args.tool,config),indent=2));return
        engine=make_engine(args,configurations)
        if args.action=='web':
            from .web import serve
            serve(engine,args.port,lambda tool:make_engine(args,configurations,tool),configurations,wizard);return
        if args.action=='diagnose':result=engine.scan(args.deep)
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
        if args.action=='diagnose' and result.get('snapshot',{}).get('errors'):p.exit(2,'Evidence collection incomplete.\n')
    except (ValueError,RuntimeError,OSError,EOFError) as exc:p.exit(1,f'Error: {exc}\n')


if __name__=='__main__':main()
