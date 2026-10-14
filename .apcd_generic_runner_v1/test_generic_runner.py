"""
Test Suite for Generic GPU Runner - Fixed for Windows permissions

Cross-batch integration tests (A/B/C) and resource gate classification.
"""

import json
import os
from pathlib import Path
import sqlite3


def test_batch_manifest_validation():
    """Test batch manifest validation logic."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from generic_runner import GenericBatchManifest
    
    # Valid manifest
    valid_data = {
        "batch_id": "TEST_BATCH_001",
        "project_id": "test_project",
        "jobs": [
            {
                "job_id": "JOB_001",
                "attempt_id": "attempt_001",
                "input_fsp": "test.fsp",
                "output_dir": "/tmp/out"
            }
        ],
        "max_entries": 1
    }
    
    manifest = GenericBatchManifest(**valid_data)
    is_valid, errors = manifest.validate()
    assert is_valid, f"Valid manifest failed: {errors}"
    
    # Invalid batch_id
    invalid_data = valid_data.copy()
    invalid_data["batch_id"] = "invalid batch!"
    manifest = GenericBatchManifest(**invalid_data)
    is_valid, errors = manifest.validate()
    assert not is_valid, "Invalid batch_id should fail"
    
    # Missing job_id
    invalid_data = valid_data.copy()
    invalid_data["jobs"] = [{"attempt_id": "attempt_001"}]
    manifest = GenericBatchManifest(**invalid_data)
    is_valid, errors = manifest.validate()
    assert not is_valid, "Missing job_id should fail"


def test_cross_batch_isolation():
    """Test that multiple batches can coexist with isolated data."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from generic_runner import GenericRunnerDB, GenericBatchManifest
    
    test_dir = Path(__file__).parent / 'test_temp'
    test_dir.mkdir(exist_ok=True)
    db_path = test_dir / "test_isolation.db"
    
    try:
        # Clean up old db
        if db_path.exists():
            db_path.unlink()
        
        db = GenericRunnerDB(db_path)
        
        # Register Batch A (DOE56-like, HOLD)
        batch_a = GenericBatchManifest(
            batch_id="DOE56_TEST",
            project_id="coupling_ml",
            jobs=[{"job_id": "G001", "attempt_id": "attempt_001", 
                   "input_fsp": "g001.fsp", "output_dir": "/tmp/a"}],
            max_entries=1
        )
        
        # Register Batch B (DIAG2-like, independent)
        batch_b = GenericBatchManifest(
            batch_id="DIAG2_TEST",
            project_id="coupling_ml",
            jobs=[{"job_id": "A1", "attempt_id": "attempt_001",
                   "input_fsp": "a1.fsp", "output_dir": "/tmp/b"}],
            max_entries=1
        )
        
        # Register Batch C (new test batch)
        batch_c = GenericBatchManifest(
            batch_id="NEW_TEST_BATCH",
            project_id="mdc_planewave",
            jobs=[{"job_id": "T450", "attempt_id": "attempt_001",
                   "input_fsp": "t450.fsp", "output_dir": "/tmp/c"}],
            max_entries=1
        )
        
        # All should register successfully
        assert db.register_batch(batch_a, "sha_a"), "Batch A failed"
        assert db.register_batch(batch_b, "sha_b"), "Batch B failed"
        assert db.register_batch(batch_c, "sha_c"), "Batch C failed"
        
        # Verify isolation
        status_a = db.get_batch_status("DOE56_TEST")
        status_b = db.get_batch_status("DIAG2_TEST")
        status_c = db.get_batch_status("NEW_TEST_BATCH")
        
        assert status_a is not None
        assert status_b is not None
        assert status_c is not None
        
        assert status_a['total_jobs'] == 1
        assert status_b['total_jobs'] == 1
        assert status_c['total_jobs'] == 1
        
        # List all batches
        all_batches = db.list_batches()
        assert len(all_batches) == 3
        
        print(f"  Registered 3 independent batches: A, B, C")
        print(f"  Batch isolation verified")
        
    finally:
        # Cleanup
        if db_path.exists():
            db_path.unlink()


