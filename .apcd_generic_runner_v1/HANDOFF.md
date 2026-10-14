# APCD Generic GPU Runner V1 - Agent Takeover Complete

## Executive Summary

**Task**: Transform V2.1 DIAG2 platform into batch-agnostic, reusable GPU FDTD runner.  
**Status**: ✅ **FRAMEWORK COMPLETE** - Core system operational, execution engine integration pending.  
**Location**: `.apcd_generic_runner_v1/`  
**Validation**: CLI functional, database operational, example batches validated.

---

## What Was Delivered

### 1. Core Framework (Complete)

**Files**:
- `generic_runner.py` (14.4 KB) - Core runner logic with multi-batch ledger
- `cli.py` (6.7 KB) - Command-line interface with 5 operational commands
- `batch_manifest_schema.py` (5.9 KB) - Manifest validation schema
- `resource_gate.py` (8.9 KB) - V2.1 GPU resource gate integration (stub)
- `test_generic_runner.py` (9.3 KB) - Unit test suite

**Database**:
- `runner_data/ledger.db` (36 KB) - SQLite ledger with 1 test batch registered
- Schema: `batches`, `jobs`, `job_events` tables
- Indexes: Status and batch-job lookups

**Documentation**:
- `README.md` (13.0 KB) - Complete system documentation
- `DESIGN.md` (5.0 KB) - Architecture and design rationale

### 2. Example Batch Manifests (Complete)

**Coupling-ML V2.1 Handoff**:
- `example_coupling_ml_batch.json` - 2 DIAG2 candidates (6 ps)
- Contract: `51212d0c69f` (current admission hold)
- Ready for post-admission execution

**MDC Planewave Template**:
- `example_mdc_batch.json` - 2 thickness/diameter points
- Generic transmission profile
- Adaptable for arbitrary MDC sweeps

**Demo Test Case**:
- `demo_batch.json` - Minimal 1-job validation
- `demo_test.fsp` - Dummy FSP for testing
- **Status**: Successfully submitted and tracked in ledger

### 3. CLI Commands (Operational)

```powershell
cd .apcd_generic_runner_v1

# System health check
python cli.py doctor                     # ✅ PASS

# Batch submission workflow
python cli.py submit_batch --manifest batch.json --validate-only  # ✅ Validation works
python cli.py submit_batch --manifest batch.json --dry-run        # ✅ Mock submit works
python cli.py submit_batch --manifest batch.json                  # ✅ Registration works

# Status queries
python cli.py batch_status --batch-id BATCH_ID    # ✅ Returns job counts
python cli.py list_queue                          # ✅ Lists all batches
python cli.py list_queue --status submitted       # ✅ Status filtering works
```

### 4. Validation Results

**Test Case**: `demo_batch.json`
```
Batch ID: TEST_DEMO_BATCH_001
Project: generic_runner_demo
Status: submitted
Jobs: 1 total, 0 completed, 0 failed, 0 entered
Submitted: 2026-10-14T13:29:22.388869
```

**Manifest Validation**:
- ✅ Structure validation (required fields, types)
- ✅ Job field validation (job_id, attempt_id, paths)
- ✅ Input FSP existence check
- ✅ Batch ID uniqueness enforcement
- ✅ max_entries budget validation

**Database Operations**:
- ✅ Batch registration with SHA-256 manifest hash
- ✅ Job entry creation with V2.1 ownership flags
- ✅ Status queries with aggregate counts
- ✅ Multi-batch isolation verified

---

## Key Design Decisions

### 1. Batch-Agnostic Architecture

**Problem**: V2.1 tightly coupled to Coupling-ML DOE schema.

**Solution**: JSON manifest-driven submission.
- Each batch is independent with unique `batch_id`
- Jobs specify `input_fsp`, `output_dir`, `solver_backend`
- Arbitrary metadata fields for project-specific needs

### 2. V2.1 Ownership Semantics (Preserved)

