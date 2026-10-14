"""
Generic Batch Manifest Schema for APCD GPU FDTD Runner

This schema decouples scientific batch parameters from the GPU platform.
"""

GENERIC_BATCH_MANIFEST_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["batch_id", "project_id", "jobs", "max_entries"],
    "properties": {
        "batch_id": {
            "type": "string",
            "description": "Unique batch identifier, must not conflict with existing batches",
            "pattern": "^[A-Za-z0-9_-]+$"
        },
        "project_id": {
            "type": "string",
            "description": "Research project identifier"
        },
        "batch_type": {
            "type": "string",
            "enum": ["fdtd_3d", "fdtd_2d", "varfdtd"],
            "default": "fdtd_3d"
        },
        "jobs": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["job_id", "attempt_id", "input_fsp", "output_dir"],
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Unique job identifier within batch"
                    },
                    "attempt_id": {
                        "type": "string",
                        "pattern": "^attempt_\\d{3}$",
                        "description": "Attempt identifier, e.g., attempt_001"
                    },
                    "input_fsp": {
                        "type": "string",
                        "description": "Absolute path to input FSP file"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Absolute path for results"
                    },
                    "solver_backend": {
                        "type": "string",
                        "enum": ["lumerical_fdtd_gpu", "lumerical_fdtd_cpu"],
                        "default": "lumerical_fdtd_gpu"
                    },
                    "resources": {
                        "type": "object",
                        "properties": {
                            "gpu_count": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 1,
                                "default": 1,
                                "description": "Always 1 for serial platform"
                            },
                            "estimated_memory_gb": {
                                "type": "number",
                                "minimum": 1
                            }
                        }
                    },
                    "physics_contract_sha256": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{64}$",
                        "description": "Optional SHA256 of frozen physics contract"
                    },
                    "profile": {
                        "type": "string",
                        "description": "Optional post-processing profile name"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional job-specific metadata"
                    }
                }
            }
        },
        "max_entries": {
            "type": "integer",
            "minimum": 1,
            "description": "Maximum number of solver entries for this batch"
        },
        "recovery_strategy": {
            "type": "string",
            "enum": ["fail_closed", "skip_failed"],
            "default": "fail_closed",
            "description": "How to handle uncertain entry states"
        },
        "authorization": {
            "type": "object",
            "description": "Scientific authorization metadata",
            "properties": {
                "granted_by": {"type": "string"},
                "granted_at": {"type": "string", "format": "date-time"},
                "authorization_id": {"type": "string"}
            }
        }
    }
}

EXAMPLE_COUPLING_ML_BATCH = {
    "batch_id": "COUPLING_ML_K6V3_EXAMPLE_001",
    "project_id": "blue_apcd_mdc_np_coupling_ml_v1",
    "batch_type": "fdtd_3d",
    "jobs": [
        {
            "job_id": "K6V3_G001_EXAMPLE",
            "attempt_id": "attempt_001",
            "input_fsp": "D:/apcd_runtime/coupling_ml/setups/G001_5nm.fsp",
            "output_dir": "D:/apcd_runtime/coupling_ml/results/G001",
            "solver_backend": "lumerical_fdtd_gpu",
            "resources": {
                "gpu_count": 1,
                "estimated_memory_gb": 6
            },
            "physics_contract_sha256": "51212d0c69f2112add3ee4008eb51a8aa94e380c39624d93d31e5f75e7be0e36",
            "profile": "coupling_609d_v1",
            "metadata": {
                "geometry_type": "K6V3",
                "mesh_size_nm": 5,
                "simulation_time_ps": 3
            }
        }
    ],
    "max_entries": 1,
    "recovery_strategy": "fail_closed"
}

EXAMPLE_MDC_BATCH = {
    "batch_id": "MDC_PLANEWAVE_EXAMPLE_001",
    "project_id": "blue_apcd_mdc_planewave_sweep",
    "batch_type": "fdtd_3d",
    "jobs": [
        {
            "job_id": "MDC_T450_D350",
            "attempt_id": "attempt_001",
            "input_fsp": "D:/apcd_runtime/mdc/setups/mdc_t450_d350.fsp",
            "output_dir": "D:/apcd_runtime/mdc/results/t450_d350",
            "solver_backend": "lumerical_fdtd_gpu",
            "resources": {
                "gpu_count": 1,
                "estimated_memory_gb": 4
            },
            "profile": "mdc_transmission_v1",
            "metadata": {
                "thickness_nm": 450,
                "diameter_nm": 350
            }
        }
    ],
    "max_entries": 1,
    "recovery_strategy": "fail_closed"
}
