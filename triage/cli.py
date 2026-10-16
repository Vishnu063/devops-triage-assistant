"""CLI and a loopback-only dashboard share one diagnosis and approval engine."""
import argparse
import json
from .engine import Engine
from .linux import Linux


def parser():
    p = argparse.ArgumentParser(description="Live Linux triage. Changes always need explicit approval.")
    p.add_argument("--target", default="local", help="local or an existing trusted OpenSSH alias / user@host")
    p.add_argument("--service", action="append", default=[], help="Allowlisted systemd service (repeatable)")
    p.add_argument("--state-dir", help="Private local directory for plans and audit history")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("diagnose", help="Collect live read-only evidence")
    plan = sub.add_parser("plan", help="Propose a restart for a failed service")
    plan.add_argument("service_name")
    for name in ("approve", "apply", "show", "cancel"):
        cmd = sub.add_parser(name)
        cmd.add_argument("plan_id")
    sub.add_parser("history")
    web = sub.add_parser("web", help="Start local dashboard; use an SSH tunnel for remote access")
    web.add_argument("--port", type=int, default=8765)
    return p


def main():
    p = parser()
    args = p.parse_args()
    try:
        engine = Engine(Linux(args.target, args.service), args.state_dir)
        if args.action == "web":
            from .web import serve
            serve(engine, args.port)
            return
        if args.action == "diagnose":
            result = engine.scan()
        elif args.action == "plan":
            result = engine.plan(args.service_name)
        elif args.action == "approve":
            print(json.dumps(engine.show(args.plan_id), indent=2))
            if input("Review target, command and risk. Type the full plan ID to approve: ") != args.plan_id:
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
    except (ValueError, RuntimeError, OSError, EOFError) as exc:
        p.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
