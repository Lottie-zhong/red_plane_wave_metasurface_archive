"""Real GPU V2.1 Worker Integration

Connects Generic Runner to the proven V2/V2.1 Lumerical FDTD execution kernel.
"""
import json
import sys
import importlib.util
from pathlib import Path
from typing import Any, Dict


class V21WorkerAdapter:
    """Adapter between Generic Runner and V2.1 serial worker.
    
    Responsibilities:
    - Convert Generic Job to V2.1 Request
    - Setup V2.1 SerialConfig with Platform/Profile
    - Invoke proven run_serial_case()
    - Return execution evidence
    
    Does NOT:
    - Replace GPU solver backend
    - Modify V2.1 execution semantics
    - Create second ledger system
    """
    
    def __init__(self, runner):
        """Initialize adapter with Generic Runner instance."""
        self.runner = runner
        self.config = runner.config
        self.v21_agent_path = Path(__file__).parent.parent / '.apcd86_agent'
        
        # Validate V2.1 agent availability
        if not (self.v21_agent_path / 'closeout_serial.py').exists():
            raise RuntimeError(f"V2.1 agent not found at {self.v21_agent_path}")
        
        # Dynamically load V2.1 modules
        self._load_v21_modules()
    
    def _load_v21_modules(self):
        """Dynamically load V2.1 modules without package structure."""
        # Add agent path to sys.path
        agent_path_str = str(self.v21_agent_path)
        if agent_path_str not in sys.path:
            sys.path.insert(0, agent_path_str)
        
        # Import V2.1 modules
        try:
            import closeout_serial
            import closeout_general
            import artifacts
            import config as v21_config
            import ledger as v21_ledger
            
            self.v21_serial = closeout_serial
            self.v21_general = closeout_general
            self.v21_artifacts = artifacts
            self.v21_config = v21_config
            self.v21_ledger = v21_ledger
            
        except ImportError as e:
            raise RuntimeError(f"Failed to load V2.1 modules: {e}")
    
    def _build_v21_config(self, batch_id: str, manifest_path: Path, 
                          admission_path: Path, platform_path: Path):
        """Build V2.1 GeneralConfig from Generic Runner context."""
        
        # Read manifests
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        admission = json.loads(admission_path.read_text(encoding='utf-8'))
        platform = json.loads(platform_path.read_text(encoding='utf-8'))
        
        # Get profile
        profile_id = manifest['label_validation_profile']
        profile_data = next((p for p in platform['profiles'] if p['profile_id'] == profile_id), None)
        if not profile_data:
            raise ValueError(f"Profile {profile_id} not found in platform")
        
        # Build truth toolchain pins using V2.1 Pin class
        Pin = self.v21_serial.Pin
        truth_toolchain = {}
        for key, pin_data in profile_data['truth_toolchain'].items():
            truth_toolchain[key] = Pin(path=pin_data['path'], sha256=pin_data['sha256'])
        
        # Get physics contract SHA from first case
        first_case = manifest['cases'][0]
        contract_sha = first_case['physics_contract_sha']
        
        # Build V2.1 GeneralConfig using loaded classes
        GeneralConfig = self.v21_general.GeneralConfig
        
        v21_config_data = {
            'schema_version': 'APCD_GPU_V21_SERIAL_V1',
            'mode': platform['mode'],
            'runtime_root': platform['runtime_root'],
            'coupling_ledger': str(Path(platform['science_root']) / batch_id / 'ledger.json'),
            'queue': {
                'path': str(manifest_path),
                'sha256': self._sha256(str(manifest_path))
            },
            'release': {
                'path': str(admission_path),
                'sha256': self._sha256(str(admission_path))
            },
            'fdtd_executable': platform['fdtd_executable'],
            'executable_sha256': platform['executable_sha256'],
            'gpu_resource': platform['gpu_resource'],
            'native_h5_name': platform['native_h5_name'],
            'physical_contract_sha256': contract_sha,
            'heartbeat_seconds': platform.get('heartbeat_seconds', 15.0),
            'slots': platform.get('slots', 1),
            'automatic_replays': platform.get('automatic_replays', 0),
            'batch_id': batch_id,
            'batch_manifest': {
                'path': str(manifest_path),
                'sha256': self._sha256(str(manifest_path))
            },
            'science_admission': {
                'path': str(admission_path),
                'sha256': self._sha256(str(admission_path))
            },
            'science_control': {
                'path': str(Path(platform['science_root']) / batch_id / 'control.json'),
                'sha256': self._sha256(str(Path(platform['science_root']) / batch_id / 'control.json'))
            },
            'platform': platform,
            'truth_toolchain': truth_toolchain,
            'coupling_root': platform['coupling_root'],
            'importer_module': 'k6_v2_pipeline.generic_profile',
            'importer_entrypoint': 'load_authorized_runner_case',
            'label_validator_entrypoint': 'validate_authorized_labels',
            'validation_profile': profile_id
        }
        
        return GeneralConfig(**v21_config_data)
    
    def _sha256(self, path: str) -> str:
        """Calculate SHA256 of file."""
        return self.v21_artifacts.sha256(path)
    
    def _build_v21_request(self, job: Dict[str, Any], case_manifest: Dict[str, Any]):
        """Convert Generic Job to V2.1 GeneralRequest."""
        
        GeneralRequest = self.v21_general.GeneralRequest
        case_id = job['case_id']
        
        request_data = {
            'case_id': case_id,
            'attempt_id': job['attempt_id'],
            'role': case_manifest['role'],
            'ordered_D_nm': tuple(case_manifest['ordered_D_nm']),
            'pre_fsp': job['input_fsp'],
            'pre_fsp_sha256': job['input_sha256'],
            'source_manifest': {
                'path': case_manifest['source_manifest']['path'],
                'sha256': case_manifest['source_manifest']['sha256']
            },
            'physical_contract': {
                'path': case_manifest['physics_contract']['path'],
                'sha256': case_manifest['physics_contract']['sha256']
            },
            'physical_contract_sha256': case_manifest['physics_contract_sha'],
            'config_sha256': '',  # Will be filled after config built
            'batch_id': job['batch_id'],
            'simulation_time_s': case_manifest['simulation_time_s'],
            'mesh_nm': case_manifest['mesh_nm'],
            'auto_shutoff_min': case_manifest['auto_shutoff_min']
        }
        
        return GeneralRequest(**request_data)
    
    def execute_job(self, job_id: int) -> Dict[str, Any]:
        """Execute a job using V2.1 worker.
        
        Args:
            job_id: Generic Runner job ID
            
        Returns:
            Execution evidence from V2.1 worker
            
        Raises:
            RuntimeError: Job not found or invalid state
            Exception: V2.1 worker errors
        """
        with self.runner.db.transaction() as conn:
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            )
            job_row = cursor.fetchone()
            
            if not job_row:
                raise RuntimeError(f"Job {job_id} not found")
            
            # Convert row to dict
            job = dict(job_row)
            
            if job['status'] not in ['QUEUED', 'RESOURCE_WAIT']:
                raise RuntimeError(f"Job {job_id} not executable: {job['status']}")
            
            # Get batch
            cursor = conn.execute(
                "SELECT * FROM batches WHERE batch_id = ?", (job['batch_id'],)
            )
            batch_row = cursor.fetchone()
            
            if not batch_row:
                raise RuntimeError(f"Batch {job['batch_id']} not found")
            
            batch = dict(batch_row)
            
            # Read manifest
            manifest_path = Path(batch['manifest_path'])
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            
            # Find case in manifest
            case_manifest = next(
                (c for c in manifest['cases'] if c['case_id'] == job['case_id']),
                None
            )
            if not case_manifest:
                raise RuntimeError(f"Case {job['case_id']} not in manifest")
        
        # Build V2.1 components
        admission_path = Path(batch['admission_path']) if batch.get('admission_path') else None
        platform_path = Path(self.config.platform_config_path)
        
        if not admission_path or not admission_path.exists():
            raise RuntimeError(f"Science admission required for batch {job['batch_id']}")
        
        v21_config = self._build_v21_config(
            job['batch_id'], manifest_path, admission_path, platform_path
        )
        v21_request = self._build_v21_request(job, case_manifest)
        
        # Fill config SHA
        v21_request.config_sha256 = v21_config.sha256
        
        # Create V2.1 ledger
        SerialLedger = self.v21_serial.SerialLedger
        ledger_path = Path(v21_config.runtime_root) / 'v21_ledger.sqlite3'
        v21_ledger = SerialLedger(ledger_path)
        
        # Register request if needed
        v21_ledger.register(v21_request, v21_config)
        
        # Create backend and validator
        ProductionNativeBackend = self.v21_serial.ProductionNativeBackend
        NativeTruthValidator = self.v21_serial.NativeTruthValidator
        
        backend = ProductionNativeBackend(v21_config.fdtd_executable)
        validator = NativeTruthValidator(v21_config.truth_toolchain)
        
        # Execute via V2.1 worker
        run_serial_case = self.v21_serial.run_serial_case
        evidence = run_serial_case(
            config=v21_config,
            request=v21_request,
            ledger=v21_ledger,
            backend=backend,
            validator=validator
        )
        
        return evidence


def integrate_v21_worker(runner):
    """Integrate V2.1 worker into Generic Runner.
    
    Replaces the _real_solver() placeholder with actual V2.1 worker adapter.
    """
    adapter = V21WorkerAdapter(runner)
    runner._v21_adapter = adapter
    
    # Replace _real_solver in execution engine
    from . import execution_engine
    
    def real_solver_v21(engine, job_id: int) -> Dict[str, Any]:
        """Real solver using V2.1 worker adapter."""
        return adapter.execute_job(job_id)
    
    # Monkey-patch execution engine
    execution_engine.ExecutionEngine._real_solver = real_solver_v21
    
    return adapter
