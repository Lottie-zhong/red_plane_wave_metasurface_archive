"""
Command-Line Interface for Generic GPU Runner

Usage:
  python cli.py submit_batch --manifest batch.json [--validate-only | --dry-run]
  python cli.py batch_status --batch-id BATCH_ID
  python cli.py list_queue [--status STATUS]
  python cli.py run_batch --batch-id BATCH_ID [--max-jobs N] [--production]
  python cli.py doctor
"""

import argparse
import sys
import json
from pathlib import Path
from generic_runner import GenericGPURunner, GenericBatchManifest
from resource_gate import check_resource_gate, ResourceGateStatus
from v21_worker_integration import integrate_v21_worker


def cmd_submit_batch(args):
    """Submit a batch for execution."""
    manifest_path = Path(args.manifest)
    
    if not manifest_path.exists():
        print(f"Error: Manifest file not found: {manifest_path}")
        return 1
    
    runner = GenericGPURunner()
    
    # Validate
    print(f"Validating batch manifest: {manifest_path}")
    is_valid, errors = runner.validate_batch(manifest_path)
    
    if not is_valid:
        print("\nValidation FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    
    print("Validation passed.")
    
    if args.validate_only:
        print("\n--validate-only: Stopping here (no submission)")
        return 0
    
    # Submit
    result = runner.submit_batch(
        manifest_path,
        authorization_token=args.auth_token,
        dry_run=args.dry_run
    )
    
    if result['success']:
        print(f"\n{result['message']}")
        if 'batch_id' in result:
            print(f"Batch ID: {result['batch_id']}")
            print(f"Total Jobs: {result.get('total_jobs', 'N/A')}")
        return 0
    else:
        print(f"\nSubmission FAILED: {result['message']}")
        if 'errors' in result:
            for error in result['errors']:
                print(f"  - {error}")
        return 1


def cmd_batch_status(args):
    """Get batch status."""
    runner = GenericGPURunner()
    status = runner.batch_status(args.batch_id)
    
    if not status:
        print(f"Error: Batch not found: {args.batch_id}")
        return 1
    
    print(f"\nBatch Status for: {status['batch_id']}")
    print(f"Project: {status['project_id']}")
    print(f"Status: {status['status']}")
    print(f"Submitted: {status['submitted_at']}")
    print(f"\nJobs:")
    print(f"  Total: {status['total_jobs']}")
    print(f"  Completed: {status['completed_jobs']}")
    print(f"  Failed: {status['failed_jobs']}")
    print(f"  Solver Entered: {status['entered_jobs']}")
    
    return 0


def cmd_list_queue(args):
    """List batches in queue."""
    runner = GenericGPURunner()
    batches = runner.list_queue(status_filter=args.status)
    
    if not batches:
        print("No batches found.")
        return 0
    
    print(f"\nBatches (Total: {len(batches)}):")
    print("-" * 80)
    print(f"{'Batch ID':<30} {'Project':<25} {'Status':<15} {'Submitted'}")
    print("-" * 80)
    
    for batch in batches:
        print(f"{batch['batch_id']:<30} {batch['project_id']:<25} {batch['status']:<15} {batch['submitted_at']}")
    
    return 0


def cmd_run_batch(args):
    """Execute batch jobs."""
    from execution_engine import GenericExecutionEngine, GenericRunnerDB
    
    print(f"Executing batch: {args.batch_id}")
    if args.production:
        print("  Mode: PRODUCTION_GPU")
        print("  WARNING: This will consume real solver budget!")
    else:
        print("  Mode: OFFLINE_FIXTURE (testing)")
    
    if args.max_jobs:
        print(f"  Max jobs: {args.max_jobs}")
    
    # Initialize engine
    ledger_path = Path('runner_data/ledger.db')
    if not ledger_path.exists():
        print(f"\nError: Ledger not found at {ledger_path}")
        print("Run 'python cli.py submit_batch' first to register batches.")
        return 1
    
    db = GenericRunnerDB(ledger_path)
    engine = GenericExecutionEngine(db)
    
    # Integrate V2.1 worker for production mode
    if args.production:
        try:
            print("\nIntegrating V2.1 GPU worker...")
            from generic_runner import GenericGPURunner
            # Create a minimal runner instance for adapter
            runner_instance = GenericGPURunner()
            integrate_v21_worker(runner_instance)
            # Attach to engine
            engine.runner = runner_instance
            print("  V2.1 worker integration: SUCCESS")
        except Exception as e:
            print(f"  V2.1 worker integration: FAILED")
            print(f"  Error: {e}")
            print("\n  Cannot run in production mode without V2.1 worker.")
            print("  Use --offline-mode for testing or fix V2.1 integration.")
            return 1
    
    # Check resources first
    print("\nChecking GPU resources...")
    gate_status = engine.check_resources()
    print(f"  Status: {gate_status['status']}")
    print(f"  Message: {gate_status['message']}")
    
    if gate_status['status'] in {'scientific_active', 'resource_conflict'}:
        print("\n  BLOCKED: Cannot proceed due to resource conflict.")
        print("  Close other GPU applications and try again.")
        return 1
    
    # Execute
    print("\nStarting batch execution...")
    result = engine.run_batch(
        args.batch_id,
        max_jobs=args.max_jobs,
        offline_mode=not args.production
    )
    
    # Report
    print(f"\n{'='*60}")
    print(f"Execution Summary:")
    print(f"  Batch: {result['batch_id']}")
    print(f"  Jobs Executed: {result['jobs_executed']}")
    print(f"  Jobs Failed: {result['jobs_failed']}")
    
    if result['executed']:
        print(f"\n  Completed Jobs:")
        for job in result['executed']:
            print(f"    - {job['job_id']}")
    
    if result['failed']:
        print(f"\n  Failed Jobs:")
        for job in result['failed']:
            error = job.get('error', job.get('reason', 'Unknown'))
            print(f"    - {job['job_id']}: {error}")
    
    print(f"{'='*60}\n")
    
    return 0 if result['success'] and result['jobs_failed'] == 0 else 1


def cmd_doctor(args):
    """System health check."""
    print("Generic GPU Runner - System Health Check")
    print("=" * 60)
    
    # Check resource gate
    print("\n1. Resource Gate Status:")
    status, report = check_resource_gate()
    print(report)
    
    if status == ResourceGateStatus.SCIENTIFIC_ACTIVE:
        print("\n  WARNING: Active solver detected - submissions will HOLD")
    elif status == ResourceGateStatus.CLEAR:
        print("\n  OK: System ready for GPU work")
    
    # Check GPU
    print("\n2. GPU Availability:")
    try:
        import subprocess
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"  {result.stdout.strip()}")
        else:
            print("  nvidia-smi check failed")
    except Exception as e:
        print(f"  GPU check skipped: {str(e)}")
    
    # Check database
    print("\n3. Ledger Database:")
    try:
        runner = GenericGPURunner()
        batches = runner.list_queue()
        print(f"  Registered batches: {len(batches)}")
        print(f"  Database path: {runner.config['ledger_path']}")
    except Exception as e:
        print(f"  ERROR: {str(e)}")
    
    # Check V2.1 integration
    print("\n4. V2.1 Integration:")
    try:
        from execution_engine import V21_AVAILABLE
        if V21_AVAILABLE:
            print("  OK: V2.1 modules available")
        else:
            print("  WARNING: V2.1 modules not found")
            print("  Production execution will be disabled")
    except Exception as e:
        print(f"  ERROR: {str(e)}")
    
    print("\n" + "=" * 60)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='APCD Generic GPU FDTD Runner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate batch manifest
  python cli.py submit_batch --manifest batch.json --validate-only
  
  # Submit batch for execution
  python cli.py submit_batch --manifest batch.json
  
  # Execute batch (offline testing)
  python cli.py run_batch --batch-id COUPLING_ML_001
  
  # Execute batch (production GPU - CAUTION!)
  python cli.py run_batch --batch-id COUPLING_ML_001 --production
  
  # Check batch status
  python cli.py batch_status --batch-id COUPLING_ML_001
  
  # List all batches
  python cli.py list_queue
  
  # System health check
  python cli.py doctor
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    # submit_batch
    submit_parser = subparsers.add_parser('submit_batch', help='Submit a batch')
    submit_parser.add_argument('--manifest', required=True, help='Path to batch manifest JSON')
    submit_parser.add_argument('--validate-only', action='store_true', help='Only validate, do not submit')
    submit_parser.add_argument('--dry-run', action='store_true', help='Validate and check database without submitting')
    submit_parser.add_argument('--auth-token', help='Authorization token (optional)')
    
    # batch_status
    status_parser = subparsers.add_parser('batch_status', help='Get batch status')
    status_parser.add_argument('--batch-id', required=True, help='Batch ID')
    
    # list_queue
    list_parser = subparsers.add_parser('list_queue', help='List batches')
    list_parser.add_argument('--status', help='Filter by status')
    
    # run_batch (NEW)
    run_parser = subparsers.add_parser('run_batch', help='Execute batch jobs')
    run_parser.add_argument('--batch-id', required=True, help='Batch ID to execute')
    run_parser.add_argument('--max-jobs', type=int, help='Maximum jobs to run (default: all)')
    run_parser.add_argument('--production', action='store_true',
                           help='Use production GPU solver (default: offline fixture)')
    
    # doctor
    subparsers.add_parser('doctor', help='System health check')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Dispatch
    if args.command == 'submit_batch':
        return cmd_submit_batch(args)
    elif args.command == 'batch_status':
        return cmd_batch_status(args)
    elif args.command == 'list_queue':
        return cmd_list_queue(args)
    elif args.command == 'run_batch':
        return cmd_run_batch(args)
    elif args.command == 'doctor':
        return cmd_doctor(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
