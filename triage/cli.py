"""CLI entry point shared by Linux and all configured tool profiles."""
import argparse
import json
from .engine import Engine
from .linux import Linux
from .integrations import ToolAdapter, catalog, load_configuration
from .tool_engine import ToolEngine


def parser():
    p = argparse.ArgumentParser(description="Live DevOps triage. Changes always need explicit approval.")
    p.add_argument("--tool", default="linux", help="linux or a tool ID from the tools command")
    p.add_argument("--config", help="Private JSON file containing tool connections and resource scopes")
    p.add_argument("--target", default="local", help="Linux only: local or trusted SSH alias / user@hostname")
    p.add_argument("--service", action="append", default=[], help="Linux only: allowlisted systemd service")
    p.add_argument("--state-dir", help="Private local directory for plans and history")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("tools", help="List tool profiles, scopes, required configuration and repair support")
    sub.add_parser("diagnose", help="Collect scoped live evidence")
    plan = sub.add_parser("plan", help="Propose a repair; Linux takes a service name, other tools an action ID")
    plan.add_argument("action_name")
    for name in ("approve", "apply", "show", "cancel"):
        cmd = sub.add_parser(name)
        cmd.add_argument("plan_id")
    sub.add_parser("history")
    web = sub.add_parser("web", help="Start local multi-tool dashboard")
    web.add_argument("--port", type=int, default=8765)
    return p


def make_engine(args, configurations, tool=None):
    selected = tool or args.tool
    if selected == "linux":
        return Engine(Linux(args.target, args.service), args.state_dir)
    if args.target != "local" or args.service:
        raise ValueError("--target/--service apply only to Linux. Other tools use explicit API/native CLI contexts in --config.")
    if selected not in configurations:
        raise ValueError(f"No configuration for {selected}; see examples/connections.example.json")
    return ToolEngine(ToolAdapter(selected, configurations[selected]), args.state_dir)


def main():
    p = parser()
    args = p.parse_args()
    try:
        configurations = load_configuration(args.config)
        if args.action == "tools":
            print(json.dumps(catalog(configurations), indent=2))
            return
        engine = make_engine(args, configurations)
        if args.action == "web":
            from .web import serve
            serve(engine, args.port, lambda tool: make_engine(args, configurations, tool), configurations)
            return
        if args.action == "diagnose":
            result = engine.scan()
        elif args.action == "plan":
            result = engine.plan(args.action_name)
        elif args.action == "approve":
            print(json.dumps(engine.show(args.plan_id), indent=2))
            if input("Review target, command, risk and verification. Type the full plan ID to approve: ") != args.plan_id:
                raise ValueError("Approval cancelled")
            result = engine.approve(args.plan_id)
        elif args.action == "show":
            result = engine.show(args.plan_id)
        elif args.action == "apply":
            result = engine.apply(args.plan_id)
        elif args.action == "cancel":
            result = engine.cancel(args.plan_id)
        else:
            result = engine.history()
        print(json.dumps(result, indent=2))
        if args.action == "diagnose" and result.get("snapshot", {}).get("errors"):
            p.exit(2, "Evidence collection incomplete.\n")
        if args.action == "apply" and result.get("status") != "verified":
            p.exit(2, "Repair needs operator attention.\n")
    except (ValueError, RuntimeError, OSError, EOFError) as exc:
        p.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