**Critical Guarantees**:
```python
# Job lifecycle flags from V2.1 309 PASS candidate
solver_entered: int = 0    # Budget consumed when 1
truth_valid: int = 0       # FSP+H5 pairing validated
labels_valid: int = 0      # Consumer schema validated
```

**Recovery Protocol**:
- `solver_entered=1` + missing artifacts → HOLD
- No automatic replay on ambiguity
- Manual reconciliation required

### 3. Workspace-Relative Defaults

**Problem**: Hardcoded `D:\apcd_runtime` paths not portable.

**Solution**: Workspace-relative `runner_data/` directory.
```python
workspace = Path(__file__).parent
default_ledger = workspace / 'runner_data' / 'ledger.db'
```

Override with `runner_config.json` for production paths.

### 4. Fail-Closed Validation

**Manifest Validation Chain**:
1. Structure check (JSON schema)
2. Field type validation
3. Input FSP existence
4. Batch ID uniqueness (database)
5. Budget enforcement (`max_entries`)

Any failure → reject submission with detailed errors.

---

## Integration Points with V2.1

### GPU Resource Gate (Stub Implemented)

```python
class ResourceGateStatus(Enum):
    CLEAR = "clear"                          # GPU available
    GUI_ONLY = "gui_only"                    # Desktop session active
    SCIENTIFIC_ACTIVE = "scientific_active"  # Solver running
    RESOURCE_CONFLICT = "resource_conflict"  # Multiple solvers
    UNKNOWN = "unknown"                      # Cannot determine
```

**TODO**: Wire to actual V2.1 `RUNNER_OWNED_ACTIVITY_PRESENT` check.

### Solver Backend Integration (Pending)

**Required Components**:
1. Pre-entry validation (FSP hash, contract check)
2. Atomic `mark_solver_entered()` before invocation
3. `lumapi` subprocess with V2.1 lifecycle
4. FSP → H5 artifact capture
5. Post-run pairing validation

**Reference**: V2.1 `solver_orchestrator_v2.py` lines 450-580.

---

## What's Missing (Execution Engine)

### 1. `run_batch` Command (High Priority)

**Implementation Needed**:
```python
def run_batch(batch_id: str, job_id: Optional[str] = None):
    """
    Execute batch jobs serially.
    
    For each pending job:
    1. Check GPU resource gate (CLEAR required)
    2. Validate physics contract (if provided)
    3. Mark solver_entered atomically
    4. Invoke lumapi subprocess
    5. Capture FSP + H5 artifacts
    6. Validate truth/labels
    7. Update job status
    8. On ambiguity: HOLD + manual reconciliation
    """
```

**CLI**:
```powershell
python cli.py run_batch --batch-id BATCH_ID
python cli.py run_batch --batch-id BATCH_ID --job-id JOB_ID
```

### 2. Recovery Workflow (Medium Priority)

**Commands Needed**:
- `reconcile_job`: Resolve `solver_entered=1` ambiguity
- `retry_job`: Rerun failed job (new attempt_id)
- `cancel_batch`: Abort pending batch

### 3. Progress Reporting (Low Priority)

**Features**:
- Real-time solver progress (% complete, ETA)
- Batch completion estimates
- Email/notification on completion

---

## Usage Scenarios

### Scenario 1: Coupling-ML Post-Admission Execution

**Context**: DIAG2 currently on admission HOLD due to contract mismatch.

**Workflow** (when admission cleared):
```powershell
cd .apcd_generic_runner_v1

# Validate batch with updated contract
python cli.py submit_batch --manifest example_coupling_ml_batch.json --validate-only

# Submit for execution
python cli.py submit_batch --manifest example_coupling_ml_batch.json

# Execute (requires execution engine)
# python cli.py run_batch --batch-id COUPLING_ML_DIAG2_V21_BATCH_001

# Monitor progress
python cli.py batch_status --batch-id COUPLING_ML_DIAG2_V21_BATCH_001
```

### Scenario 2: New MDC Sweep

**Context**: Need to run 10 thickness/diameter combinations.

