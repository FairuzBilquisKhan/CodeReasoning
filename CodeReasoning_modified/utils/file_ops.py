"""File operations utilities - PLATFORM INDEPENDENT"""

import os
import shutil
import signal
import subprocess
import time
import platform
from pathlib import Path
from typing import List, Optional


class FileOperations:
    """Utility class for file operations - PLATFORM INDEPENDENT"""
    
    def __init__(self):
        self.system = platform.system().lower()
    
    def clean_directory(self, directory: Path) -> bool:
        """Remove directory if it exists - PLATFORM INDEPENDENT"""
        if not directory.exists():
            return True
            
        try:
            shutil.rmtree(directory)
            return True
        except PermissionError:
            print(f"Permission error cleaning {directory}")
            if self.system == "windows":
                # Try alternative approach on Windows
                return self._clean_directory_windows(directory)
            return False
        except Exception as e:
            print(f"Error cleaning directory {directory}: {e}")
            return False
    
    def _clean_directory_windows(self, directory: Path) -> bool:
        """Windows-specific directory cleaning"""
        try:
            # Use Windows command for stubborn directories
            import subprocess
            subprocess.run(f'rmdir /S /Q "{directory}"', shell=True, check=True)
            return True
        except:
            return False
    
    def ensure_directory(self, directory: Path) -> bool:
        """Ensure directory exists - PLATFORM INDEPENDENT"""
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            print(f"Error creating directory {directory}: {e}")
            return False
    
    def get_relative_paths(self, absolute_paths: List[Path], base_dir: Path) -> List[Path]:
        """Convert absolute paths to relative paths - PLATFORM INDEPENDENT"""
        try:
            return [path.relative_to(base_dir) for path in absolute_paths]
        except ValueError as e:
            print(f"Error converting paths to relative: {e}")
            return []
    
    def read_file_lines(self, file_path: Path) -> List[str]:
        """Read file lines with platform-independent line ending handling"""
        try:
            with open(file_path, 'r', newline='', encoding='utf-8') as f:
                return f.readlines()
        except UnicodeDecodeError:
            # Fallback for different encodings
            with open(file_path, 'r', newline='', encoding='latin-1') as f:
                return f.readlines()
    
    def write_file_lines(self, file_path: Path, lines: List[str]) -> bool:
        """Write file lines with platform-appropriate line endings"""
        try:
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                f.writelines(lines)
            return True
        except Exception as e:
            print(f"Error writing file {file_path}: {e}")
            return False


def kill_processes_for_path(path: Path, timeout: int = 5) -> None:
    """Kill processes whose command line references the given path (SIGTERM then SIGKILL)."""
    try:
        out = subprocess.check_output(["pgrep", "-f", str(path)], text=True).strip()
        if not out:
            return
        pids = [int(p) for p in out.splitlines() if p.strip().isdigit()]
    except subprocess.CalledProcessError:
        return

    for pid in pids:
        try:
            print(f"   [CLEANUP] Terminating PID {pid} for path {path}")
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            continue

    time.sleep(timeout)

    for pid in pids:
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        try:
            print(f"   [CLEANUP] Killing PID {pid} (SIGKILL)")
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def find_java_file_by_class(class_name: str, base_dirs: List[Path]) -> Optional[Path]:
    """Find Java source file for a fully-qualified class name across base directories.

    Tries direct path, common Maven layouts, then a recursive glob fallback.
    """
    if not class_name:
        return None
    rel_path = class_name.replace('.', '/') + '.java'
    for base_dir in base_dirs:
        direct = base_dir / rel_path
        if direct.exists():
            return direct
        for prefix in ["src/main/java", "src/java"]:
            maven_path = base_dir / prefix / rel_path
            if maven_path.exists():
                return maven_path
        matches = list(base_dir.rglob(rel_path))
        if matches:
            return matches[0]
    return None