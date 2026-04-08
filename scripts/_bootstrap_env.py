import os
import sys
from pathlib import Path


def ensure_local_venv() -> None:
    """Re-exec the script inside the skill-local virtualenv when available."""
    script_dir = Path(__file__).resolve().parent
    venv_dir = script_dir.parent / ".venv"
    venv_python = venv_dir / "bin" / "python"

    if not venv_python.exists():
        return

    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir.resolve():
        return

    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["PATH"] = f"{venv_dir / 'bin'}:{env.get('PATH', '')}"
    os.execve(str(venv_python), [str(venv_python), *sys.argv], env)
