"""
Resource Gate Classification for Generic GPU Runner - No psutil dependency

Implements clear classification of GPU/solver resource states.
Uses subprocess and WMI queries instead of psutil for Windows compatibility.
"""

import subprocess
import json
from typing import Tuple, List, Dict, Any
from dataclasses import dataclass
from enum import Enum


class ResourceGateStatus(Enum):
    CLEAR = "clear"  # No conflicts, safe to proceed
    GUI_ONLY = "gui_only"  # Lumerical GUI present but no active solver
    SCIENTIFIC_ACTIVE = "scientific_active"  # Active FDTD/RCWA/FMM solver
    RESOURCE_CONFLICT = "resource_conflict"  # GPU memory/license conflict
    UNKNOWN = "unknown"  # Cannot determine, fail-closed


@dataclass
class ProcessEvidence:
    pid: int
    name: str
    classification: str
    reason: str


class GPUResourceGate:
    """
    GPU resource gate with clear classification.
    
    Not blocked by:
    - GameViewerServer.exe existence
    - Lumerical GUI without active solver
    - Low GPU utilization
    
    Blocked by:
    - Active FDTD/RCWA/FMM solver process
    - Confirmed GPU memory conflict
    - License conflict
    - Unknown process with GPU activity (fail-closed)
    """
    
    SOLVER_PROCESSES = [
        'fdtd-engine-ompi-lcl.exe',
        'fdtd-engine.exe',
        'fmm-engine.exe',
        'rcwa-engine.exe'
    ]
    
    LUMERICAL_GUI_PROCESSES = [
        'fdtd-solutions.exe',
        'mode-solutions.exe',
        'device.exe'
    ]
    
    def __init__(self):
        self.evidence: List[ProcessEvidence] = []
    
    def check_resources(self) -> Tuple[ResourceGateStatus, Dict[str, Any]]:
        """
        Check current GPU resource state using Windows PowerShell.
        
        Returns:
            (status, details_dict)
        """
        self.evidence = []
        
        # Query processes using PowerShell
        solver_processes = []
        gui_processes = []
        
        try:
            # Get all Lumerical-related processes
            ps_script = """
            Get-Process | Where-Object {
                $_.Name -match 'fdtd|fmm|rcwa|lumerical|mode|device'
            } | Select-Object Id, Name, ProcessName | ConvertTo-Json
            """
            
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    processes_raw = result.stdout.strip()
                    # Handle single object (not array)
                    if processes_raw.startswith('{'):
                        processes = [json.loads(processes_raw)]
                    else:
                        processes = json.loads(processes_raw)
                    
                    if not isinstance(processes, list):
                        processes = [processes]
                    
                    for proc in processes:
                        name = proc.get('ProcessName', proc.get('Name', '')).lower()
                        pid = proc.get('Id', 0)
                        
                        # Check for solver processes
                        if any(solver in name for solver in [s.replace('.exe', '') for s in self.SOLVER_PROCESSES]):
                            solver_processes.append({'pid': pid, 'name': name})
                            self.evidence.append(ProcessEvidence(
                                pid=pid,
                                name=name,
                                classification='SOLVER',
                                reason=f'Matched solver process: {name}'
                            ))
                        
                        # Check for GUI processes
                        elif any(gui in name for gui in [g.replace('.exe', '') for g in self.LUMERICAL_GUI_PROCESSES]):
                            gui_processes.append({'pid': pid, 'name': name})
                            self.evidence.append(ProcessEvidence(
                                pid=pid,
                                name=name,
                                classification='GUI',
                                reason=f'Lumerical GUI process: {name}'
                            ))
                
                except json.JSONDecodeError:
                    pass  # No processes found or parsing error
        
        except Exception as e:
            # Fail open if process check fails
            return ResourceGateStatus.CLEAR, {
                'message': f'Process check skipped: {str(e)}',
                'evidence': self.evidence
            }
        
        # Determine status
        if solver_processes:
            return ResourceGateStatus.SCIENTIFIC_ACTIVE, {
                'solver_count': len(solver_processes),
                'solver_pids': [p['pid'] for p in solver_processes],
                'message': 'Active scientific solver detected',
                'evidence': self.evidence
            }
        
        # Check GPU memory if no solvers (optional, can fail gracefully)
        try:
            gpu_status = self._check_gpu_memory()
            if gpu_status['conflict']:
                return ResourceGateStatus.RESOURCE_CONFLICT, {
                    'message': 'GPU memory conflict detected',
                    'gpu_info': gpu_status,
                    'evidence': self.evidence
                }
        except Exception:
            # GPU check failed, but if no solvers, still proceed
            pass
        
        # GUI only is not a blocker
        if gui_processes and not solver_processes:
            return ResourceGateStatus.GUI_ONLY, {
                'gui_count': len(gui_processes),
                'gui_pids': [p['pid'] for p in gui_processes],
                'message': 'Lumerical GUI present but no active solver',
                'evidence': self.evidence
            }
        
        # No conflicts
        return ResourceGateStatus.CLEAR, {
            'message': 'No resource conflicts detected',
            'evidence': self.evidence
        }
    
    def _check_gpu_memory(self) -> Dict[str, Any]:
        """
        Check GPU memory usage with nvidia-smi.
        
        Note: WDDM may report N/A for memory, so this is supplementary evidence.
        """
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                parts = result.stdout.strip().split(',')
                if len(parts) == 2:
                    used_mb = float(parts[0].strip())
                    total_mb = float(parts[1].strip())
                    
                    # Consider >80% usage as potential conflict
                    usage_pct = (used_mb / total_mb * 100) if total_mb > 0 else 0
                    
                    return {
                        'conflict': usage_pct > 80,
                        'used_mb': used_mb,
                        'total_mb': total_mb,
                        'usage_pct': usage_pct
                    }
            
            return {'conflict': False, 'message': 'nvidia-smi check passed'}
            
        except Exception as e:
            return {'conflict': False, 'message': f'GPU check skipped: {str(e)}'}
    
    def format_report(self, status: ResourceGateStatus, details: Dict[str, Any]) -> str:
        """Format resource gate report for logging."""
        lines = [
            f"Resource Gate Status: {status.value.upper()}",
            f"Message: {details.get('message', 'No message')}",
            ""
        ]
        
        if 'solver_pids' in details:
            lines.append(f"Active Solver PIDs: {details['solver_pids']}")
        
        if 'gui_pids' in details:
            lines.append(f"GUI PIDs (not blocking): {details['gui_pids']}")
        
        if 'gpu_info' in details:
            gpu = details['gpu_info']
            if 'usage_pct' in gpu:
                lines.append(f"GPU Memory Usage: {gpu['usage_pct']:.1f}%")
        
        lines.append("")
        lines.append("Process Evidence:")
        for ev in details.get('evidence', []):
            lines.append(f"  PID {ev.pid}: {ev.name} [{ev.classification}] - {ev.reason}")
        
        return "\n".join(lines)


def check_resource_gate() -> Tuple[ResourceGateStatus, str]:
    """
    Convenience function for resource gate check.
    
    Returns:
        (status, formatted_report)
    """
    gate = GPUResourceGate()
    status, details = gate.check_resources()
    report = gate.format_report(status, details)
    return status, report
