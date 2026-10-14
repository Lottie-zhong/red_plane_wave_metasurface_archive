"""
Generic GPU FDTD Runner - Core Implementation with workspace-relative defaults

Transforms V2.1 platform into reusable, batch-agnostic runner.
Reuses validated GPU solver backend from 309 PASS candidate.
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import os


class BatchStatus(Enum):
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    HOLD = "hold"


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ResourceGateStatus(Enum):
    CLEAR = "clear"
    GUI_ONLY = "gui_only"
    SCIENTIFIC_ACTIVE = "scientific_active"
    RESOURCE_CONFLICT = "resource_conflict"
    UNKNOWN = "unknown"


@dataclass
class GenericBatchManifest:
    batch_id: str
    project_id: str
    jobs: List[Dict[str, Any]]
    max_entries: int
    batch_type: str = "fdtd_3d"
    recovery_strategy: str = "fail_closed"
    authorization: Optional[Dict[str, Any]] = None
    
    @classmethod
    def from_file(cls, path: Path) -> 'GenericBatchManifest':
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls(**data)
    
    def validate(self) -> tuple[bool, List[str]]:
        """Validate batch manifest structure and constraints."""
        errors = []
        
        # Check batch_id uniqueness will be handled by database
        if not self.batch_id or not self.batch_id.replace('_', '').replace('-', '').isalnum():
            errors.append(f"Invalid batch_id: {self.batch_id}")
        
        if not self.project_id:
            errors.append("project_id is required")
        
        if not self.jobs:
            errors.append("jobs list cannot be empty")
        
        if self.max_entries < len(self.jobs):
            errors.append(f"max_entries ({self.max_entries}) < job count ({len(self.jobs)})")
        
        # Validate each job
        job_ids = set()
        for i, job in enumerate(self.jobs):
            if 'job_id' not in job:
                errors.append(f"Job {i}: missing job_id")
                continue
            
            job_id = job['job_id']
            if job_id in job_ids:
                errors.append(f"Duplicate job_id: {job_id}")
            job_ids.add(job_id)
            
            if 'attempt_id' not in job or not job['attempt_id'].startswith('attempt_'):
                errors.append(f"Job {job_id}: invalid or missing attempt_id")
            
            if 'input_fsp' not in job:
                errors.append(f"Job {job_id}: missing input_fsp")
            elif not Path(job['input_fsp']).suffix == '.fsp':
                errors.append(f"Job {job_id}: input_fsp must be .fsp file")
            
            if 'output_dir' not in job:
                errors.append(f"Job {job_id}: missing output_dir")
        
        return len(errors) == 0, errors


class GenericRunnerDB:
    """
    Multi-batch SQLite ledger.
    Extends V2.1 single-batch schema to support multiple independent batches.
    """
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
    
    def _init_schema(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    batch_type TEXT NOT NULL,
                    max_entries INTEGER NOT NULL,
                    recovery_strategy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    authorization_json TEXT,
                    manifest_sha256 TEXT NOT NULL,
                    UNIQUE(batch_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    input_fsp TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    solver_backend TEXT NOT NULL,
                    physics_contract_sha256 TEXT,
                    profile TEXT,
                    status TEXT NOT NULL,
                    queued_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    solver_entered INTEGER DEFAULT 0,
                    truth_valid INTEGER DEFAULT 0,
                    labels_valid INTEGER DEFAULT 0,
                    FOREIGN KEY (batch_id) REFERENCES batches(batch_id),
                    UNIQUE(batch_id, job_id, attempt_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_data TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_batches_status ON batches(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(batch_id, status)
            """)
            
            conn.commit()
        finally:
            conn.close()
    
    def register_batch(self, manifest: GenericBatchManifest, manifest_sha256: str) -> bool:
        """Register a new batch. Returns True if successful."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Check if batch_id already exists
            cursor = conn.execute(
                "SELECT batch_id FROM batches WHERE batch_id = ?",
                (manifest.batch_id,)
            )
            if cursor.fetchone():
                return False  # Already exists
            
            conn.execute("""
                INSERT INTO batches (
                    batch_id, project_id, batch_type, max_entries,
                    recovery_strategy, status, submitted_at,
                    authorization_json, manifest_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                manifest.batch_id,
                manifest.project_id,
                manifest.batch_type,
                manifest.max_entries,
                manifest.recovery_strategy,
                BatchStatus.SUBMITTED.value,
                datetime.utcnow().isoformat(),
                json.dumps(manifest.authorization) if manifest.authorization else None,
                manifest_sha256
            ))
            
            # Register all jobs
            for job in manifest.jobs:
                conn.execute("""
                    INSERT INTO jobs (
                        batch_id, job_id, attempt_id, input_fsp, output_dir,
                        solver_backend, physics_contract_sha256, profile, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    manifest.batch_id,
                    job['job_id'],
                    job['attempt_id'],
                    job['input_fsp'],
                    job['output_dir'],
                    job.get('solver_backend', 'lumerical_fdtd_gpu'),
                    job.get('physics_contract_sha256'),
                    job.get('profile'),
                    JobStatus.PENDING.value
                ))
            
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get batch status with job counts."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("""
                SELECT 
                    b.batch_id, b.project_id, b.status, b.submitted_at,
                    COUNT(j.id) as total_jobs,
                    SUM(CASE WHEN j.status = 'completed' THEN 1 ELSE 0 END) as completed_jobs,
                    SUM(CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END) as failed_jobs,
                    SUM(CASE WHEN j.solver_entered = 1 THEN 1 ELSE 0 END) as entered_jobs
                FROM batches b
                LEFT JOIN jobs j ON b.batch_id = j.batch_id
                WHERE b.batch_id = ?
                GROUP BY b.batch_id
            """, (batch_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            return {
                'batch_id': row[0],
                'project_id': row[1],
                'status': row[2],
                'submitted_at': row[3],
                'total_jobs': row[4],
                'completed_jobs': row[5],
                'failed_jobs': row[6],
                'entered_jobs': row[7]
            }
        finally:
            conn.close()
    
    def list_batches(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all batches, optionally filtered by status."""
        conn = sqlite3.connect(self.db_path)
        try:
            if status_filter:
                cursor = conn.execute("""
                    SELECT batch_id, project_id, status, submitted_at
                    FROM batches
                    WHERE status = ?
                    ORDER BY submitted_at DESC
                """, (status_filter,))
            else:
                cursor = conn.execute("""
                    SELECT batch_id, project_id, status, submitted_at
                    FROM batches
                    ORDER BY submitted_at DESC
                """)
            
            return [
                {
                    'batch_id': row[0],
                    'project_id': row[1],
                    'status': row[2],
                    'submitted_at': row[3]
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()


class GenericGPURunner:
    """
    Generic GPU FDTD Runner.
    Batch-agnostic serial executor reusing V2.1 validated components.
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        # Load configuration
        if config_path and config_path.exists():
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        else:
            self.config = self._default_config()
        
        self.db = GenericRunnerDB(Path(self.config['ledger_path']))
    
    def _default_config(self) -> Dict[str, Any]:
        # Use workspace-relative path for ledger
        workspace = Path(__file__).parent
        return {
            'ledger_path': str(workspace / 'runner_data' / 'ledger.db'),
            'gpu_platform_version': 'v2.1',
            'max_concurrent_gpu_solvers': 1,
            'default_solver_backend': 'lumerical_fdtd_gpu'
        }
    
    def validate_batch(self, manifest_path: Path) -> tuple[bool, List[str]]:
        """Validate batch manifest without submission."""
        try:
            manifest = GenericBatchManifest.from_file(manifest_path)
            is_valid, errors = manifest.validate()
            
            # Additional checks
            if is_valid:
                # Check input FSP files exist
                for job in manifest.jobs:
                    fsp_path = Path(job['input_fsp'])
                    if not fsp_path.exists():
                        errors.append(f"Input FSP not found: {fsp_path}")
                
                # Check batch_id uniqueness in database
                if self.db.get_batch_status(manifest.batch_id):
                    errors.append(f"Batch ID already exists: {manifest.batch_id}")
            
            return len(errors) == 0, errors
        except Exception as e:
            return False, [f"Manifest parsing error: {str(e)}"]
    
    def submit_batch(
        self,
        manifest_path: Path,
        authorization_token: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Submit batch for execution.
        
        Returns:
            Dict with 'success', 'batch_id', 'message', and optional 'errors'
        """
        # Validate first
        is_valid, errors = self.validate_batch(manifest_path)
        if not is_valid:
            return {
                'success': False,
                'message': 'Validation failed',
                'errors': errors
            }
        
        if dry_run:
            return {
                'success': True,
                'message': 'Dry run validation passed',
                'errors': []
            }
        
        # Load and register
        manifest = GenericBatchManifest.from_file(manifest_path)
        
        # Compute manifest SHA
        with open(manifest_path, 'rb') as f:
            import hashlib
            manifest_sha256 = hashlib.sha256(f.read()).hexdigest()
        
        # Register in database
        success = self.db.register_batch(manifest, manifest_sha256)
        
        if success:
            return {
                'success': True,
                'batch_id': manifest.batch_id,
                'message': f'Batch {manifest.batch_id} submitted successfully',
                'total_jobs': len(manifest.jobs)
            }
        else:
            return {
                'success': False,
                'message': f'Failed to register batch (already exists?)',
                'errors': ['Database registration failed']
            }
    
    def batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get batch status."""
        return self.db.get_batch_status(batch_id)
    
    def list_queue(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all batches in queue."""
        return self.db.list_batches(status_filter)
