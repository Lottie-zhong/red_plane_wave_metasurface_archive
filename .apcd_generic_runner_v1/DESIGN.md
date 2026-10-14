# APCD Generic GPU FDTD Runner - Design Document

## 1. Architecture Overview

Transform GPU V2/V2.1 from batch-specific platform into a generic, reusable FDTD serial runner.

### Core Principle
- One Windows workstation, one RTX 3080, one Controller, one Worker
- One GPU scientific solver at a time
- Multiple research branches share the same queue
- Complete data isolation between batches
- Stable, reusable GPU solver backend

### Reused Components (from 309 PASS V2.1)
- Validated GPU solver invocation (native.py)
- Single Controller/Worker serial architecture
- GPU resource lock & fencing (processes.py)
- SQLite execution ledger
- Native FSP/H5/SHA persistence (artifacts.py)
- Failure recovery, No Replay, Truth Valid checks
- V2.1 validator fixes

## 2. Generic Batch Contract

### Batch Manifest Schema
```json
{
  "batch_id": "unique_batch_identifier",
  "project_id": "research_project_name",
  "jobs": [
    {
      "job_id": "unique_job_id",
      "attempt_id": "attempt_001",
      "input_fsp": "absolute_path_or_uri",
      "output_dir": "results_directory",
      "solver_backend": "lumerical_fdtd_gpu",
      "resources": {
        "gpu_count": 1,
        "estimated_memory_gb": 8
      },
      "physics_contract_sha256": "optional_verification_hash",
      "profile": "optional_postprocessing_profile"
    }
  ],
  "max_entries": 10,
  "recovery_strategy": "fail_closed"
}
```

### Decoupled Elements
Platform must NOT hardcode:
- K6, MDC, DIAG2, DOE56, 609D
- 440-460nm, 5nm, 6ps
- Specific materials, sources, geometries

These are per-batch scientific parameters.

## 3. Generic Interface

### Command-Line API
```bash
apcd_gpu_runner submit_batch --manifest batch.json --validate-only
apcd_gpu_runner submit_batch --manifest batch.json --dry-run
apcd_gpu_runner submit_batch --manifest batch.json  # requires authorization
apcd_gpu_runner batch_status --batch-id ABC123
apcd_gpu_runner list_queue
apcd_gpu_runner inspect_job --job-id XYZ789
apcd_gpu_runner export_report --batch-id ABC123 --output report.json
apcd_gpu_runner doctor  # system health check
```

### Python API
```python
from apcd_gpu_runner import GenericRunner

runner = GenericRunner(config_path="config.yaml")
runner.validate_batch(manifest)
runner.submit_batch(manifest, authorization_token)
status = runner.batch_status(batch_id)
```

## 4. Authorization Model

Simplified but safe:
- Protected generic batch submission endpoint
- One-time scientific authorization per batch
- Platform enforces budget and No Replay automatically

Must choose: OS identity + batch approval records, or explicit signed admission.
Cannot allow self-signed forgery or bypass via same Windows SID.

## 5. Resource Gate Logic

Clear classification:
- `GUI_ONLY`: Lumerical GUI without active solver → proceed
- `SCIENTIFIC_ACTIVE`: Active FDTD/RCWA/FMM solver → HOLD
- `RESOURCE_CONFLICT`: GPU memory/license conflict → HOLD
- `UNKNOWN`: Cannot determine → HOLD (fail-closed)

Not blocked by GameViewerServer.exe existence alone.
Check actual solver process, GPU engine activity, license state.

## 6. Cross-Batch Integration Tests

### Test Batches
A. DOE56 - existing, science HOLD
B. DIAG2 - independent authorization
C. NEW_TEST_BATCH - synthetic, never pre-coded in platform

Verify:
- A cannot enter (frozen HOLD)
- B can validate and queue (with mock admission)
- C can validate and queue without platform source changes
- Budget isolation
- No replay
- No double GPU solver
- Independent ledgers

## 7. Implementation Phases

### Phase 1: Core Refactoring
- Extract reusable solver backend
- Define GenericBatchManifest
- Create batch-agnostic validator
- Separate scientific profile plugins

### Phase 2: Queue & Controller
- Generic serial queue manager
- Batch submission interface
- Resource gate with clear classification
- SQLite schema for multi-batch

### Phase 3: Integration
- Cross-batch A/B/C tests
- Failure injection
- Full regression (must exceed 309 PASS baseline)

### Phase 4: Documentation & Release
- User guide (Chinese)
- Two working examples (Coupling-ML, MDC)
- Release candidate with SHA inventory
- Deployment instructions

## 8. Deliverables

Code:
- apcd_gpu_runner/ (generic platform)
- batch_manifest_schema.json
- example_coupling_ml_batch.json
- example_mdc_batch.json

Tests:
- test_generic_validation.py
- test_cross_batch_isolation.py
- test_resource_gate_classification.py
- test_no_replay_recovery.py

Documentation:
- GENERIC_GPU_RUNNER_INTERFACE.md
- QUICK_START_CN.md (one-page Chinese guide)
- FINAL_REPORT.md
- CONTINUATION.md
- SHA_INVENTORY.json

## 9. Success Criteria

- Coupling-ML batch today
- MDC batch tomorrow
- Future batches without:
  - Platform source changes
  - Re-deployment
  - Re-binding identities
  - New ACL configuration
  - Repeated platform authorization

## 10. Constraints

This round:
- solver entries = 0
- FDTD runs = 0
- ML fits = 0
- replay = 0
- DIAG2 = 0/2
- DOE56 = 4 entered / 52 HOLD

Complete offline, await deployment authorization.
