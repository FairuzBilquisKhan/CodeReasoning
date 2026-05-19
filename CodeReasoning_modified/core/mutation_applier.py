"""Applies mutations to source files - SIMPLIFIED & FIXED"""

import hashlib
import shutil
import random
import re
from pathlib import Path
from typing import List, Optional, Dict, Any


class MutationApplier:
    """Handles mutation application - SIMPLIFIED for reliability"""
    
    def __init__(self, random_seed: int = 42, project_id: str = "", bug_id: str = ""):
        self.random_seed = random_seed
        self.project_id = project_id
        self.bug_id = bug_id
        
        # Simple deterministic seed based on inputs
        seed_value = random_seed
        if project_id and bug_id:
            # Simple deterministic calculation without hash()
            seed_str = f"{project_id}{bug_id}{random_seed}"
            seed_value = sum(ord(c) for c in seed_str) % (2**31)
        
        self.rng = random.Random(seed_value)
    
    def generate_unique_mutants(self, all_mutations: List[Dict], num_mutants: int, 
                              max_mutations: int) -> List[Dict]:
        """
        Generate unique mutants - SIMPLIFIED deterministic algorithm
        """
        # 1. Sort mutations for consistency
        sorted_mutations = sorted(all_mutations,
                                 key=lambda x: (x['class_name'],
                                               x['line_number'],
                                               x['mutator'],
                                               x['original_code']))
        
        # 2. Simple deterministic selection
        unique_mutants = []
        used_combinations = set()
        
        for mutant_num in range(1, num_mutants + 1):
            # Create seed for this mutant
            mutant_seed = self.random_seed + mutant_num * 1000
            
            # Determine number of mutations
            temp_rng = random.Random(mutant_seed)
            num_for_mutant = temp_rng.randint(1, max_mutations)
            
            # Select mutations
            selected = []
            for i in range(num_for_mutant):
                # Deterministic index selection
                idx = (mutant_seed + i * 17) % len(sorted_mutations)
                selected.append(sorted_mutations[idx])
            
            # Sort and create signature
            selected.sort(key=lambda x: (x['class_name'], x['line_number']))
            
            # Simple signature without hash()
            signature_parts = []
            for m in selected:
                part = f"{m['class_name']}:{m['line_number']}:{m['mutator']}"
                signature_parts.append(part)
            signature = "|".join(signature_parts)
            
            # Ensure uniqueness
            if signature in used_combinations:
                # Try alternative selection
                alt_seed = mutant_seed + 9999
                alt_rng = random.Random(alt_seed)
                num_for_mutant = alt_rng.randint(1, max_mutations)
                selected = []
                for i in range(num_for_mutant):
                    idx = (alt_seed + i * 23) % len(sorted_mutations)
                    selected.append(sorted_mutations[idx])
                
                selected.sort(key=lambda x: (x['class_name'], x['line_number']))
                signature_parts = []
                for m in selected:
                    part = f"{m['class_name']}:{m['line_number']}:{m['mutator']}"
                    signature_parts.append(part)
                signature = "|".join(signature_parts)
            
            if signature not in used_combinations:
                used_combinations.add(signature)
                
                combined_id = '|'.join([str(m.get('mutant_id', '')) for m in selected]) if selected else f"gen_{len(unique_mutants) + 1}"

                mutant_info = {
                    'mutant_id': combined_id,
                    'mutations': selected,
                    'num_mutations': len(selected),
                    'mutators': sorted([m['mutator'] for m in selected]),
                    'signature': signature,
                    'project_id': self.project_id,
                    'bug_id': self.bug_id,
                    'generation_seed': mutant_seed
                }
                
                if selected:
                    first = selected[0]
                    whole_logs = [m.get('whole_log', '') for m in selected if m.get('whole_log')]
                    method_names = []
                    for m in selected:
                        name = m.get('method_name', '')
                        if name and name not in method_names:
                            method_names.append(name)
                    mutant_info.update({
                        'mutator': first['mutator'],
                        'class_name': first['class_name'],
                        'method_name': " | ".join(method_names) if method_names else first.get('method_name', ''),
                        'method_names': method_names,
                        'line_number': first['line_number'],
                        'original_code': first['original_code'],
                        'mutated_code': first['mutated_code'],
                        'whole_log': " || ".join(whole_logs) if whole_logs else first.get('whole_log', ''),
                        'whole_logs': whole_logs
                    })
                
                unique_mutants.append(mutant_info)
        
        print(f"Generated {len(unique_mutants)} unique mutants for {self.project_id}-{self.bug_id}")
        return unique_mutants
    
    # ... rest of the class methods remain the same ...
    
    def _create_mutation_signature(self, mutations: List[Dict], combined_id: str = "") -> str:
        """Create deterministic signature for mutations including combined_id"""
        parts = []
        
        # Include combined_id in signature
        if combined_id:
            parts.append(f"ID:{combined_id}")
        
        # Add mutation details
        for m in sorted(mutations, key=lambda x: (x.get('mutant_id', ''), 
                                                 x['class_name'], 
                                                 x['line_number'])):
            part = (f"{m.get('mutant_id', '')}:{m['class_name']}:{m['line_number']}:{m['mutator']}:"
                   f"{hashlib.md5(m['original_code'].encode()).hexdigest()[:8]}:"
                   f"{hashlib.md5(m['mutated_code'].encode()).hexdigest()[:8]}")
            parts.append(part)
        
        return "||".join(parts)

    @staticmethod
    def _count_params(param_str: str) -> int:
        """Count parameters in a method signature string."""
        params = [p.strip() for p in param_str.split(',') if p.strip()]
        return len(params)

    @staticmethod
    def find_method_start_line(source_file: Path, method_name: str) -> Optional[int]:
        """Find the line number where a method declaration starts."""
        if not method_name:
            return None

        base_name = method_name.split('(')[0].strip()
        param_str = ""
        if '(' in method_name and ')' in method_name:
            param_str = method_name[method_name.find('(') + 1:method_name.rfind(')')]
            expected_param_count = MutationApplier._count_params(param_str)
        else:
            expected_param_count = None

        try:
            with open(source_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except Exception:
            return None

        pattern = re.compile(rf"\b{re.escape(base_name)}\s*\(")

        for idx, line in enumerate(lines, start=1):
            line_no_comments = line.split("//", 1)[0]
            if "class " in line_no_comments:
                continue
            if not pattern.search(line_no_comments):
                continue

            if ')' in line_no_comments:
                params_in_line = line_no_comments[line_no_comments.find('(') + 1:line_no_comments.find(')')]
                param_count = MutationApplier._count_params(params_in_line)
                if expected_param_count is not None and param_count != expected_param_count:
                    continue

            return idx

        return None

    @staticmethod
    def get_relative_line_number(source_file: Path, method_name: str, absolute_line: int) -> Optional[int]:
        """Convert an absolute line number to a method-relative line number."""
        start_line = MutationApplier.find_method_start_line(source_file, method_name)
        if start_line is None:
            return None
        relative_line = absolute_line - start_line
        return relative_line if relative_line >= 0 else None
    
    @staticmethod
    def apply_mutation_to_file(source_file: Path, line_number: int, 
                             original_code: str, mutated_code: str,
                             match_index: Optional[int] = None) -> bool:
        """Apply mutation to a specific file"""
        try:
            if not source_file.exists():
                return False
            
            with open(source_file, 'r') as f:
                lines = f.readlines()
            
            if line_number < 1 or line_number > len(lines):
                return False
            
            target_line_index = line_number - 1
            original_line = lines[target_line_index]
            
            def replace_nth_whole_match(line: str, old: str, new: str, index: int) -> Optional[str]:
                if not old:
                    return None
                pattern = rf"(?<!\S){re.escape(old)}(?!\S)"
                matches = list(re.finditer(pattern, line))
                if index < 0 or index >= len(matches):
                    return None
                match = matches[index]
                return line[:match.start()] + new + line[match.end():]

            def replace_all_whole_matches(line: str, old: str, new: str) -> Optional[str]:
                if not old:
                    return None
                pattern = rf"(?<!\S){re.escape(old)}(?!\S)"
                if not re.search(pattern, line):
                    return None
                return re.sub(pattern, new, line)

            token = original_code.strip()
            if not token:
                return False

            if match_index is not None:
                mutated_line = replace_nth_whole_match(original_line, token, mutated_code, match_index)
                if mutated_line is None:
                    return False
            else:
                mutated_line = replace_all_whole_matches(original_line, token, mutated_code)
                if mutated_line is None:
                    return False

            lines[target_line_index] = mutated_line
            
            # Write the modified content back
            with open(source_file, 'w') as f:
                f.writelines(lines)
            
            return True
            
        except Exception as e:
            print(f"Error applying mutation: {e}")
            return False
    
    def apply_multiple_mutations(self, source_file: Path, mutations: List[Dict]) -> bool:
        """Apply multiple mutations to a single file"""
        try:
            if not source_file.exists():
                return False
            
            with open(source_file, 'r') as f:
                lines = f.readlines()
            
            # Sort mutations by line number (descending) to avoid line number shifts
            mutations_sorted = sorted(mutations, key=lambda x: x['line_number'], reverse=True)
            
            for mutation in mutations_sorted:
                line_number = mutation['line_number']
                original_code = mutation['original_code']
                mutated_code = mutation['mutated_code']
                match_index = mutation.get('match_index')

                if line_number < 1 or line_number > len(lines):
                    continue
                
                target_line_index = line_number - 1
                original_line = lines[target_line_index]
                
                def replace_nth_whole_match(line: str, old: str, new: str, index: int) -> Optional[str]:
                    if not old:
                        return None
                    pattern = rf"(?<!\S){re.escape(old)}(?!\S)"
                    matches = list(re.finditer(pattern, line))
                    if index < 0 or index >= len(matches):
                        return None
                    match = matches[index]
                    return line[:match.start()] + new + line[match.end():]

                def replace_all_whole_matches(line: str, old: str, new: str) -> Optional[str]:
                    if not old:
                        return None
                    pattern = rf"(?<!\S){re.escape(old)}(?!\S)"
                    if not re.search(pattern, line):
                        return None
                    return re.sub(pattern, new, line)

                token = original_code.strip()
                if not token:
                    continue

                if match_index is not None:
                    mutated_line = replace_nth_whole_match(original_line, token, mutated_code, match_index)
                    if mutated_line is None:
                        continue
                else:
                    mutated_line = replace_all_whole_matches(original_line, token, mutated_code)
                    if mutated_line is None:
                        continue

                lines[target_line_index] = mutated_line
            
            # Write all changes at once
            with open(source_file, 'w') as f:
                f.writelines(lines)
            
            return True
            
        except Exception as e:
            print(f"Error applying multiple mutations: {e}")
            return False
    
    def create_project_copy(self, original_dir: Path, copy_dir: Path) -> bool:
        """Create a fast copy of the project (ignoring heavy artifacts)"""
        if copy_dir.exists():
            shutil.rmtree(copy_dir)
        
        try:
            shutil.copytree(
                original_dir, 
                copy_dir, 
                ignore=shutil.ignore_patterns('.git', 'mutants.log', '*.tar.gz')
            )
            return True
        except Exception as e:
            print(f"Error creating project copy: {e}")
            return False