"""
Integration Tests for Generic Runner Execution Engine

Tests the complete workflow from batch submission to execution.
"""
import json
import pytest
import sys
from pathlib import Path
import tempfile
import shutil

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from generic_runner import GenericGPURunner, GenericRunnerDB, BatchStatus, JobStatus
from execution_engine import GenericExecutionEngine, GPUResourceGate


class TestExecutionEngineIntegration:
    """Test complete batch execution workflow."""
    
    def setup_method(self):
        """Create temporary workspace for each test."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.ledger_path = self.temp_dir / 'test_ledger.db'
        self.data_dir = self.temp_dir / 'data'
        self.data_dir.mkdir()
        
    def teardown_method(self):
        """Clean up temporary workspace."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
    
    def create_test_fsp(self, name: str) -> Path:
        """Create a dummy FSP file."""
        fsp_path = self.data_dir / f'{name}.fsp'
        fsp_path.write_text('DUMMY_FSP_CONTENT', encoding='utf-8')
        return fsp_path
    
    def create_test_manifest(self, batch_id: str, job_count: int = 2) -> Path:
        """Create a test batch manifest."""
        jobs = []
        for i in range(job_count):
            fsp = self.create_test_fsp(f'{batch_id}_job_{i}')
            output_dir = self.data_dir / f'{batch_id}_output_{i}'
            
            jobs.append({
                'job_id': f'JOB_{i:03d}',
                'attempt_id': 'attempt_001',
                'input_fsp': str(fsp),
                'output_dir': str(output_dir),
                'solver_backend': 'lumerical_fdtd_gpu',
                'metadata': {'test': True}
            })
        
        manifest = {
            'batch_id': batch_id,
            'project_id': 'TEST_PROJECT',
            'batch_type': 'fdtd_3d',
            'jobs': jobs,
            'max_entries': job_count,
            'recovery_strategy': 'fail_closed',
            'authorization': {
                'granted_by': 'test_user',
                'granted_at': '2026-10-14T00:00:00Z'
            }
        }
        
        manifest_path = self.data_dir / f'{batch_id}_manifest.json'
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        
        return manifest_path
    
    def test_batch_submission_and_validation(self):
        """Test batch submission workflow."""
        db = GenericRunnerDB(self.ledger_path)
        runner = GenericGPURunner(config_path=None)
        runner.db = db  # Override with test database
        
        # Create manifest
        manifest_path = self.create_test_manifest('TEST_BATCH_001', job_count=3)
        
        # Validate
        is_valid, errors = runner.validate_batch(manifest_path)
        assert is_valid, f"Validation failed: {errors}"
        
        # Submit
        result = runner.submit_batch(manifest_path)
        assert result['success']
        assert result['batch_id'] == 'TEST_BATCH_001'
        assert result['total_jobs'] == 3
        
        # Check status
        status = runner.batch_status('TEST_BATCH_001')
        assert status is not None
        assert status['total_jobs'] == 3
        assert status['completed_jobs'] == 0
        assert status['status'] == BatchStatus.SUBMITTED.value
    
    def test_offline_execution_single_job(self):
        """Test offline execution of a single job."""
        db = GenericRunnerDB(self.ledger_path)
        runner = GenericGPURunner(config_path=None)
        runner.db = db
        
        # Submit batch
        manifest_path = self.create_test_manifest('EXEC_TEST_001', job_count=1)
        runner.submit_batch(manifest_path)
        
        # Execute
        engine = GenericExecutionEngine(db)
        result = engine.run_batch('EXEC_TEST_001', offline_mode=True)
        
        assert result['success']
        assert result['jobs_executed'] == 1
        assert result['jobs_failed'] == 0
        assert len(result['executed']) == 1
        
        # Verify job completed
        status = runner.batch_status('EXEC_TEST_001')
        assert status['completed_jobs'] == 1
        assert status['entered_jobs'] == 1
    
    def test_offline_execution_multiple_jobs(self):
        """Test serial execution of multiple jobs."""
        db = GenericRunnerDB(self.ledger_path)
        runner = GenericGPURunner(config_path=None)
        runner.db = db
        
        # Submit batch with 5 jobs
        manifest_path = self.create_test_manifest('EXEC_TEST_002', job_count=5)
        runner.submit_batch(manifest_path)
        
        # Execute all
        engine = GenericExecutionEngine(db)
        result = engine.run_batch('EXEC_TEST_002', offline_mode=True)
        
        assert result['success']
        assert result['jobs_executed'] == 5
        assert result['jobs_failed'] == 0
        
        # Verify all completed
        status = runner.batch_status('EXEC_TEST_002')
        assert status['completed_jobs'] == 5
        assert status['entered_jobs'] == 5
    
    def test_solver_entered_no_replay(self):
        """Test that solver_entered prevents replay."""
        db = GenericRunnerDB(self.ledger_path)
        runner = GenericGPURunner(config_path=None)
        runner.db = db
        
        # Submit and execute once
        manifest_path = self.create_test_manifest('NO_REPLAY_001', job_count=1)
        runner.submit_batch(manifest_path)
        
        engine = GenericExecutionEngine(db)
        result1 = engine.run_batch('NO_REPLAY_001', offline_mode=True)
        assert result1['jobs_executed'] == 1
        
        # Try to execute again - should find no pending jobs
        result2 = engine.run_batch('NO_REPLAY_001', offline_mode=True)
        assert result2['jobs_executed'] == 0
        
        # Verify entered count stayed at 1
        status = runner.batch_status('NO_REPLAY_001')
        assert status['entered_jobs'] == 1
        assert status['completed_jobs'] == 1
    
    def test_max_jobs_limit(self):
        """Test max_jobs execution limit."""
        db = GenericRunnerDB(self.ledger_path)
        runner = GenericGPURunner(config_path=None)
        runner.db = db
        
        # Submit batch with 10 jobs
        manifest_path = self.create_test_manifest('LIMIT_TEST_001', job_count=10)
        runner.submit_batch(manifest_path)
        
        # Execute only 3 jobs
        engine = GenericExecutionEngine(db)
        result = engine.run_batch('LIMIT_TEST_001', max_jobs=3, offline_mode=True)
        
        assert result['jobs_executed'] == 3
        
        # Verify only 3 completed
        status = runner.batch_status('LIMIT_TEST_001')
        assert status['completed_jobs'] == 3
        assert status['entered_jobs'] == 3
        
        # Execute 3 more
        result2 = engine.run_batch('LIMIT_TEST_001', max_jobs=3, offline_mode=True)
        assert result2['jobs_executed'] == 3
        
        # Verify total 6 completed
        status = runner.batch_status('LIMIT_TEST_001')
        assert status['completed_jobs'] == 6
    
    def test_cross_batch_isolation(self):
        """Test that different batches don't interfere."""
        db = GenericRunnerDB(self.ledger_path)
        runner = GenericGPURunner(config_path=None)
        runner.db = db
        
        # Submit two batches
        manifest_a = self.create_test_manifest('BATCH_A', job_count=2)
        manifest_b = self.create_test_manifest('BATCH_B', job_count=2)
        
        runner.submit_batch(manifest_a)
        runner.submit_batch(manifest_b)
        
        # Execute batch A
        engine = GenericExecutionEngine(db)
        result_a = engine.run_batch('BATCH_A', offline_mode=True)
        assert result_a['jobs_executed'] == 2
        
        # Verify batch B unaffected
        status_b = runner.batch_status('BATCH_B')
        assert status_b['completed_jobs'] == 0
        assert status_b['entered_jobs'] == 0
        
        # Execute batch B
        result_b = engine.run_batch('BATCH_B', offline_mode=True)
        assert result_b['jobs_executed'] == 2
        
        # Verify both complete and isolated
        status_a = runner.batch_status('BATCH_A')
        status_b = runner.batch_status('BATCH_B')
        
        assert status_a['completed_jobs'] == 2
        assert status_a['entered_jobs'] == 2
        assert status_b['completed_jobs'] == 2
        assert status_b['entered_jobs'] == 2
    
    def test_resource_gate_check(self):
        """Test GPU resource gate functionality."""
        gate = GPUResourceGate()
        result = gate.check()
        
        # Should return a valid status dict
        assert 'status' in result
        assert 'message' in result
        assert 'processes' in result
        assert 'conflicts' in result
        
        # Status should be one of the valid values
        valid_statuses = {'clear', 'gui_only', 'scientific_active', 
                         'resource_conflict', 'unknown'}
        assert result['status'] in valid_statuses
    
    def test_artifact_creation(self):
        """Test that offline execution creates artifacts."""
        db = GenericRunnerDB(self.ledger_path)
        runner = GenericGPURunner(config_path=None)
        runner.db = db
        
        # Submit and execute
        manifest_path = self.create_test_manifest('ARTIFACT_TEST', job_count=1)
        runner.submit_batch(manifest_path)
        
        engine = GenericExecutionEngine(db)
        result = engine.run_batch('ARTIFACT_TEST', offline_mode=True)
        
        assert result['success']
        
        # Check artifacts were created
        job_result = result['executed'][0]
        fsp_artifact = Path(job_result['artifacts']['fsp'])
        h5_artifact = Path(job_result['artifacts']['h5'])
        
        assert fsp_artifact.exists()
        assert h5_artifact.exists()
        assert 'OFFLINE_SOLVER_FIXTURE' in fsp_artifact.read_text()


def test_cli_integration(tmp_path):
    """Test CLI commands work end-to-end."""
    import subprocess
    
    # Create test manifest
    fsp = tmp_path / 'test.fsp'
    fsp.write_text('DUMMY', encoding='utf-8')
    
    manifest = {
        'batch_id': 'CLI_TEST',
        'project_id': 'CLI_PROJECT',
        'batch_type': 'fdtd_3d',
        'jobs': [{
            'job_id': 'JOB_001',
            'attempt_id': 'attempt_001',
            'input_fsp': str(fsp),
            'output_dir': str(tmp_path / 'output'),
            'solver_backend': 'lumerical_fdtd_gpu'
        }],
        'max_entries': 1
    }
    
    manifest_path = tmp_path / 'manifest.json'
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f)
    
    # Test validate
    result = subprocess.run(
        [sys.executable, 'cli.py', 'submit_batch', '--manifest', str(manifest_path), '--validate-only'],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent
    )
    assert result.returncode == 0
    assert 'Validation passed' in result.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