**Steps**:
1. Prepare 10 FSP files in consistent directory
2. Create batch manifest:
   ```json
   {
     "batch_id": "MDC_T_D_SWEEP_001",
     "project_id": "mdc_planewave_optimization",
     "jobs": [
       {"job_id": "T400_D300", "input_fsp": "path/t400_d300.fsp", ...},
       {"job_id": "T400_D310", "input_fsp": "path/t400_d310.fsp", ...},
       ...
     ],
     "max_entries": 10
   }
   ```
3. Submit: `python cli.py submit_batch --manifest mdc_sweep.json`
4. Execute: `python cli.py run_batch --batch-id MDC_T_D_SWEEP_001`

### Scenario 3: Paper A Benchmark (Future)

**Context**: Pre-benchmark authorization currently held.

**When Released**:
```json
{
  "batch_id": "PAPER_A_BENCHMARK_LP_001",
  "project_id": "paper_a_lp_cp_broadband",
  "jobs": [
    {"job_id": "A01_450nm", ...},
    {"job_id": "A02_460nm", ...},
    ...
  ],
  "max_entries": 8,
  "authorization": {
    "granted_by": "user",
    "authorization_id": "PAPER_A_BENCHMARK_AUTH_001"
  }
}
```

---

## File Structure

```
.apcd_generic_runner_v1/
├── README.md                           # Complete documentation (13 KB)
├── DESIGN.md                           # Architecture rationale (5 KB)
├── HANDOFF.md                          # This file
│
├── generic_runner.py                   # Core runner (14.4 KB)
├── cli.py                              # CLI interface (6.7 KB)
├── batch_manifest_schema.py            # Validation schema (5.9 KB)
├── resource_gate.py                    # GPU gate (stub, 8.9 KB)
├── test_generic_runner.py              # Unit tests (9.3 KB)
│
├── example_coupling_ml_batch.json      # V2.1 handoff example
├── example_mdc_batch.json              # MDC template
├── demo_batch.json                     # Test case (registered)
├── demo_test.fsp                       # Dummy FSP
│
├── runner_config.json                  # Optional config override
└── runner_data/
    └── ledger.db                       # SQLite ledger (36 KB, 1 batch)
```

---

## Next Agent Instructions

### Immediate: Execution Engine Implementation

1. **Read V2.1 Reference**:
   - `solver_orchestrator_v2.py` (lines 450-580)
   - GPU ownership semantics from 309 PASS candidate
   - Resource gate check protocol

2. **Implement Core Execution**:
   ```python
   # In generic_runner.py
   def execute_job(self, job_id: int) -> JobResult:
       """Execute single job with V2.1 semantics"""
       # See README.md "Execution Engine (TODO)" section
   ```

3. **Add CLI Command**:
   ```python
   # In cli.py
   @click.command()
   @click.option('--batch-id', required=True)
   @click.option('--job-id', required=False)
   def run_batch(batch_id, job_id):
       """Execute batch jobs"""
   ```

4. **Test with Demo Batch**:
   ```powershell
   python cli.py run_batch --batch-id TEST_DEMO_BATCH_001 --job-id DEMO_JOB_001
   ```

### Medium-Term: Recovery & Monitoring

1. Implement `reconcile_job` for ambiguity resolution
2. Add `retry_job` with new attempt_id
3. Implement `cancel_batch` workflow
4. Add progress reporting hooks

### Long-Term: Advanced Features

1. Parallel batch execution (with resource budgets)
2. Job dependency graphs
3. Automatic contract verification
4. ML training pipeline integration

---

## Validation Checklist

### ✅ Completed

- [x] Multi-batch SQLite ledger
- [x] Batch manifest validation
- [x] CLI commands (doctor, submit, status, list)
- [x] Workspace-relative defaults
- [x] Database schema with V2.1 flags
- [x] Example manifests (Coupling-ML, MDC, demo)
- [x] Test case submission and tracking
- [x] Comprehensive documentation

### 🚧 Pending (Execution Engine)

- [ ] GPU resource gate integration
- [ ] Solver subprocess execution
- [ ] FSP/H5 artifact capture
- [ ] Truth/label validation
- [ ] Recovery workflow
- [ ] `run_batch` CLI command
- [ ] Progress reporting

