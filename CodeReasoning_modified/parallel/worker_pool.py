"""Manages parallel execution - REPRODUCIBLE & ISOLATED"""

import os
import random
import shutil
import time
import uuid
import hashlib
import signal
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Tuple
from core.mutation_applier import MutationApplier

class WorkerPool:
    """Manages parallel execution - REPRODUCIBLE & ISOLATED"""
    
    def __init__(self, max_workers: int = 6):
        self.max_workers = max_workers
    
    def process_single_mutant(self, args: Tuple) -> Dict[str, Any]:
        """Process single mutant - ISOLATED and REPRODUCIBLE"""
        (work_dir, mutant_dir, mutant_info, project_id, bug_id, 
         relative_source_dirs, worker_seed) = args
        
        # CRITICAL: Set seeds for reproducibility
        import random
        random.seed(worker_seed)
        
        # Create FRESH instances with isolated seeds
        mutation_applier = MutationApplier(
            random_seed=worker_seed,
            project_id=project_id,
            bug_id=bug_id
        )
        
        from core.coverage_runner import CoverageRunner
        coverage_runner = CoverageRunner()
        
        pid = os.getpid()
        mutant_id = mutant_info['mutant_id']
        
        try:
            print(f"   [PID {pid}] Processing {project_id}-{bug_id} mutant {mutant_id}")
            
            # VALIDATE: Check mutant belongs to correct project/bug
            if (mutant_info.get('project_id') != project_id or 
                mutant_info.get('bug_id') != bug_id):
                print(f"   [PID {pid}] ERROR: Mutant data mismatch!")
                return None
            
            # 1. Create ISOLATED project copy
            if not mutation_applier.create_project_copy(work_dir, mutant_dir):
                return None
            
            # 2. Process mutations
            source_dirs = [mutant_dir / rel_path for rel_path in relative_source_dirs]
            mutations_by_file = {}
            
            print(f"   [PID {pid}] Mutant {mutant_id} will apply the following mutations:")
            for mutation in mutant_info['mutations']:
                class_name = mutation['class_name']
                line_number = mutation['line_number']
                mutator = mutation['mutator']
                original_code = mutation.get('original_code', '').strip()
                mutated_code = mutation.get('mutated_code', '').strip()
                print(f"      - File/Class: {class_name}, Line: {line_number}, Mutator: {mutator}")
                print(f"        Original: {original_code}")
                print(f"        Mutated : {mutated_code}")
                target_file = mutation_applier.find_java_file_by_class(class_name, source_dirs)
                if not target_file:
                    print(f"   [PID {pid}] File not found: {class_name}")
                    continue
                relative_line = mutation_applier.get_relative_line_number(
                    target_file,
                    mutation.get('method_name', ''),
                    line_number
                )
                relative_line_value = relative_line if relative_line is not None else line_number
                mutation['relative_line_number'] = relative_line_value
                mutation['mutation'] = (
                    f"{class_name}@{mutation.get('method_name', '')}:{relative_line_value}:"
                    f"{original_code} |==> {mutated_code}"
                )
                if target_file not in mutations_by_file:
                    mutations_by_file[target_file] = []
                mutations_by_file[target_file].append(mutation)
            
            # 3. Apply mutations
            for target_file, file_mutations in mutations_by_file.items():
                if len(file_mutations) == 1:
                    m = file_mutations[0]
                    success = mutation_applier.apply_mutation_to_file(
                        target_file,
                        m['line_number'],
                        m['original_code'],
                        m['mutated_code'],
                        m.get('match_index')
                    )
                else:
                    success = mutation_applier.apply_multiple_mutations(target_file, file_mutations)
                
                if not success:
                    return None
            
            # 4. Run coverage
            coverage_result = coverage_runner.run_coverage_analysis(
                mutant_dir, project_id, bug_id
            )
            
            # 5. Prepare ISOLATED result
            result_info = {
                'mutant_id': f"{project_id}-{bug_id}_{mutant_info['mutant_id']}",
                'project_id': project_id,
                'bug_id': bug_id,
                'mutant_directory': str(mutant_dir),
                'mutator': ', '.join(mutant_info['mutators']),
                'class_name': mutant_info['class_name'],
                'method_name': mutant_info.get('method_name', ''),
                'method_names': mutant_info.get('method_names', []),
                'line_number': mutant_info['line_number'],
                'target_file': str(list(mutations_by_file.keys())[0].relative_to(mutant_dir)),
                'whole_log': mutant_info.get('whole_log', ''),
                'whole_logs': mutant_info.get('whole_logs', []),
                'mutation': " || ".join(
                    [m.get('mutation', '') for m in mutant_info.get('mutations', []) if m.get('mutation')]
                ),
                'coverage_success': coverage_result['coverage_success'],
                'coverage_percentage': coverage_result['coverage_percentage'],
                'branch_coverage': coverage_result['branch_coverage'],
                'test_run': coverage_result.get('test_run', ''),
                'method_coverage': coverage_result['method_coverage'],
                'num_mutations': mutant_info['num_mutations'],
                'mutation_signature': mutant_info['signature'],
                'generation_seed': mutant_info.get('generation_seed', worker_seed),
                'worker_pid': pid,
                'worker_seed': worker_seed
            }
            
            return result_info
            
        except Exception as e:
            print(f"   [PID {pid}] Error: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        finally:
            # Cleanup - but only if it's a temp directory
            if "temp_mutant_" in str(mutant_dir):
                # Kill any lingering processes that reference this mutant directory
                try:
                    self._kill_processes_for_path(mutant_dir)
                except Exception:
                    pass
                try:
                    shutil.rmtree(mutant_dir)
                except Exception:
                    pass

    def _kill_processes_for_path(self, path: Path, timeout: int = 5):
        """Kill processes whose command line references the given path.

        This helps clean up java/ant child processes that can remain after
        timeouts or errors. We try SIGTERM first, then SIGKILL.
        """
        # Use pgrep -f to find processes matching the path string (works on macOS/Linux)
        try:
            cmd = ["pgrep", "-f", str(path)]
            out = subprocess.check_output(cmd, text=True).strip()
            if not out:
                return
            pids = [int(p) for p in out.splitlines() if p.strip().isdigit()]
        except subprocess.CalledProcessError:
            # pgrep returns non-zero when no processes matched
            return

        for pid in pids:
            try:
                print(f"   [CLEANUP] Terminating PID {pid} for path {path}")
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue

        # Give processes a moment to exit
        time.sleep(timeout)

        # Force kill any remaining
        for pid in pids:
            try:
                # Check if process still exists
                os.kill(pid, 0)
            except OSError:
                continue
            try:
                print(f"   [CLEANUP] Killing PID {pid} (SIGKILL)")
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
    
    def process_mutants_parallel(self, work_dir: Path, mutants_output_dir: Path,
                               mutants: List[Dict], project_id: str, bug_id: str,
                               relative_source_dirs: List[Path]) -> Tuple[List[Dict], List[str]]:
        """Process mutants with ISOLATION and REPRODUCIBILITY"""
        
        # VALIDATE all mutants belong to this project/bug
        valid_mutants = []
        for mutant in mutants:
            if (mutant.get('project_id') == project_id and 
                mutant.get('bug_id') == bug_id):
                valid_mutants.append(mutant)
            else:
                print(f"WARNING: Skipping mutant from wrong project/bug")
        
        successful_mutants = []
        failed_mutants = []
        
        # Create worker args with ISOLATED seeds
        worker_args = []
        for i, mutant_info in enumerate(valid_mutants):
            # Create UNIQUE directory name with project/bug/mutant ID
            # Sanitize mutant id to remove characters that are interpreted by the shell (e.g. pipes)
            raw_mid = str(mutant_info.get('mutant_id', ''))
            # replace unsafe characters with underscore
            import re
            safe_mid = re.sub(r'[^A-Za-z0-9_.-]', '_', raw_mid)
            # Use a UUID to avoid collisions across fast parallel workers
            mutant_dir = work_dir.parent / f"temp_mutant_{project_id}_{bug_id}_{safe_mid}_{i}_{uuid.uuid4().hex}"

            # Create deterministic worker seed using MD5 of identifying info
            # Avoid Python's built-in hash() which is randomized across processes
            seed_source = f"{project_id}{bug_id}{mutant_info['mutant_id']}{mutant_info.get('generation_seed', 42)}"
            worker_seed = int(hashlib.md5(seed_source.encode()).hexdigest(), 16) % (2**31)
            
            args = (work_dir, mutant_dir, mutant_info, project_id, bug_id, 
                   relative_source_dirs, worker_seed)
            worker_args.append(args)
        
        # Execute with isolation
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_mutant = {}
            for args in worker_args:
                future = executor.submit(self.process_single_mutant, args)
                future_to_mutant[future] = args[2]['mutant_id']
            
            for future in as_completed(future_to_mutant):
                mutant_id = future_to_mutant[future]
                try:
                    result = future.result(timeout=1200)  # 20 minute timeout
                    if result and result.get('project_id') == project_id and result.get('bug_id') == bug_id:
                        successful_mutants.append(result)
                    else:
                        failed_mutants.append(mutant_id)
                except Exception as e:
                    print(f"Worker failed for mutant {mutant_id}: {e}")
                    failed_mutants.append(mutant_id)
        
        return successful_mutants, failed_mutants