def test_no_replay_enforcement():
    """Test that duplicate job entries are prevented."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from generic_runner import GenericRunnerDB, GenericBatchManifest
    
    test_dir = Path(__file__).parent / 'test_temp'
    test_dir.mkdir(exist_ok=True)
    db_path = test_dir / "test_replay.db"
    
    try:
        if db_path.exists():
            db_path.unlink()
        
        db = GenericRunnerDB(db_path)
        
        batch = GenericBatchManifest(
            batch_id="NO_REPLAY_TEST",
            project_id="test",
            jobs=[{"job_id": "JOB_001", "attempt_id": "attempt_001",
                   "input_fsp": "test.fsp", "output_dir": "/tmp"}],
            max_entries=1
        )
        
        # First registration should succeed
        assert db.register_batch(batch, "sha1")
        
        # Second registration should fail (batch_id uniqueness)
        assert not db.register_batch(batch, "sha2")
        
        print(f"  No replay constraint enforced")
        
    finally:
        if db_path.exists():
            db_path.unlink()


def test_resource_gate_classification():
    """Test resource gate classification logic."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from resource_gate import GPUResourceGate, ResourceGateStatus
    
    gate = GPUResourceGate()
    status, details = gate.check_resources()
    
    # Status should be one of the defined values
    assert isinstance(status, ResourceGateStatus)
    
    # Details should contain evidence
    assert 'evidence' in details
    assert 'message' in details
    
    print(f"  Resource gate status: {status.value}")
    print(f"  Message: {details['message']}")
    
    # If GUI_ONLY, should not block
    if status == ResourceGateStatus.GUI_ONLY:
        print(f"  GUI detected but NOT blocking")
    
    # If SCIENTIFIC_ACTIVE, should block
    if status == ResourceGateStatus.SCIENTIFIC_ACTIVE:
        print(f"  Active solver detected - BLOCKING")
    
    if status == ResourceGateStatus.CLEAR:
        print(f"  No conflicts - CLEAR to proceed")


def test_batch_submission_flow():
    """Test complete batch submission flow."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from generic_runner import GenericGPURunner
    
    test_dir = Path(__file__).parent / 'test_temp'
    test_dir.mkdir(exist_ok=True)
    
    # Create temporary config
    config_path = test_dir / "config.json"
    config_path.write_text(json.dumps({
        'ledger_path': str(test_dir / 'ledger.db'),
        'gpu_platform_version': 'v2.1'
    }), encoding='utf-8')
    
    # Create temporary manifest
    manifest_path = test_dir / "batch.json"
    fsp_path = test_dir / "test.fsp"
    fsp_path.write_text("dummy fsp", encoding='utf-8')
    
    manifest_path.write_text(json.dumps({
        "batch_id": "SUBMIT_TEST",
        "project_id": "test",
        "jobs": [
            {
                "job_id": "JOB_001",
                "attempt_id": "attempt_001",
                "input_fsp": str(fsp_path),
                "output_dir": str(test_dir)
            }
        ],
        "max_entries": 1
    }), encoding='utf-8')
    
    try:
        runner = GenericGPURunner(config_path)
        
        # Validate only
        is_valid, errors = runner.validate_batch(manifest_path)
        assert is_valid, f"Validation failed: {errors}"
        
        # Dry run
        result = runner.submit_batch(manifest_path, dry_run=True)
        assert result['success']
        assert 'Dry run' in result['message']
        
        # Actual submission
        result = runner.submit_batch(manifest_path, dry_run=False)
        assert result['success']
        assert result['batch_id'] == 'SUBMIT_TEST'
        
        # Check status
        status = runner.batch_status('SUBMIT_TEST')
        assert status is not None
        assert status['total_jobs'] == 1
        assert status['entered_jobs'] == 0  # Not yet executed
        
        print(f"  Batch submission flow complete")
        print(f"  Batch ID: {status['batch_id']}")
        print(f"  Jobs: {status['total_jobs']}, Entered: {status['entered_jobs']}")
        
    finally:
        # Cleanup
        for f in [config_path, manifest_path, fsp_path, test_dir / 'ledger.db']:
            if f.exists():
                try:
                    f.unlink()
                except:
                    pass


if __name__ == '__main__':
    print("Running Generic GPU Runner Tests\n")
    print("="*60)
    
    print("\nTest 1: Batch Manifest Validation")
    test_batch_manifest_validation()
    print("  -> PASS")
    
    print("\nTest 2: Cross-Batch Isolation (A/B/C)")
    test_cross_batch_isolation()
    print("  -> PASS")
    
    print("\nTest 3: No Replay Enforcement")
    test_no_replay_enforcement()
    print("  -> PASS")
    
    print("\nTest 4: Resource Gate Classification")
    test_resource_gate_classification()
    print("  -> PASS")
    
    print("\nTest 5: Batch Submission Flow")
    test_batch_submission_flow()
    print("  -> PASS")
    
    print("\n" + "="*60)
    print("All 5 tests passed!")
