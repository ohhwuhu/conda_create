"""conda_api.py - Pure logic layer for locating conda and managing environments.

The GUI (main.py) calls these functions. All conda invocations use the
absolute path of the located conda executable, so conda does not need to be
on PATH at runtime.
"""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_COMMON_ROOTS = (
    "miniconda3", "Miniconda3", "Anaconda3", "anaconda3",
    "miniforge3", "Miniforge3", "mambaforge", "Mambaforge",
)

DEFAULT_PYTHON_VERSIONS = ("3.13", "3.12", "3.11", "3.10", "3.9", "3.8")


class CondaError(Exception):
    pass


# ---------------------------------------------------------------- conda lookup

def _candidate_roots():
    roots = {Path.home() / name for name in _COMMON_ROOTS}
    for base in ("D:/app", "C:/ProgramData", "C:/"):
        roots.update(Path(base) / name for name in ("miniconda3", "anaconda3"))
    return list(roots)


def _find_in_root(root):
    for candidate in (
        root / "Scripts" / "conda.exe",
        root / "condabin" / "conda.bat",
        root / "conda.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def find_conda(preferred=None):
    """Locate a conda executable, returning its absolute path or None.

    Order: preferred -> CONDA_EXE env -> PATH -> common install roots.
    """
    for candidate in (preferred, os.environ.get("CONDA_EXE")):
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    found = shutil.which("conda")
    if found:
        return str(Path(found).resolve())
    for root in _candidate_roots():
        found = _find_in_root(root)
        if found:
            return str(Path(found).resolve())
    return None


# ---------------------------------------------------------------- subprocess run

def run_sync(args):
    """Run a command to completion. Returns (returncode, stdout, stderr)."""
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_streaming(args, on_out=None, on_err=None):
    """Run a command, feeding each output line to on_out/on_err callbacks.

    Reads stdout and stderr on separate threads to avoid pipe deadlock.
    Returns the exit code.
    """
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=CREATE_NO_WINDOW,
    )

    def pump(stream, callback):
        for line in stream:
            line = line.rstrip("\r\n")
            if line and callback:
                callback(line)

    t1 = threading.Thread(target=pump, args=(proc.stdout, on_out), daemon=True)
    t2 = threading.Thread(target=pump, args=(proc.stderr, on_err), daemon=True)
    t1.start()
    t2.start()
    rc = proc.wait()
    t1.join()
    t2.join()
    return rc


# ---------------------------------------------------------------- conda info

def conda_info(conda):
    """Return {'base': ..., 'envs_dirs': [...]}. Raises CondaError on failure."""
    rc, out, err = run_sync([conda, "info", "--base"])
    if rc != 0:
        raise CondaError((err or out).strip() or "无法获取 conda 信息")
    base = out.strip()
    envs_dirs = []
    rc2, out2, err2 = run_sync([conda, "config", "--show", "envs_dirs", "--json"])
    if rc2 == 0:
        try:
            envs_dirs = json.loads(out2).get("envs_dirs", [])
        except ValueError:
            envs_dirs = []
    if not envs_dirs:
        envs_dirs = [os.path.join(base, "envs")]
    return {"base": base, "envs_dirs": envs_dirs}


# ---------------------------------------------------------------- env management

def parse_env_paths(paths, base, envs_dirs):
    """Pure function: map raw env paths to {name, path, is_base}, base first."""
    base_norm = os.path.normcase(os.path.abspath(base))
    dirs_norm = {os.path.normcase(os.path.abspath(d)) for d in envs_dirs}
    envs = []
    for path in paths:
        ap = os.path.abspath(path)
        norm = os.path.normcase(ap)
        if norm == base_norm:
            name, is_base = "base", True
        elif os.path.normcase(os.path.dirname(ap)) in dirs_norm:
            name, is_base = os.path.basename(ap), False
        else:
            name, is_base = ap, False
        envs.append({"name": name, "path": ap, "is_base": is_base})
    envs.sort(key=lambda e: (not e["is_base"], e["name"].lower()))
    return envs


def list_envs(conda, base, envs_dirs):
    """Return a list of env dicts {name, path, is_base}, base first.

    Raises CondaError on failure.
    """
    rc, out, err = run_sync([conda, "env", "list", "--json"])
    if rc != 0:
        raise CondaError((err or out).strip() or "无法列出环境")
    try:
        data = json.loads(out)
    except ValueError:
        raise CondaError("解析 conda env list 输出失败")
    return parse_env_paths(data.get("envs", []), base, envs_dirs)


def resolve_prefix_env_path(path):
    """Return the folder the prefix env should live in.

    The chosen folder is the *project* directory; the environment goes into
    <folder>\\.conda. If the chosen folder is already named .conda, use it as-is.
    """
    p = path.strip()
    if not p:
        return p
    if os.path.basename(p.rstrip("\\/")) == ".conda":
        return p.rstrip("\\/")
    return os.path.join(p, ".conda")


def build_create_args(conda, *, name=None, prefix=None, python_version):
    """Build the argv for `conda create`, ready to run. Testable, no side effects."""
    if not (name or prefix):
        raise ValueError("必须提供环境名称或前缀路径")
    if not (python_version or "").strip():
        raise ValueError("必须指定 Python 版本")
    args = [conda, "create", "-y"]
    args += ["-n", name] if name else ["-p", prefix]
    args += [f"python={python_version.strip()}"]
    return args


def build_remove_args(conda, *, name=None, prefix=None):
    if not (name or prefix):
        raise ValueError("必须提供环境名称或前缀路径")
    args = [conda, "env", "remove", "-y"]
    args += ["-n", name] if name else ["-p", prefix]
    return args
