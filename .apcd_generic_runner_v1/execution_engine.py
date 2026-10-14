"""
Generic GPU Runner - Execution Engine Integration with V2.1 Worker

Integrates the batch submission framework with V2.1's validated GPU execution kernel.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

# Import V2.1 components from .apcd86_agent
v21_path = Path(__file__).parent.parent / '.apcd86_agent'
sys.path.insert(0, str(v21_path))

from generic_runner import GenericRunnerDB, BatchStatus, JobStatus, ResourceGateStatus

# Try to import V2.1 components
V21_AVAILABLE = False
V21_WORKER_AVAILABLE = False

try:
    # Check if closeout_serial.py exists and can be imported
    closeout_path = v21_path / 'closeout_serial.py'
    if closeout_path.exists():
        V21_WORKER_AVAILABLE = True
        print(f"V2.1 worker found at: {closeout_path}")
except Exception as e:
    print(f"Warning: Could not locate V2.1 worker: {e}")

try:
    import psutil
    V21_AVAILABLE = True
except ImportError:
    print("Warning: psutil not available. Resource gate will be limited.")


class GPUResourceGate:
    """
    GPU resource gate check.
    Checks for GPU conflicts before solver launch.
    """
    
    @staticmethod
    def check() -> Dict[str, Any]:
        """Check GPU resource availability."""
        if not V21_AVAILABLE:
            return {
                'status': ResourceGateStatus.UNKNOWN.value,
                'message': 'psutil not available - cannot check GPU processes',
                'processes': [],
                'conflicts': []
            }
        
        try:
            import psutil
            evidence = []
            conflicts = []
            
            # Check for Lumerical/Ansys processes
            for p in psutil.process_iter(['pid', 'name', 'create_time']):
                try:
                    pinfo = p.info
                    name = pinfo.get('name', '').lower()
                    
                    # Known Lumerical/Ansys processes
                    if any(x in name for x in ['fdtd-engine', 'ansysedt', 'lumerical']):
                        evidence.append({
                            'pid': pinfo['pid'],
                            'name': pinfo['name'],
                            'create_time': pinfo.get('create_time')
                        })
                        
                        # Check if it's a scientific solver
                        if 'fdtd-engine' in name or 'fdtd' in name:
                            conflicts.append({
                                'pid': pinfo['pid'],
                                'name': pinfo['name'],
                                'reason': 'Active FDTD process detected'
                            })
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Determine status
            if conflicts:
                status = ResourceGateStatus.RESOURCE_CONFLICT
                message = f"GPU conflict: {len(conflicts)} active solver(s)"
            elif evidence:
                status = ResourceGateStatus.GUI_ONLY
                message = f"Lumerical/Ansys GUI detected ({len(evidence)} process(es)), no active solver"
            else:
                status = ResourceGateStatus.CLEAR
                message = "No GPU conflicts detected"
                
            return {
                'status': status.value,
                'message': message,
                'processes': evidence,
                'conflicts': conflicts
            }
            
        except Exception as e:
            return {
                'status': ResourceGateStatus.UNKNOWN.value,
                'message': f'Resource check failed: {e}',
                'processes': [],
                'conflicts': []
            }


class GenericExecutionEngine:
    """
    Execution engine that connects Generic Runner to V2.1 GPU worker.
    
    Responsibilities:
    - Load jobs from Generic Runner ledger
    - Check GPU resource gate
    - Invoke V2.1 worker for each job
    - Capture native FSP/H5 artifacts
    - Update ledger with results
    - Auto-advance to next job
    """
    
    def __init__(self, db: GenericRunnerDB):
        """Initialize execution engine."""
        self.db = db
        self.resource_gate = GPUResourceGate()
        
    def run_batch(
        self,
        batch_id: str,
        job_id: Optional[str] = None,
        max_jobs: Optional[int] = None,
        offline_mode: bool = False
    ) -> Dict[str, Any]:
        """
        Execute batch jobs.
        
        Args:
            batch_id: Batch to execute
            job_id: Specific job (None = all pending)
            max_jobs: Maximum jobs to execute (None = all)
            offline_mode: Use fake solver for testing (default False)
            
        Returns:
            Execution summary
        """
        print(f"\n{'='*60}")
        print(f"Executing Batch: {batch_id}")
        print(f"{'='*60}")
        
        # Get batch info
        batch = self.db.get_batch(batch_id)
        if not batch:
            return {
                'success': False,
                'error': f'Batch not found: {batch_id}',
                'batch_id': batch_id
            }
        
        # Get pending jobs
        if job_id:
            jobs = [self.db.get_job(batch_id, job_id)] if self.db.get_job(batch_id, job_id) else []
        else:
            jobs = self.db.list_jobs(batch_id, status=JobStatus.QUEUED)
        
        if not jobs:
            print(f"\nNo pending jobs found for batch {batch_id}")
            return {
                'success': True,
                'batch_id': batch_id,
                'jobs_executed': 0,
                'jobs_failed': 0,
                'executed': [],
                'failed': []
            }
        
        # Apply max_jobs limit
        if max_jobs:
            jobs = jobs[:max_jobs]
        
        print(f"\nJobs to execute: {len(jobs)}")
        if offline_mode:
            print("⚠ OFFLINE MODE: Using fake solver")
        
        # Execute jobs serially
        results = {
            'success': True,
            'batch_id': batch_id,
            'jobs_executed': 0,
            'jobs_failed': 0,
            'executed': [],
            'failed': []
        }
        
        for i, job in enumerate(jobs, 1):
            print(f"\n{'-'*60}")
            print(f"Job {i}/{len(jobs)}: {job['job_id']}")
            print(f"{'-'*60}")
            
            try:
                job_result = self._execute_job(job, offline_mode=offline_mode)
                
                if job_result['success']:
                    results['jobs_executed'] += 1
                    results['executed'].append(job_result)
                    print(f"✓ Job completed: {job['job_id']}")
                else:
                    results['jobs_failed'] += 1
                    results['failed'].append(job_result)
                    print(f"✗ Job failed: {job['job_id']}")
                    
            except Exception as e:
                print(f"✗ Job exception: {e}")
                results['jobs_failed'] += 1
                results['failed'].append({
                    'job_id': job['job_id'],
                    'success': False,
                    'error': str(e)
                })
        
        print(f"\n{'='*60}")
        print(f"Batch Execution Complete")
        print(f"{'='*60}")
        print(f"Executed: {results['jobs_executed']}")
        print(f"Failed: {results['jobs_failed']}")
        print(f"{'='*60}\n")
        
        return results
    
    def _execute_job(self, job: Dict[str, Any], offline_mode: bool = False) -> Dict[str, Any]:
        """
        Execute a single job.
        
        Args:
            job: Job record from ledger
            offline_mode: Use fake solver
            
        Returns:
            Job execution result
        """
        job_id = job['job_id']
        batch_id = job['batch_id']
        
        # 1. Check resource gate (skip in offline mode)
        if not offline_mode:
            gate_result = self.resource_gate.check()
            print(f"  Resource gate: {gate_result['status']}")
            
            if gate_result['status'] == ResourceGateStatus.RESOURCE_CONFLICT.value:
                raise Exception(f"GPU conflict: {gate_result['message']}")
        else:
            print(f"  Resource gate: SKIPPED (offline mode)")
        
        # 2. Mark solver_entered BEFORE launch (atomic entry)
        entered_at = datetime.utcnow().isoformat() + 'Z'
        self.db.mark_solver_entered(batch_id, job_id, entered_at)
        print(f"  Solver entered marked: {entered_at}")
        
        # 3. Execute solver
        if offline_mode:
            result = self._offline_solver(job)
        else:
            result = self._real_solver(job)
        
        # 4. Capture artifacts
        artifacts = result.get('artifacts', {})
        print(f"  Artifacts: {len(artifacts)} files")
        
        # 5. Validate results
        is_valid = self._validate_artifacts(artifacts)
        print(f"  Validation: {'PASS' if is_valid else 'FAIL'}")
        
        # 6. Update ledger
        if is_valid:
            self.db.mark_job_completed(
                batch_id,
                job_id,
                result_hash=result.get('result_hash'),
                completed_at=datetime.utcnow().isoformat() + 'Z',
                artifacts_json=json.dumps(artifacts),
                metadata_json=json.dumps(result.get('metadata', {}))
            )
            print(f"  Status: COMPLETED")
        else:
            self.db.mark_job_failed(
                batch_id,
                job_id,
                error='Artifact validation failed',
                failed_at=datetime.utcnow().isoformat() + 'Z'
            )
            print(f"  Status: FAILED")
        
        return {
            'job_id': job_id,
            'success': is_valid,
            'artifacts': artifacts,
            'result': result
        }
    
    def _offline_solver(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Offline solver fixture for testing.
        Simulates solver execution without real FDTD.
        """
        print(f"  Running OFFLINE solver fixture...")
        time.sleep(0.5)  # Simulate work
        
        # Create fake artifacts in output directory
        output_dir = Path(job['output_dir'])
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create fake FSP
        fsp_path = output_dir / f"{job['job_id']}.fsp"
        fsp_content = f"OFFLINE_SOLVER_FIXTURE\nJob: {job['job_id']}\nTime: {datetime.utcnow().isoformat()}"
        fsp_path.write_text(fsp_content, encoding='utf-8')
        
        # Create fake H5
        h5_path = output_dir / f"{job['job_id']}_p0.h5"
        h5_path.write_text("OFFLINE_H5_FIXTURE", encoding='utf-8')
        
        # Create fake log
        log_path = output_dir / f"{job['job_id']}.log"
        log_path.write_text(f"Offline solver log\nJob: {job['job_id']}", encoding='utf-8')
        
        return {
            'success': True,
            'artifacts': {
                'fsp': str(fsp_path),
                'h5': str(h5_path),
                'log': str(log_path)
            },
            'result_hash': 'offline_fixture_hash',
            'metadata': {
                'solver_type': 'offline_fixture',
                'wall_time': 0.5
            }
        }
    
    def _real_solver(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Real V2.1 GPU solver invocation via V21WorkerAdapter.
        
        This calls the validated V2.1 worker execution kernel.
        Requires V2.1 integration via integrate_v21_worker function.
        """
        if not hasattr(self.runner, '_v21_adapter'):
            raise RuntimeError(
                "V2.1 worker not integrated. "
                "Call integrate_v21_worker first or use --offline-mode."
            )
        
        # Extract job_id from job dict
        job_id = job.get('job_id')
        if not job_id:
            raise ValueError("Job must have job_id field")
        
        # Call V2.1 worker adapter
        return self.runner._v21_adapter.execute_job(job_id)
    
    def _validate_artifacts(self, artifacts: Dict[str, str]) -> bool:
        """
        Validate solver artifacts.
        
        Args:
            artifacts: Dictionary of artifact paths
            
        Returns:
            True if artifacts are valid
        """
        required = ['fsp', 'h5']
        
        for key in required:
            if key not in artifacts:
                print(f"    Missing artifact: {key}")
                return False
            
            path = Path(artifacts[key])
            if not path.exists():
                print(f"    Artifact not found: {path}")
                return False
            
            if path.stat().st_size == 0:
                print(f"    Artifact is empty: {path}")
                return False
        
        return True


# CLI integration helpers

def run_batch_command(
    batch_id: str,
    job_id: Optional[str] = None,
    max_jobs: Optional[int] = None,
    offline_mode: bool = False,
    ledger_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Execute batch from CLI.
    
    Args:
        batch_id: Batch to execute
        job_id: Specific job (optional)
        max_jobs: Maximum jobs to run (optional)
        offline_mode: Use fake solver
        ledger_path: Path to ledger database
        
    Returns:
        Execution result
    """
    if not ledger_path:
        ledger_path = Path('runner_data/ledger.db')
    
    db = GenericRunnerDB(ledger_path)
    engine = GenericExecutionEngine(db)
    
    return engine.run_batch(
        batch_id=batch_id,
        job_id=job_id,
        max_jobs=max_jobs,
        offline_mode=offline_mode
    )


if __name__ == '__main__':
    # Quick test
    print("Generic Execution Engine")
    print(f"V2.1 worker available: {V21_WORKER_AVAILABLE}")
    print(f"psutil available: {V21_AVAILABLE}")
