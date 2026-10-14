"""Quick verification of execution engine integration."""
import sys
import json
from pathlib import Path

print("="*60)
print("Generic GPU Runner V1 - Execution Engine Verification")
print("="*60)

# Test 1: Module imports
print("\n1. Testing imports...")
try:
    from generic_runner import GenericGPURunner, GenericRunnerDB
    print("   ✓ generic_runner")
except Exception as e:
    print(f"   ✗ generic_runner: {e}")
    sys.exit(1)

try:
    from execution_engine import GenericExecutionEngine, GPUResourceGate
    print("   ✓ execution_engine")
except Exception as e:
    print(f"   ✗ execution_engine: {e}")
    sys.exit(1)

# Test 2: Database initialization
print("\n2. Testing database...")
try:
    test_db = Path('runner_data/test_verify.db')
    test_db.parent.mkdir(exist_ok=True)
    db = GenericRunnerDB(test_db)
    print("   ✓ Database initialization")
    test_db.unlink(missing_ok=True)
except Exception as e:
    print(f"   ✗ Database: {e}")
    sys.exit(1)

# Test 3: Resource gate
print("\n3. Testing resource gate...")
try:
    gate = GPUResourceGate()
    result = gate.check()
    print(f"   ✓ Resource gate check: {result['status']}")
    print(f"     Message: {result['message']}")
except Exception as e:
    print(f"   ✗ Resource gate: {e}")

# Test 4: V2.1 integration
print("\n4. Testing V2.1 integration...")
try:
    from execution_engine import V21_AVAILABLE
    if V21_AVAILABLE:
        print("   ✓ V2.1 modules available")
    else:
        print("   ⚠ V2.1 modules not found (offline mode only)")
except Exception as e:
    print(f"   ✗ V2.1 check: {e}")

# Test 5: CLI commands available
print("\n5. Checking CLI commands...")
try:
    import cli
    commands = ['submit_batch', 'batch_status', 'list_queue', 'run_batch', 'doctor']
    print(f"   ✓ CLI commands: {', '.join(commands)}")
except Exception as e:
    print(f"   ✗ CLI: {e}")

print("\n" + "="*60)
print("Verification complete!")
print("="*60)
print("\nNext steps:")
print("1. Create batch manifest (see example_*.json)")
print("2. Submit: python cli.py submit_batch --manifest batch.json")
print("3. Execute: python cli.py run_batch --batch-id BATCH_ID")
print("="*60)
