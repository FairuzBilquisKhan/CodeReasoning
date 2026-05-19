import subprocess
import csv
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Tuple, List, Optional
import re

from config.settings import DEFECTS4J_EXECUTABLE, COVERAGE_TIMEOUT, COMPILE_TIMEOUT
from utils.file_ops import kill_processes_for_path, find_java_file_by_class


class CoverageRunner:
    """Handles coverage analysis and test execution"""
    
    def __init__(self):
        self.defects4j_cmd = DEFECTS4J_EXECUTABLE
        self._bug_test_map = self._load_bug_test_map()

    def _load_bug_test_map(self) -> Dict[str, str]:
        """Load bug->test mapping from bug_dataset.csv (first test only)."""
        candidates = [
            Path("data/bug_dataset.csv")
        ]
        csv_path = next((p for p in candidates if p.exists()), None)
        if not csv_path:
            print("[WARN] bug_dataset.csv not found; running coverage on full test suite.")
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
                    # take first test only (semicolon-separated list)
                    first_test = failing_tests.split(';')[0].strip()
                    if first_test:
                        bug_test_map[bug_key] = first_test
            print(f"[INFO] Loaded {len(bug_test_map)} bug test mappings from {csv_path}")
        except Exception as e:
            print(f"[WARN] Failed to read {csv_path}: {e}")
        return bug_test_map

    def _get_target_test(self, project_id: str, bug_id: str) -> str:
        """Return the target test for coverage, or empty string if not found."""
        bug_key = f"{project_id}-{bug_id}"
        return self._bug_test_map.get(bug_key, "")

    def run_defects4j_test(self, mutant_dir: Path) -> dict:
        """Run defects4j test and parse failed test cases and their names."""
        result = {
            'failed_count': 0,
            'failed_tests': [],
            'all_tests': [],
            'test_output': ''
        }
        try:
            proc = subprocess.run([
                self.defects4j_cmd, "test"
            ], capture_output=True, text=True, cwd=mutant_dir, timeout=COVERAGE_TIMEOUT)
            output = proc.stdout + proc.stderr
            result['test_output'] = output
            failed_tests = []
            in_failed_section = False
            for line in output.splitlines():
                if line.strip().startswith("Failing tests:"):
                    in_failed_section = True
                    continue
                if in_failed_section:
                    if not line.strip() or not line.strip().startswith("-"):
                        # End of failing tests section
                        in_failed_section = False
                        continue
                    # Extract test name after '- '
                    test_name = line.strip()[2:].strip()
                    if test_name:
                        failed_tests.append(test_name)
            result['failed_tests'] = failed_tests
            result['failed_count'] = len(failed_tests)
        except subprocess.TimeoutExpired:
            result['test_output'] = 'TIMEOUT'
        except Exception as e:
            result['test_output'] = f'ERROR: {e}'
        return result
    
    def run_command(self, command: List[str], working_dir: Path, step_name: str = "Command"):
        """Run a shell command with proper error handling"""
        print(f"    Running: {' '.join(command)}", flush=True)
        try:
            result = subprocess.run(
                command, check=True, capture_output=True, text=True,
                cwd=working_dir, timeout=COMPILE_TIMEOUT
            )
            return result
        except subprocess.TimeoutExpired:
            print(f"    {step_name} timed out after {COMPILE_TIMEOUT}s", flush=True)
            return None
        except subprocess.CalledProcessError as e:
            print(f"    Command failed: {e}", flush=True)
            if hasattr(e, 'stdout') and e.stdout:
                print(f"    stdout:\n{e.stdout}", flush=True)
            if hasattr(e, 'stderr') and e.stderr:
                print(f"    stderr:\n{e.stderr}", flush=True)
            return None
    
    def compile_mutant(self, mutant_dir: Path) -> bool:
        """Compile the mutant"""
        return bool(self.run_command([self.defects4j_cmd, "compile"], mutant_dir, "Compile mutant"))

    @staticmethod
    def _jvm_sig_to_java_params(signature: str) -> str:
        """Convert JVM signature like (ILjava/lang/String;[D)V to (int,java.lang.String,double[])."""
        if not signature or '(' not in signature or ')' not in signature:
            return signature
        params_str = signature[signature.find('(') + 1:signature.find(')')]
        primitives = {
            'B': 'byte', 'C': 'char', 'D': 'double', 'F': 'float',
            'I': 'int', 'J': 'long', 'S': 'short', 'Z': 'boolean',
        }
        params = []
        i = 0
        array_depth = 0
        while i < len(params_str):
            char = params_str[i]
            if char == '[':
                array_depth += 1
                i += 1
            elif char == 'L':
                end = params_str.find(';', i)
                if end == -1:
                    break
                class_ref = params_str[i + 1:end].replace('/', '.')
                params.append(class_ref + '[]' * array_depth)
                array_depth = 0
                i = end + 1
            elif char in primitives:
                params.append(primitives[char] + '[]' * array_depth)
                array_depth = 0
                i += 1
            else:
                i += 1
        return f"({','.join(params)})"

    @staticmethod
    def _count_params_from_jvm_signature(signature: str) -> int:
        """Count parameters in a JVM method signature like (I[Ljava/lang/String;)Z."""
        if not signature or '(' not in signature or ')' not in signature:
            return 0
        params = signature[signature.find('(') + 1:signature.find(')')]
        count = 0
        i = 0
        while i < len(params):
            char = params[i]
            if char == 'L':
                end = params.find(';', i)
                if end == -1:
                    break
                count += 1
                i = end + 1
            elif char == '[':
                i += 1
            else:
                count += 1
                i += 1
        return count

    @staticmethod
    def _find_method_start_line(source_file: Path, method_name: str, param_count: int) -> Optional[int]:
        """Find the start line of a method declaration in a Java source file."""
        if not method_name:
            return None
        try:
            lines = source_file.read_text(encoding='utf-8', errors='ignore').splitlines()
        except Exception:
            return None
        pattern = re.compile(rf"\b{re.escape(method_name)}\s*\(")
        for idx, line in enumerate(lines, start=1):
            line_no_comments = line.split('//', 1)[0]
            if not pattern.search(line_no_comments):
                continue
            if ')' in line_no_comments:
                params_in_line = line_no_comments[line_no_comments.find('(') + 1:line_no_comments.find(')')]
                found_count = len([p for p in params_in_line.split(',') if p.strip()])
                if found_count != param_count:
                    continue
            return idx
        return None

    @staticmethod
    def _format_branch_conditions(line_element: ET.Element) -> Tuple[str, str]:
        """Format branch condition coverage as (covered/total) and numbered condition list."""
        condition_coverage = line_element.get('condition-coverage', '')
        covered_total = None
        total_total = None
        ratio = ""
        match = re.search(r"\((\d+)\s*/\s*(\d+)\)", condition_coverage)
        if match:
            covered_total = int(match.group(1))
            total_total = int(match.group(2))
            ratio = f"({covered_total}/{total_total})"

        conditions = line_element.findall('./conditions/condition')
        if not conditions:
            return ratio, "[]"

        per_condition_total = None
        remainder = 0
        if total_total is not None and len(conditions) > 0:
            per_condition_total = total_total // len(conditions)
            remainder = total_total % len(conditions)

        formatted_conditions = []
        for idx, condition in enumerate(conditions):
            number = condition.get('number') or str(idx)
            coverage_text = condition.get('coverage', '')
            cond_match = re.search(r"\((\d+)\s*/\s*(\d+)\)", coverage_text)
            if cond_match:
                cond_covered = cond_match.group(1)
                cond_total = cond_match.group(2)
                formatted_conditions.append(f"{number}:{cond_covered}/{cond_total}")
                continue

            if per_condition_total is not None and per_condition_total > 0:
                percent_match = re.search(r"(\d+)", coverage_text)
                percent = int(percent_match.group(1)) if percent_match else 0
                extra = 1 if idx < remainder else 0
                total_for_condition = per_condition_total + extra
                covered_for_condition = round((percent / 100) * total_for_condition)
                formatted_conditions.append(f"{number}:{covered_for_condition}/{total_for_condition}")
            else:
                formatted_conditions.append(f"{number}:0/0")

        return ratio, f"({', '.join(formatted_conditions)})"
    
    def parse_coverage_xml(self, xml_file: Path, base_dir: Optional[Path] = None) -> Tuple[float, float, Dict[str, List[str]]]:
        """Parse coverage.xml and extract line-rate, branch-rate, and method coverage data"""
        method_data = {}
        line_rate = 0.0
        branch_rate = 0.0
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            # Get line-rate and branch-rate from root attributes
            line_rate = float(root.attrib.get('line-rate', '0'))
            branch_rate = float(root.attrib.get('branch-rate', '0'))
            for cls in root.findall('.//class'):
                class_name = cls.get('name')
                java_file = find_java_file_by_class(class_name, [base_dir]) if base_dir else None
                for method in cls.findall('.//method'):
                    method_name = method.get('name')
                    method_signature = method.get('signature', '')
                    java_params = self._jvm_sig_to_java_params(method_signature)
                    full_method_name = f"{class_name}:{method_name}{java_params}"
                    line_numbers = []
                    has_nonzero_hits = False
                    for line in method.findall('.//line'):
                        line_number = line.get('number')
                        hit_count = line.get('hits')
                        branch = line.get('branch')
                        if line_number:
                            parsed_hits = None
                            if hit_count is not None:
                                try:
                                    parsed_hits = int(hit_count)
                                except ValueError:
                                    parsed_hits = None
                            if parsed_hits is not None:
                                if parsed_hits <= 0:
                                    continue
                                has_nonzero_hits = True
                            if branch == 'true':
                                ratio, conditions_detail = self._format_branch_conditions(line)
                                line_numbers.append(
                                    f"{line_number}|{hit_count}|{ratio}|{conditions_detail}"
                                )
                            else:
                                line_numbers.append(f"{line_number}|{hit_count}")
                    if has_nonzero_hits:
                        method_data[full_method_name] = line_numbers
            return line_rate, branch_rate, method_data
        except Exception as e:
            print(f"Error parsing {xml_file}: {e}")
            return 0.0, 0.0, {}
    
    @staticmethod
    def build_covered_lines(xml_file: Path, modified_classes: List[str]) -> Dict[str, set]:
        """Parse coverage.xml and return {class_name: set(line_numbers with hits > 0)}
        restricted to classes listed in modified_classes."""
        modified_set = set(modified_classes)
        covered: Dict[str, set] = {}
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            for cls in root.findall('.//class'):
                class_name = cls.get('name', '')
                if class_name not in modified_set:
                    continue
                covered_lines: set = set()
                for line in cls.findall('.//line'):
                    try:
                        if int(line.get('hits', '0')) > 0:
                            covered_lines.add(int(line.get('number')))
                    except (ValueError, TypeError):
                        pass
                if covered_lines:
                    covered[class_name] = covered_lines
        except Exception as e:
            print(f"Error building covered lines from {xml_file}: {e}")
        return covered

    def parse_failing_tests(self, mutant_dir: Path) -> List[str]:
        """Parse failing tests from failing_tests file"""
        failing_tests_file = mutant_dir / "failing_tests"
        failed_tests = []
        
        if failing_tests_file.exists():
            try:
                with open(failing_tests_file, 'r', encoding='utf-8') as infile:
                    for line in infile:
                        stripped_line = line.strip()
                        if stripped_line.startswith('--- '):
                            test_name = stripped_line[4:].strip()
                            if test_name:
                                failed_tests.append(test_name)
            except Exception as e:
                print(f"Error reading failing tests: {e}")
        
        return failed_tests
    
    def read_all_tests(self, mutant_dir: Path) -> List[str]:
        """Read all tests from all_tests file"""
        all_tests_file = mutant_dir / "all_tests"
        all_tests = []
        
        if all_tests_file.exists():
            try:
                with open(all_tests_file, 'r') as f:
                    all_tests = [line.strip() for line in f if line.strip()]
            except Exception as e:
                print(f"Error reading all_tests: {e}")
        print(all_tests)
        return all_tests
    
    def run_coverage_analysis(self, mutant_dir: Path, project_id: str, bug_id: str) -> Dict:
        """Run comprehensive coverage analysis on mutant"""
        coverage_result = {
            'coverage_success': False,
            'coverage_output': '',
            'coverage_percentage': 0,
            'method_coverage': {},
            'branch_coverage': 0,
            'test_run': '',
        }
        
        try:
            # Compile mutant first (required before coverage)
            if not self.compile_mutant(mutant_dir):
                return coverage_result
            
            # Run coverage for line/method coverage
            target_test = self._get_target_test(project_id, bug_id)
            if target_test:
                print(f"   Running defects4j coverage for test: {target_test}")
                coverage_cmd = [self.defects4j_cmd, "coverage", "-t", target_test]
                coverage_result['test_run'] = target_test
            else:
                print("   Running defects4j coverage...")
                coverage_cmd = [self.defects4j_cmd, "coverage", "-r"]

            coverage_process = subprocess.run(
                coverage_cmd,
                capture_output=True, text=True, cwd=mutant_dir,
                timeout=COVERAGE_TIMEOUT
            )
            coverage_result['coverage_output'] = coverage_process.stdout + coverage_process.stderr
            coverage_result['coverage_success'] = (coverage_process.returncode == 0)

            # Parse coverage XML
            coverage_xml_file = mutant_dir / "coverage.xml"
            if coverage_xml_file.exists():
                line_rate, branch_coverage, method_data = self.parse_coverage_xml(coverage_xml_file, mutant_dir)
                coverage_result['coverage_percentage'] = line_rate
                coverage_result['branch_coverage'] = branch_coverage
                coverage_result['method_coverage'] = method_data
                print(f"   Line-rate: {coverage_result['coverage_percentage']:.4f}, Branch-coverage: {coverage_result['branch_coverage']:.4f}")
            # defects4j test is intentionally skipped (coverage only)

        except subprocess.TimeoutExpired:
            print("   Coverage command timed out")
            coverage_result['coverage_output'] = "TIMEOUT"
            try:
                kill_processes_for_path(mutant_dir)
                coverage_result['coverage_output'] += "; killed lingering processes"
            except Exception as e:
                coverage_result['coverage_output'] += f"; cleanup error: {e}"
        except Exception as e:
            print(f"   Error running coverage: {e}")
            coverage_result['coverage_output'] = f"ERROR: {str(e)}"

        return coverage_result

