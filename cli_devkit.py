"""Devkit CLI — autonomous development tools for PitchForge MVP.

Usage:
    python cli.py devkit setup <project-dir> [--planning <planning.json>]
    python cli.py devkit status <project-dir>
    python cli.py devkit cycle <project-dir>
    python cli.py devkit task <project-dir> <task-id> [--status <status>]
    python cli.py devkit plan <project-dir>
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add backend to path (supports code/backend/, backend/, and Docker /app/ layouts)
_base = os.path.dirname(__file__)
_backend_path = _base
for candidate in [
    os.path.join(_base, "code", "backend"),
    os.path.join(_base, "backend"),
    _base,  # Docker layout: modules at ./app/
]:
    if os.path.isdir(os.path.join(candidate, "app")):
        _backend_path = candidate
        break
sys.path.insert(0, _backend_path)

from app.devkit import DevAgent


def add_devkit_parser(sub):
    """Add devkit subcommand to argparse."""
    dk = sub.add_parser("devkit", help="Autonomous MVP development toolkit")
    dk_sub = dk.add_subparsers(dest="devkit_command", required=True)

    # setup
    setup_p = dk_sub.add_parser("setup", help="Initialize dev environment")
    setup_p.add_argument("project_dir", help="Project directory")
    setup_p.add_argument("--planning", "-p", help="Path to planning_report.json", default="")

    # status
    status_p = dk_sub.add_parser("status", help="Show project status")
    status_p.add_argument("project_dir", help="Project directory")

    # cycle
    cycle_p = dk_sub.add_parser("cycle", help="Run development cycle")
    cycle_p.add_argument("project_dir", help="Project directory")
    cycle_p.add_argument("--endpoints", "-e", nargs="*", help="Endpoints to check", default=[])

    # task
    task_p = dk_sub.add_parser("task", help="Manage task status")
    task_p.add_argument("project_dir", help="Project directory")
    task_p.add_argument("task_id", help="Task ID (e.g. TASK-001)")
    task_p.add_argument("--status", "-s", choices=["in_progress", "completed", "blocked", "failed"],
                        help="New status", default="")

    # plan
    plan_p = dk_sub.add_parser("plan", help="Generate DEVPLAN.md")
    plan_p.add_argument("project_dir", help="Project directory")
    plan_p.add_argument("--output", "-o", help="Output path", default="")


def run_devkit(args) -> None:
    """Execute devkit commands."""
    project_dir = args.project_dir

    if args.devkit_command == "setup":
        agent = DevAgent(project_dir)
        result = agent.setup(planning_json=args.planning if args.planning else None)
        print(f"✅ Dev environment ready in {project_dir}")
        print(f"   Vault files: {len(result['vault_files'])}")
        print(f"   Tasks created: {result['tasks_created']}")
        print(f"   Docker: {'✅' if result['docker_available'] else '❌'} available")

        if result['tasks_created'] > 0:
            agent.generate_dev_plan_md(str(Path(project_dir) / "DEVPLAN.md"))
            print(f"   DEVPLAN.md generated")

    elif args.devkit_command == "status":
        agent = DevAgent(project_dir)
        status = agent.status()
        print(f"📊 Status for {status['project']}")
        print(f"   Cycle: {status['cycle']}")
        print(f"   Tasks: {status['tasks']['completed']}/{status['tasks']['total']} done")
        print(f"   Docker: {'✅' if status['docker_available'] else '❌'}")
        if status['next_task']:
            t = status['next_task']
            print(f"   Next: {t['id']} — {t['title']} [{t['priority']}]")
        else:
            print(f"   ✅ All tasks completed!")
        print(f"   Vault files: {len(status['vault'])}")

    elif args.devkit_command == "cycle":
        agent = DevAgent(project_dir)
        result = agent.run_cycle(
            test_endpoints=args.endpoints if args.endpoints else None
        )
        print(f"🔄 Cycle {result['cycle']}")
        print(f"   Status: {result['status']}")
        if result['status'] == 'all_done':
            print(f"   🎉 MVP complete! {result['message']}")
        else:
            t = result['task']
            print(f"   Task: {t['id']} — {t['title']}")
            print(f"   Priority: {t['priority']}")
            print(f"   Criteria ({len(t['criteria'])}):")
            for c in t['criteria']:
                print(f"     - {c}")
            tr = result['test_results']
            print(f"   Tests: {'✅' if tr.get('steps',{}).get('tests',{}).get('success') else '❌'}")

    elif args.devkit_command == "task":
        agent = DevAgent(project_dir)
        if args.status == "completed":
            task = agent.complete_task(args.task_id)
        elif args.status == "blocked":
            task = agent.block_task(args.task_id, "Manually blocked")
        elif args.status == "failed":
            task = agent.fail_task(args.task_id, "Manually failed")
        elif args.status == "in_progress":
            task = agent.start_task(args.task_id)
        else:
            task = agent.tasks.get_task(args.task_id)

        if task:
            print(f"📋 {task.task_id}: {task.title} → {task.status}")
        else:
            print(f"❌ Task {args.task_id} not found")

    elif args.devkit_command == "plan":
        agent = DevAgent(project_dir)
        output = args.output or str(Path(project_dir) / "DEVPLAN.md")
        plan = agent.generate_dev_plan_md(output)
        print(f"📝 DEVPLAN generated: {output}")
        print(plan[:500] if len(plan) > 500 else plan)
