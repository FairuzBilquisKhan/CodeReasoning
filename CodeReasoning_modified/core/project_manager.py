"""Manages Defects4J project operations - FIXED for subprocess compatibility"""

import platform
import shutil
import subprocess
import os
import csv
from pathlib import Path
from typing import List, Dict

from config.settings import DEFECTS4J_EXECUTABLE, BASE_CHECKOUT_DIR


class ProjectManager:
    """Handles project checkout, compilation, and setup"""
    
    def __init__(self, base_dir: Path = BASE_CHECKOUT_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(exist_ok=True)
        self.system = platform.system().lower()
        self._bug_test_map = self._load_bug_test_map()
        
    def _get_defects4j_command(self) -> str:
        """Get platform-appropriate Defects4J command"""
        if self.system == "windows":
            return f"{DEFECTS4J_EXECUTABLE}.bat"  # Windows batch file
        else:
            return DEFECTS4J_EXECUTABLE  # Unix shell script
    
    def _run_platform_command(self, command: List[str], work_dir: Path, 
                            timeout: int = 300) -> bool:
        """Run command with platform-specific considerations"""
        env = os.environ.copy()
        python_env_vars = ['PYTHONHASHSEED', 'PYTHONPATH', 'PYTHONHOME']
        for var in python_env_vars:
            if var in env:
                del env[var]
        try:
            # Handle command formatting for different platforms
            if self.system == "windows":
                # On Windows, we might need to use shell=True for some commands
                result = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    cwd=work_dir,
                    timeout=timeout,
                    shell=True  # May be needed on Windows
                )
            else:
                # On Unix-like systems, shell=False is generally safer
                result = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    cwd=work_dir,
                    timeout=timeout,
                    shell=False
                )
            return True
        except subprocess.CalledProcessError as e:
            print(f"Command failed: {e}")
            return False
        except subprocess.TimeoutExpired:
            print("Command timed out")
            return False
        except FileNotFoundError:
            print(f"Command not found: {command[0]}")
            return False
    
    def checkout_project(self, project_id: str, bug_id: str, work_dir: Path) -> bool:
        """Checkout and compile a buggy project version (default behavior)."""
        return self.checkout_project_version(project_id, bug_id, "b", work_dir, compile_project=True)

    def checkout_project_version(self, project_id: str, bug_id: str, version: str,
                                 work_dir: Path, compile_project: bool = True) -> bool:
        """Checkout a specific project version (b/f) and optionally compile."""
        if work_dir.exists():
            self._clean_directory(work_dir)
        
        defects4j_cmd = self._get_defects4j_command()
        
        checkout_cmd = [
            defects4j_cmd, "checkout", "-p", project_id,
            "-v", f"{bug_id}{version}", "-w", str(work_dir)
        ]
        
        print(f"Checking out {project_id}-{bug_id}{version} using: {' '.join(checkout_cmd)}")
        
        try:
            result = subprocess.run(
                checkout_cmd, 
                check=True, 
                capture_output=True, 
                text=True, 
                cwd=self.base_dir, 
                timeout=300
            )
            print(f"✓ Checked out {project_id}-{bug_id}{version}")
            return self.compile_project(work_dir) if compile_project else True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to checkout project: {e}")
            if e.stderr:
                print(f"Error details: {e.stderr}")
            return False
        except FileNotFoundError:
            print(f"✗ Defects4J command not found: {defects4j_cmd}")
            print("Please ensure Defects4J is installed and in your PATH")
            return False
    
    def _clean_directory(self, directory: Path):
        """Clean directory with platform-specific error handling"""
        if directory.exists():
            try:
                shutil.rmtree(directory)
            except PermissionError:
                print(f"Warning: Could not delete {directory} due to permission issues")
                # On Windows, files might be locked
                if self.system == "windows":
                    print("On Windows, try closing any open files or IDEs")
            except Exception as e:
                print(f"Warning: Could not clean directory {directory}: {e}")
    
    def compile_project(self, work_dir: Path) -> bool:
        """Compile the project"""
        try:
            result = subprocess.run(
                [DEFECTS4J_EXECUTABLE, "compile"],
                check=True, capture_output=True, text=True, cwd=work_dir,
                timeout=300
            )
            print("✓ Project compiled successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to compile project: {e}")
            return False
    
    def _load_bug_test_map(self) -> Dict[str, str]:
        """Load bug->test mapping from bug_dataset.csv (first test only)."""
        candidates = [
            Path("data/bug_dataset.csv")
        ]
        csv_path = next((p for p in candidates if p.exists()), None)
        if not csv_path:
            print("[WARN] bug_dataset.csv not found; mutation will run without -t.")
            return {}

        bug_test_map: Dict[str, str] = {}
        try:
            with open(csv_path, 'r', encoding='utf-8') as infile:
                reader = csv.DictReader(infile)
                for row in reader:
                    bug_key = row.get('bug', '').strip()
                    failing_tests = row.get('failingTests', '').strip()
                    if not bug_key or not failing_tests:
                        continue
                    first_test = failing_tests.split(';')[0].strip()
                    if first_test:
                        bug_test_map[bug_key] = first_test
            print(f"[INFO] Loaded {len(bug_test_map)} bug test mappings from {csv_path}")
        except Exception as e:
            print(f"[WARN] Failed to read {csv_path}: {e}")
        return bug_test_map

    def get_target_test(self, project_id: str, bug_id: str) -> str:
        """Return the target failing test for a project/bug if available."""
        bug_key = f"{project_id}-{bug_id}"
        return self._bug_test_map.get(bug_key, "")

    def run_mutation_testing(self, work_dir: Path, test_name: str = "") -> bool:
        """Run mutation testing to generate mutants.log.

        On the buggy version the test suite fails, so defects4j mutation exits
        non-zero — but mutants.log is still written. We treat success as
        'mutants.log exists', not as a clean exit code.
        """
        mutation_cmd = [DEFECTS4J_EXECUTABLE, "mutation"]
        if test_name:
            mutation_cmd.extend(["-t", test_name])
        try:
            subprocess.run(
                mutation_cmd,
                capture_output=True, text=True, cwd=work_dir,
                timeout=720
            )
        except subprocess.TimeoutExpired:
            print("✗ Mutation testing timed out")
            return False
        except Exception as e:
            print(f"✗ Mutation testing failed to run: {e}")
            return False

        # Success is determined by mutants.log being created, not the exit code
        mutants_log = next(work_dir.rglob("mutants.log"), None)
        if mutants_log:
            print(f"✓ Mutation testing completed — mutants.log found at {mutants_log}")
            return True
        print("✗ Mutation testing: mutants.log not found after run")
        return False

    def run_coverage(self, work_dir: Path, test_name: str = "") -> bool:
        """Run defects4j coverage on an already-compiled project."""
        from config.settings import COVERAGE_TIMEOUT
        defects4j_cmd = self._get_defects4j_command()
        cmd = [defects4j_cmd, "coverage"]
        if test_name:
            cmd.extend(["-t", test_name])
        else:
            cmd.extend(["-r"])
        try:
            subprocess.run(
                cmd, check=True, capture_output=True, text=True,
                cwd=work_dir, timeout=COVERAGE_TIMEOUT
            )
            print("✓ Coverage completed")
            return True
        except subprocess.TimeoutExpired:
            print("✗ Coverage timed out")
            return False
        except Exception as e:
            print(f"✗ Coverage failed: {e}")
            return False

    def export_modified_classes(self, work_dir: Path) -> List[str]:
        """Run defects4j export -p classes.modified and return list of fully-qualified class names."""
        try:
            result = subprocess.run(
                [self._get_defects4j_command(), "export", "-p", "classes.modified"],
                capture_output=True, text=True, check=True,
                cwd=work_dir, timeout=60
            )
            classes = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            print(f"   Modified classes ({len(classes)}): {classes}")
            return classes
        except Exception as e:
            print(f"✗ Failed to export modified classes: {e}")
            return []

    def get_source_directories(self, work_dir: Path) -> List[Path]:
        """Find all source directories in the project"""
        source_dirs = []
        
        possible_dirs = [
            work_dir / "src",
            work_dir / "src/main/java",
            work_dir / "src/java",
            work_dir / "source",
            work_dir / "Source",
        ]
        
        # Check predefined directories
        for dir_path in possible_dirs:
            if dir_path.exists():
                source_dirs.append(dir_path)
        
        # Try Defects4J export
        try:
            proc = subprocess.run(
                [DEFECTS4J_EXECUTABLE, "export", "-p", "dir.src.classes"],
                capture_output=True, text=True, check=True, cwd=work_dir
            )
            def_src_dir = work_dir / proc.stdout.strip()
            if def_src_dir.exists() and def_src_dir not in source_dirs:
                source_dirs.append(def_src_dir)
        except:
            pass
        
        # Search for Java files
        java_dirs = set()
        for java_file in work_dir.rglob("*.java"):
            java_dirs.add(java_file.parent)
        
        for java_dir in java_dirs:
            if any(pattern in str(java_dir) for pattern in ['src', 'java', 'source']):
                if java_dir not in source_dirs:
                    source_dirs.append(java_dir)
        
        print(f"Found {len(source_dirs)} source directories")
        return source_dirs