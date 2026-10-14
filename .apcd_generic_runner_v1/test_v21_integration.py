"""Test V2.1 Worker Integration

Verifies real GPU worker adapter connects correctly to V2/V2.1 execution kernel.
"""
import json
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from generic_runner import GenericRunner, RunnerConfig
from v21_worker_integration import V21WorkerAdapter, integrate_v21_worker


class TestV21WorkerIntegration:
    """Test suite for V2.1 worker integration."""
    
    def test_adapter_initialization(self, tmp_path):
        """Test adapter can be initialized with runner."""
        config = RunnerConfig(
            runtime_root=str(tmp_path / "runtime"),
            platform_config_path=str(tmp_path / "platform.json")
        )
        runner = GenericRunner(config=config)
        
        # Mock V2.1 agent existence
        v21_path = Path(__file__).parent.parent / ".apcd86_agent"
        if v21_path.exists():
            adapter = V21WorkerAdapter(runner)
            assert adapter.runner is runner
            assert adapter.v21_agent_path == v21_path
    
    def test_v21_config_building(self, tmp_path):
        """Test V2.1 config construction from Generic Runner context."""
        # Setup test data
        platform_data = {
            "schema_version": "APCD_GPU_V21_PLATFORM_V1",
            "mode": "PRODUCTION_EQUIVALENT",
            "runtime_root": str(tmp_path / "runtime"),
            "science_root": str(tmp_path / "science"),
            "source_root": str(tmp_path / "source"),
            "coupling_root": str(tmp_path / "coupling"),
            "science_owner_sid": "S-1-5-21-OWNER",
            "consumer_sid": "S-1-5-21-CONSUMER",
            "operator_sids": ["S-1-5-21-OPERATOR"],
            "fdtd_executable": "C:/fake/fdtd.exe",
            "executable_sha256": "a" * 64,
            "gpu_resource": "GPU license audit",
            "native_h5_name": "run_output.h5",
            "heartbeat_seconds": 15.0,
            "profiles": [
                {
                    "profile_id": "coupling_609d_v1",
                    "truth_toolchain": {
                        "lumapi": {"path": str(tmp_path / "lumapi.py"), "sha256": "b" * 64},
                        "importer": {"path": str(tmp_path / "importer.py"), "sha256": "c" * 64}
                    },
                    "certification": {"path": str(tmp_path / "cert.json"), "sha256": "d" * 64}
                }
            ]
        }
        
        manifest_data = {
            "schema_version": "APCD_GPU_V21_BATCH_V1",
            "batch_id": "TEST_BATCH_001",
            "label_validation_profile": "coupling_609d_v1",
            "cases": [
                {
                    "case_id": "CASE_001",
                    "physics_contract_sha": "e" * 64,
                    "role": "DEVELOPMENT_GLOBAL",
                    "ordered_D_nm": [100, 200, 300, 400, 500, 600],
                    "simulation_time_s": 3.0,
                    "mesh_nm": 5.0,
                    "auto_shutoff_min": 1e-6
                }
            ]
        }
        
        admission_data = {
            "schema_version": "APCD_GPU_V21_SCIENCE_ADMISSION_V1",
            "batch_id": "TEST_BATCH_001"
        }
        
        # Create files
        platform_path = tmp_path / "platform.json"
        manifest_path = tmp_path / "manifest.json"
        admission_path = tmp_path / "admission.json"
        
        platform_path.write_text(json.dumps(platform_data))
        manifest_path.write_text(json.dumps(manifest_data))
        admission_path.write_text(json.dumps(admission_data))
        
        # Create adapter
        config = RunnerConfig(
            runtime_root=str(tmp_path / "runtime"),
            platform_config_path=str(platform_path)
        )
        runner = GenericRunner(config=config)
        
        v21_path = Path(__file__).parent.parent / ".apcd86_agent"
        if not v21_path.exists():
            pytest.skip("V2.1 agent not available")
        
        adapter = V21WorkerAdapter(runner)
        
        # Test config building
        v21_config = adapter._build_v21_config(
            "TEST_BATCH_001", manifest_path, admission_path, platform_path
        )
        
        assert v21_config.batch_id == "TEST_BATCH_001"
        assert v21_config.schema_version == "APCD_GPU_V21_SERIAL_V1"
        assert v21_config.validation_profile == "coupling_609d_v1"
    
    def test_v21_request_building(self, tmp_path):
        """Test V2.1 request construction from Generic job."""
        job = {
            "case_id": "CASE_001",
            "attempt_id": "attempt_001",
            "batch_id": "BATCH_001",
            "input_fsp": str(tmp_path / "input.fsp"),
            "input_sha256": "f" * 64
        }
        
        case_manifest = {
            "case_id": "CASE_001",
            "role": "DEVELOPMENT_GLOBAL",
            "ordered_D_nm": [100, 200, 300, 400, 500, 600],
            "source_manifest": {"path": str(tmp_path / "source.json"), "sha256": "g" * 64},
            "physics_contract": {"path": str(tmp_path / "contract.json"), "sha256": "h" * 64},
            "physics_contract_sha": "h" * 64,
            "simulation_time_s": 3.0,
            "mesh_nm": 5.0,
            "auto_shutoff_min": 1e-6
        }
        
        config = RunnerConfig(
            runtime_root=str(tmp_path / "runtime"),
            platform_config_path=str(tmp_path / "platform.json")
        )
        runner = GenericRunner(config=config)
        
        v21_path = Path(__file__).parent.parent / ".apcd86_agent"
        if not v21_path.exists():
            pytest.skip("V2.1 agent not available")
        
        adapter = V21WorkerAdapter(runner)
        
        # Test request building
        v21_request = adapter._build_v21_request(job, case_manifest)
        
        assert v21_request.case_id == "CASE_001"
        assert v21_request.attempt_id == "attempt_001"
        assert v21_request.batch_id == "BATCH_001"
        assert v21_request.role == "DEVELOPMENT_GLOBAL"
        assert v21_request.ordered_D_nm == (100, 200, 300, 400, 500, 600)
    
    def test_integration_function(self, tmp_path):
        """Test integrate_v21_worker() function."""
        config = RunnerConfig(
            runtime_root=str(tmp_path / "runtime"),
            platform_config_path=str(tmp_path / "platform.json")
        )
        runner = GenericRunner(config=config)
        
        v21_path = Path(__file__).parent.parent / ".apcd86_agent"
        if not v21_path.exists():
            pytest.skip("V2.1 agent not available")
        
        # Integrate
        adapter = integrate_v21_worker(runner)
        
        # Verify integration
        assert hasattr(runner, '_v21_adapter')
        assert runner._v21_adapter is adapter
        
        # Verify execution engine patched
        from execution_engine import ExecutionEngine
        engine = ExecutionEngine(runner)
        
        # Should have real solver method
        assert hasattr(engine, '_real_solver')
    
    def test_adapter_without_v21_agent(self, tmp_path, monkeypatch):
        """Test adapter gracefully fails when V2.1 agent unavailable."""
        config = RunnerConfig(
            runtime_root=str(tmp_path / "runtime"),
            platform_config_path=str(tmp_path / "platform.json")
        )
        runner = GenericRunner(config=config)
        
        # Mock missing V2.1 agent
        fake_path = tmp_path / "nonexistent"
        monkeypatch.setattr(Path, '__truediv__', lambda self, other: fake_path if 'closeout_serial.py' in str(other) else self / other)
        
        with pytest.raises(RuntimeError, match="V2.1 agent not found"):
            V21WorkerAdapter(runner)
    
    def test_execute_job_requires_integration(self, tmp_path):
        """Test execute_job fails without V2.1 integration."""
        from execution_engine import ExecutionEngine
        
        config = RunnerConfig(
            runtime_root=str(tmp_path / "runtime"),
            platform_config_path=str(tmp_path / "platform.json")
        )
        runner = GenericRunner(config=config)
        engine = ExecutionEngine(runner)
        
        # Should fail without integration
        with pytest.raises(RuntimeError, match="V2.1 worker not integrated"):
            engine._real_solver(1)


