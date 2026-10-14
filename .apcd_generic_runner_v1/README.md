# APCD Generic GPU Runner V1

## Overview

The Generic GPU Runner transforms the validated V2.1 DIAG2 GPU platform into a **batch-agnostic, reusable execution system** for arbitrary FDTD GPU jobs. It preserves V2.1's production-grade fail-closed ownership semantics while removing project-specific coupling.

**Status**: Framework complete, CLI functional, core validation passed.  
**Next**: Add execution engine integration with V2.1 validated GPU solver backend.

---

## Architecture

### Core Components

1. **`generic_runner.py`**: Core runner logic
   - Multi-batch SQLite ledger
   - Batch validation and registration
   - Status tracking and reporting
   - Workspace-relative configuration

2. **`cli.py`**: Command-line interface
   - `doctor`: System health check
   - `submit_batch`: Validate and submit batch manifests
   - `batch_status`: Query batch execution status
   - `list_queue`: List all batches
   - `run_batch`: Execute batch jobs (TODO)

3. **Ledger Database** (`runner_data/ledger.db`)
   - **batches**: Top-level batch tracking
   - **jobs**: Individual job entries with V2.1 ownership flags
   - **job_events**: Execution event log

---

## Batch Manifest Format

All work is submitted as JSON manifests defining independent batches:

```json
{
  "batch_id": "UNIQUE_BATCH_ID",
  "project_id": "project_identifier",
  "batch_type": "fdtd_3d",
  "jobs": [
    {
      "job_id": "JOB_001",
      "attempt_id": "attempt_001",
      "input_fsp": "/path/to/setup.fsp",
      "output_dir": "/path/to/results",
      "solver_backend": "lumerical_fdtd_gpu",
      "physics_contract_sha256": "optional_contract_hash",
      "profile": "optional_profile_name",
      "resources": {
        "gpu_count": 1,
        "estimated_memory_gb": 4
      },
      "metadata": {
        "description": "Job description",
        "custom_field": "arbitrary metadata"
      }
    }
  ],
  "max_entries": 10,
  "recovery_strategy": "fail_closed",
  "authorization": {
    "granted_by": "user",
    "granted_at": "2026-10-14T00:00:00Z",
    "authorization_id": "AUTH_ID"
  }
}
```

### Required Fields

- `batch_id`: Unique identifier (alphanumeric + underscores/hyphens)
- `project_id`: Logical project grouping
- `jobs`: List of job specifications
- `max_entries`: Maximum allowable entries (budget/safety limit)

### Job Required Fields

- `job_id`: Unique within batch
- `attempt_id`: Must start with `attempt_`
- `input_fsp`: Path to FDTD setup file (must exist, must be `.fsp`)
- `output_dir`: Results destination
- `solver_backend`: Solver type (default: `lumerical_fdtd_gpu`)

### Optional Fields

- `physics_contract_sha256`: For contract-based validation
- `profile`: Named execution profile
- `resources`: Resource requirements
- `metadata`: Arbitrary job-specific data
- `authorization`: Authorization tracking

---

## CLI Usage

### 1. System Health Check

```powershell
cd .apcd_generic_runner_v1
python cli.py doctor
```

Validates:
- Ledger database initialization
- Configuration loading
- Core dependencies

### 2. Validate Batch (No Submission)

```powershell
python cli.py submit_batch --manifest batch.json --validate-only
```

Checks:
- Manifest structure
- Job field requirements
- Input FSP existence
- Batch ID uniqueness

### 3. Dry Run (Validate + Mock Submit)

```powershell
python cli.py submit_batch --manifest batch.json --dry-run
```

### 4. Submit Batch

```powershell
python cli.py submit_batch --manifest batch.json
```

Registers batch in ledger with `submitted` status.

### 5. Query Batch Status

```powershell
python cli.py batch_status --batch-id BATCH_ID
```

Returns:
- Batch status
- Total/completed/failed/entered job counts
- Submission timestamp

### 6. List All Batches

```powershell
python cli.py list_queue
python cli.py list_queue --status submitted
```

---

## V2.1 Integration Points

The runner reuses V2.1's validated components:

### GPU Ownership Semantics (Preserved)

From V2.1 309-candidate PASS:
- `RUNNER_OWNED_ACTIVITY_PRESENT` resource gate
- `solver_entered` atomic flag
- Fail-closed recovery on ambiguity
- FSP/H5 artifact pairing