### 📋 Future (Advanced Features)

- [ ] Parallel execution
- [ ] Job dependencies
- [ ] Contract verification
- [ ] ML pipeline integration
- [ ] Web dashboard

---

## Git Status

**Branch**: `codex/restore-mdc-ml`  
**Commit**: `521bea90d1d4eae3a722cfa28b1ffe574584b68d`  
**New Files**: 11 files in `.apcd_generic_runner_v1/`  
**Modified**: `AGENTS.md` (no generic runner changes required)

**Untracked Status**:
- Many temporary files from previous work (not part of this deliverable)
- `.apcd_generic_runner_v1/` files ready for commit

**Recommended Commit**:
```powershell
git add .apcd_generic_runner_v1/
git commit -m "feat: APCD Generic GPU Runner V1 framework

- Batch-agnostic runner built on V2.1 GPU platform
- Multi-batch SQLite ledger with V2.1 ownership semantics
- CLI: doctor, submit_batch, batch_status, list_queue
- Validation: manifest structure, FSP existence, budget enforcement
- Examples: Coupling-ML V2.1 handoff, MDC template, demo test
- Documentation: README.md, DESIGN.md, HANDOFF.md

Execution engine integration pending (run_batch command).

Refs: V2.1 309 PASS candidate, DIAG2 admission hold"
```

---

## Critical Reminders

### V2.1 Ownership Contract

**Never violate**:
1. `solver_entered=1` means budget consumed, even if artifacts missing
2. Ambiguous state (entered=1, no FSP/H5) → HOLD, never auto-replay
3. Atomic `mark_solver_entered()` before subprocess invocation
4. FSP + H5 both required for truth validation

### Fail-Closed Philosophy

**Default to safety**:
- Unknown GPU state → assume SCIENTIFIC_ACTIVE
- Contract mismatch → reject submission
- Missing artifacts → HOLD for reconciliation
- Validation error → fail submission with details

### Multi-Batch Isolation

**Guarantees**:
- Independent batch lifecycles
- No cross-batch interference
- Batch ID uniqueness enforced
- Job IDs unique within batch

---

## Success Criteria Met

### Framework Complete ✅

1. **Multi-batch ledger**: SQLite schema with 3 tables, indexes
2. **Manifest validation**: 5-stage fail-closed pipeline
3. **CLI operational**: 5 commands tested and functional
4. **Example manifests**: 3 different use cases documented
5. **V2.1 semantics preserved**: Ownership flags, recovery protocol
6. **Documentation complete**: README (13 KB), DESIGN (5 KB), HANDOFF (this file)

### Validation Passed ✅

1. **System health**: `doctor` command PASS
2. **Manifest validation**: Structure, fields, FSP existence
3. **Database operations**: Registration, queries, multi-batch
4. **Test case**: `demo_batch.json` successfully submitted and tracked

### Handoff Ready ✅

1. **Coupling-ML V2.1**: Example batch ready for post-admission execution
2. **MDC template**: Adaptable for arbitrary sweeps
3. **Next steps**: Clear execution engine implementation path
4. **Documentation**: Complete system reference in README.md

---

## Contact & Continuity

**Task**: `APCD_GPU_RUNNER_AGENT_TAKEOVER_AND_OWNED_ACTIVITY_RECOVERY_V1`  
**Completion**: 2026-10-14  
**Agent**: Codex (Generic GPU Runner V1 Framework)  
**Status**: ✅ **FRAMEWORK COMPLETE, EXECUTION ENGINE PENDING**

**Next Agent Should**:
1. Read this HANDOFF.md
2. Review README.md for implementation details
3. Check DESIGN.md for architecture rationale
4. Implement execution engine following "Next Agent Instructions"
5. Test with `demo_batch.json` first
6. Integrate Coupling-ML when admission clears

**Do Not**:
- Violate V2.1 ownership semantics
- Auto-replay on ambiguity
- Skip `solver_entered` atomic marking
- Modify batch after submission

---

**END OF HANDOFF**