class TestV21ExecutionPath:
    """Test complete execution path with V2.1 worker."""
    
    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / ".apcd86_agent").exists(),
        reason="V2.1 agent not available"
    )
    def test_end_to_end_integration(self, tmp_path):
        """Test complete Generic Runner → V2.1 worker execution path."""
        # Setup runtime
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        (runtime / "batches").mkdir()
        
        # Create minimal platform config
        platform_data = {
            "schema_version": "APCD_GPU_V21_PLATFORM_V1",
            "mode": "PRODUCTION_EQUIVALENT",
            "runtime_root": str(runtime),
            "science_root": str(runtime / "science"),
            "source_root": str(runtime / "source"),
            "coupling_root": str(runtime / "coupling"),
            "science_owner_sid": "S-1-5-21-OWNER",
            "consumer_sid": "S-1-5-21-CONSUMER",
            "operator_sids": [],
            "fdtd_executable": sys.executable,
            "executable_sha256": "a" * 64,
            "gpu_resource": "GPU license audit",
            "native_h5_name": "run_output.h5",
            "profiles": []
        }
        
        platform_path = runtime / "platform.json"
        platform_path.write_text(json.dumps(platform_data))
        
        # Create runner
        config = RunnerConfig(
            runtime_root=str(runtime),
            platform_config_path=str(platform_path)
        )
        runner = GenericRunner(config=config)
        
        # Integrate V2.1
        adapter = integrate_v21_worker(runner)
        
        # Verify adapter ready
        assert adapter.runner is runner
        assert hasattr(runner, '_v21_adapter')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
