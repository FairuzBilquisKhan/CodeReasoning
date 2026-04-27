"""Parses mutants.log file and extracts mutation information"""

from pathlib import Path
from typing import List, Dict, Optional


class MutationParser:
    """Parses mutation information from mutants.log"""
    
    @staticmethod
    def find_mutants_log(work_dir: Path) -> Optional[Path]:
        """Find the mutants.log file in the project directory"""
        log_files = list(work_dir.rglob("mutants.log"))
        return log_files[0] if log_files else None
    
    @staticmethod
    def parse_mutant_line(line: str) -> Optional[Dict]:
        """
        Parse a single line from mutants.log
        Format: ID:MUTATOR:SIG_ORIG:SIG_MUT:CLASS@METHOD:LINE:CODE_ORIG |==> CODE_MUT
        """
        line = line.strip()
        if not line or line.startswith('#'):
            return None
        
        try:
            parts = line.split(':')
            if len(parts) < 8:
                return None
            
            mutant_id, mutator, original_sig, mutated_sig = parts[0:4]
            class_method = parts[4]
            line_num = parts[5] if len(parts) > 5 else ""
            target_file = None
            
            if len(parts) >= 9:
                target_file = parts[6]
                
                code = ":".join(parts[8:])
            else:
                garbage = parts[6] if len(parts) > 6 else ""
                code = ":".join(parts[7:]) if len(parts) > 7 else ""
            
            
            # Extract code change
            if '|==>' in code:
                original_code, mutated_code = code.split('|==>', 1)
                original_code = original_code.strip()
                mutated_code = mutated_code.strip()
                
                if mutated_code == '<NO-OP>':
                    mutated_code = "/*"+original_code+"*/"
            else:
                original_code = code.strip()
                mutated_code = ""
            
            # Extract class and method names
            if '@' in class_method:
                class_name, method_name = class_method.split('@')
                class_name = class_name.split('$')[0]  # Remove inner class part  
            else:
                class_name, method_name = class_method, ""
            
            # Convert line number
            try:
                line_number = int(line_num)
            except ValueError:
                return None
            
            match_index = None
            if mutator == "LVR":
                if original_sig.isdigit():
                    match_index = int(original_sig)
                elif mutated_sig.isdigit():
                    match_index = int(mutated_sig)

            return {
                'whole_log': line,
                'mutant_id': mutant_id,
                'mutator': mutator,
                'original_signature': original_sig,
                'mutated_signature': mutated_sig,
                'class_name': class_name,
                'method_name': method_name,
                'line_number': line_number,
                'original_code': original_code,
                'mutated_code': mutated_code,
                'target_file': target_file,
                'match_index': match_index
            }
            
        except Exception as e:
            print(f"Error parsing line: {e}")
            return None
    
    def parse_all_mutations(self, log_file: Path) -> List[Dict]:
        """Parse all mutations from mutants.log file"""
        print(f"Parsing mutations from {log_file.name}...")
        
        all_mutations = []
        
        try:
            with open(log_file, 'r') as f:
                for line in f:
                    mutation_info = self.parse_mutant_line(line)
                    if mutation_info:
                        all_mutations.append(mutation_info)
                        
        except Exception as e:
            print(f"Error parsing log file: {e}")
        
        print(f"Parsed {len(all_mutations)} total mutations")
        return all_mutations

    @staticmethod
    def load_kill_csv_ids(kill_csv: Path) -> List[str]:
        """Load mutant IDs marked as covered (anything except UNCOV) from kill.csv."""
        if not kill_csv.exists():
            print(f"kill.csv not found at {kill_csv}; no mutations will be kept.")
            return []
        ids: List[str] = []
        try:
            with open(kill_csv, 'r', encoding='utf-8') as f:
                for idx, line in enumerate(f):
                    if idx == 0 and "MutantNo" in line:
                        continue
                    parts = [p.strip() for p in line.strip().split(',')]
                    if len(parts) < 2:
                        continue
                    mutant_id, status = parts[0], parts[1].upper()
                    if status != "UNCOV":
                        ids.append(mutant_id)
        except Exception as e:
            print(f"Error reading kill.csv: {e}")
        return ids

    @staticmethod
    def filter_mutations_by_kill_csv(mutations: List[Dict], kill_csv: Path) -> List[Dict]:
        """Filter mutations to those marked as covered (not UNCOV) in kill.csv."""
        kill_ids = set(MutationParser.load_kill_csv_ids(kill_csv))
        if not kill_ids:
            print("No mutations retained because kill.csv is missing or empty.")
            return []
        filtered = [m for m in mutations if str(m.get('mutant_id')) in kill_ids]
        print(f"Filtered mutations by kill.csv: {len(filtered)} of {len(mutations)}")
        return filtered