### Execution Engine (TODO)

Will integrate:
1. **Pre-entry validation**:
   - GPU resource gate check
   - Physics contract verification (if provided)
   - Output directory preparation

2. **Atomic entry recording**:
   ```python
   db.mark_solver_entered(job_id, timestamp, pre_fsp_sha256)
   ```

3. **Solver invocation**:
   - Reuse V2.1 `lumapi` subprocess pattern
   - GPU session lifecycle management
   - FSP → H5 artifact capture

4. **Post-run validation**:
   - FSP/H5 pairing check
   - Truth/label validation hooks
   - Success/failure determination

5. **Recovery protocol**:
   - Fail-closed on ambiguous state
   - Manual reconciliation required for solver_entered=1 without artifacts

---

## Example Batches

### Coupling-ML Batch

[`example_coupling_ml_batch.json`](example_coupling_ml_batch.json)
- 2 DIAG2 candidates (6 ps time window)
- Contract: `51212d0c69f` (current admission hold)
- Uses V2.1 GPU backend

### MDC Planewave Batch

[`example_mdc_batch.json`](example_mdc_batch.json)
- 2 thickness/diameter sweep points
- Planewave transmission profile
- Generic MDC project template

### Demo Batch

[`demo_batch.json`](demo_batch.json)
- Minimal 1-job test case
- Used for CLI validation

---

## Database Schema

### `batches` Table

```sql
CREATE TABLE batches (
    batch_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    batch_type TEXT NOT NULL,
    max_entries INTEGER NOT NULL,
    recovery_strategy TEXT NOT NULL,
    status TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    authorization_json TEXT,
    manifest_sha256 TEXT NOT NULL
)
```

### `jobs` Table

```sql
CREATE TABLE jobs (
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
```

### `job_events` Table

```sql
CREATE TABLE job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_data TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
)
```

---

## Status Lifecycle

### Batch States

```
submitted → validated → queued → running → completed/failed/hold
```

### Job States

```
pending → running → completed/failed/skipped
```

### Ownership Flags (V2.1 Semantics)

- `solver_entered = 0`: Budget available, no solver launch recorded
- `solver_entered = 1`: Solver launch recorded, budget consumed
- `truth_valid = 1`: Post-FSP truth validated
- `labels_valid = 1`: Consumer schema labels validated

**Recovery Rule**: `solver_entered=1` + missing artifacts = HOLD, manual reconciliation required.

---

## Configuration

Default workspace-relative config (auto-generated):

```json
{
  "ledger_path": "runner_data/ledger.db",
  "gpu_platform_version": "v2.1",
  "max_concurrent_gpu_solvers": 1,
  "default_solver_backend": "lumerical_fdtd_gpu"
}
```

Override with `runner_config.json`:

```json
{
  "ledger_path": "D:/apcd_runtime/generic_runner/ledger.db",
  "gpu_platform_version": "v2.1",
  "max_concurrent_gpu_solvers": 1,
  "resource_gate_check_enabled": true,
  "fail_closed_on_ambiguity": true
}
```

---

## Implementation Status

### ✅ Complete

1. **Core Framework**
   - Multi-batch ledger schema
   - Batch manifest validation
   - CLI interface (doctor, submit, status, list)
   - Workspace-relative defaults

2. **Validation**
   - Manifest structure checks
   - Job field requirements
   - Input file existence
   - Batch ID uniqueness

3. **Ledger Operations**
   - Batch registration
   - Job entry creation
   - Status queries
   - Multi-batch tracking

4. **Example Manifests**
   - Coupling-ML batch (V2.1 contract)
   - MDC planewave batch
   - Demo test batch

### 🚧 TODO (Execution Engine)

1. **Resource Gate Integration**
   ```python
   def check_gpu_resource_gate() -> ResourceGateStatus:
       """Check V2.1 RUNNER_OWNED_ACTIVITY_PRESENT gate"""
   ```

2. **Solver Execution**
   ```python
   def execute_job(job_id: int) -> JobResult:
       """Run single job with V2.1 GPU backend"""
       # 1. Pre-entry validation
       # 2. Atomic mark_solver_entered
       # 3. lumapi subprocess
       # 4. Artifact capture
       # 5. Post-validation
   ```

3. **Batch Executor**
   ```python
   def run_batch(batch_id: str, serial: bool = True):
       """Execute all pending jobs in batch"""
   ```

4. **CLI Command**
   ```powershell
   python cli.py run_batch --batch-id BATCH_ID [--job-id JOB_ID]
   ```

5. **Recovery Tools**
   - FSP/H5 reconciliation
   - Ambiguity resolution workflow
   - Manual entry audit

---

## Safety Guarantees

### From V2.1 (Preserved)

1. **Fail-Closed Ownership**: `solver_entered=1` without artifacts → HOLD
2. **No Auto-Replay**: Ambiguous state never triggers automatic rerun
3. **Atomic Entry**: Mark entered before solver invocation
4. **Artifact Pairing**: FSP + H5 both required for truth validation

### Generic Runner Additions

1. **Batch Isolation**: Independent batches cannot interfere
2. **Manifest Immutability**: SHA-256 hash prevents silent modification
3. **Budget Enforcement**: `max_entries` hard limit
4. **Job Uniqueness**: `(batch_id, job_id, attempt_id)` unique constraint

---

## Usage Examples

### Coupling-ML V2.1 Handoff

```powershell
# Current DIAG2 admission hold: contract mismatch
# Use generic runner for future post-admission execution

cd .apcd_generic_runner_v1

# Validate batch (checks contract availability)
python cli.py submit_batch --manifest example_coupling_ml_batch.json --validate-only

# Submit when admission cleared
python cli.py submit_batch --manifest example_coupling_ml_batch.json

# Execute (TODO: requires execution engine)
# python cli.py run_batch --batch-id COUPLING_ML_DIAG2_V21_BATCH_001
```

### MDC Planewave Sweep

```powershell
# Prepare FSP files in D:/apcd_runtime/mdc/setups/
# Update example_mdc_batch.json with actual paths

python cli.py submit_batch --manifest example_mdc_batch.json
python cli.py batch_status --batch-id MDC_PLANEWAVE_EXAMPLE_001
```

### New Project Integration

1. Create batch manifest JSON
2. Prepare input FSP files
3. Validate: `python cli.py submit_batch --manifest batch.json --validate-only`
4. Submit: `python cli.py submit_batch --manifest batch.json`
5. Execute: `python cli.py run_batch --batch-id BATCH_ID` (when available)

---

## Integration with Existing Workflows

### Coupling-ML (V2.1)

- **Current**: Monolithic `solver_orchestrator_v2.py` + DOE control
- **Future**: Submit DOE as generic batch manifests
- **Benefit**: Same fail-closed semantics, multi-batch isolation

### Paper A (LP+CP)

- **Current**: Pre-benchmark authorization hold
- **Future**: Submit benchmark sweeps as batches
- **Benefit**: Explicit budget tracking, no cross-project interference

### MDC Development

- **Current**: Ad-hoc script execution
- **Future**: Standardized batch submission
- **Benefit**: Reproducible execution, ledger audit trail

---

## Files

```
.apcd_generic_runner_v1/
├── README.md                           # This file
├── generic_runner.py                   # Core runner implementation
├── cli.py                              # Command-line interface
├── runner_config.json                  # Optional config override
├── example_coupling_ml_batch.json      # V2.1 Coupling-ML example
├── example_mdc_batch.json              # MDC planewave example
├── demo_batch.json                     # Minimal test case
├── demo_test.fsp                       # Dummy FSP for testing
└── runner_data/
    └── ledger.db                       # SQLite execution ledger
```

---

## Next Steps

### Immediate (Execution Engine)

1. Implement `run_batch` command
2. Integrate V2.1 GPU resource gate check
3. Add `lumapi` subprocess execution with V2.1 lifecycle
4. Implement FSP/H5 pairing validation
5. Add recovery workflow for ambiguous states

### Near-term (Usability)

1. Add `cancel_batch` command
2. Implement `retry_job` for failed jobs
3. Add progress reporting during execution
4. Create batch templates for common profiles
5. Add execution time estimation

### Long-term (Advanced Features)

1. Parallel batch execution (with resource budgets)
2. Job dependency graphs within batches
3. Automatic contract verification
4. Integration with ML training pipelines
5. Web dashboard for batch monitoring

---

## Author

APCD Generic GPU Runner V1  
Built on validated V2.1 GPU platform (309 PASS candidate)  
2026-10-14
