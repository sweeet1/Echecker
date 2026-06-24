"""环境检测模块 —— 检测 + 包管理 + 安装 + 全盘扫描 (全部环境)"""
import subprocess
import shutil
import os
import sys
import webbrowser
import glob as _glob
import string
import time
import re


# ═══════════════════════════════════════════════════
# 镜像源
# ═══════════════════════════════════════════════════
PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
PYPI_OFFICIAL = "https://pypi.org/simple"
NPM_MIRROR  = "https://registry.npmmirror.com"

PIP_TRUSTED_HOSTS = ["--trusted-host", "pypi.tuna.tsinghua.edu.cn"]

# ═══════════════════════════════════════════════════
# 常用包清单
# ═══════════════════════════════════════════════════
PYTHON_COMMON = [
    "numpy", "pandas", "requests", "matplotlib", "scipy",
    "scikit-learn", "flask", "django", "pytest", "jupyter",
]

NODE_COMMON = [
    "typescript", "nodemon", "pm2", "eslint", "prettier",
    "yarn", "pnpm", "vite", "ts-node", "create-react-app",
]

CONDA_COMMON = [
    "numpy", "pandas", "scipy", "matplotlib", "jupyter",
    "scikit-learn", "torch", "tensorflow", "opencv", "pillow",
]

PACKAGE_ALIASES = {
    "torch": {"torch", "pytorch"},
    "pytorch": {"torch", "pytorch"},
    "scikit-learn": {"scikit-learn", "scikit_learn", "sklearn"},
    "scikit_learn": {"scikit-learn", "scikit_learn", "sklearn"},
    "beautifulsoup4": {"beautifulsoup4", "bs4"},
    "opencv": {"opencv-python", "opencv", "cv2"},
    "opencv-python": {"opencv-python", "opencv", "cv2"},
    "pillow": {"pillow", "pil"},
    "tensorflow": {"tensorflow", "tensorflow-gpu"},
    "openai": {"openai", "openai-python"},
    "yaml": {"pyyaml", "ruamel.yaml"},
}

DOWNLOAD_URLS = {
    "Python":    "https://www.python.org/downloads/",
    "Java JDK":  "https://adoptium.net/download/",
    "C/C++":     "https://www.msys2.org/",
    "Node.js":   "https://nodejs.org/",
    "Git":       "https://git-scm.com/download/win",
    "Go":        "https://go.dev/dl/",
    ".NET":      "https://dotnet.microsoft.com/download",
    "Conda":     "https://docs.conda.io/en/latest/miniconda.html",
    "Docker":    "https://www.docker.com/products/docker-desktop/",
}

def _pkg_in_list(pkg, pkg_list):
    pkg_lower = pkg.lower()
    if pkg_lower in pkg_list: return True
    for alias in PACKAGE_ALIASES.get(pkg_lower, set()):
        if alias.lower() in pkg_list: return True
    return False

def _compute_missing(common_list, installed):
    return [p for p in common_list if not _pkg_in_list(p, installed)]

CREATE_NO_WINDOW = 0x08000000

# ═══════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════

def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           creationflags=CREATE_NO_WINDOW)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        return r.returncode, out
    except FileNotFoundError: return -1, ""
    except subprocess.TimeoutExpired: return -2, "timeout"
    except Exception as e: return -3, str(e)

def _clean_progress(output):
    result = []
    for ch in output:
        if ch == '\x08':
            if result and result[-1] != '\n': result.pop()
        else: result.append(ch)
    cleaned = ''.join(result)
    cleaned = re.sub(r'\n[ /\-\\|]+\n', '\n', cleaned)
    cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

def _run_stream(cmd, timeout=300, cancel_event=None, fail_keywords=None):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace",
                             creationflags=CREATE_NO_WINDOW)
        start = time.monotonic()
        collected = []
        while True:
            if cancel_event and cancel_event.is_set():
                p.terminate()
                try: rest = p.stdout.read()
                except: rest = ""
                return -4, _clean_progress("".join(collected + [rest]) + "\n\n已取消。")
            if p.poll() is not None:
                rest = p.stdout.read()
                return p.returncode, _clean_progress("".join(collected + [rest]))
            try: line = p.stdout.readline()
            except: time.sleep(0.05); continue
            if line:
                collected.append(line)
                if fail_keywords:
                    combined = "".join(collected)
                    for kw in fail_keywords:
                        if kw in combined:
                            p.terminate()
                            try: rest = p.stdout.read()
                            except: rest = ""
                            return -5, _clean_progress("".join(collected + [rest]))
            if timeout and time.monotonic() - start > timeout:
                p.kill()
                rest = p.stdout.read()
                return -2, _clean_progress("".join(collected + [rest]) + "\n\n超时。")
            time.sleep(0.05)
    except Exception as e: return -3, str(e)

def _extract_error_brief(out):
    lines = [l.strip() for l in (out or "").split("\n") if l.strip() and "===" not in l]
    if not lines: return ""
    last = lines[-3:]
    return " | ".join(last[-2:])

def _short_error(out):
    """从输出中提取一句简短的错误原因"""
    lines = (out or "").split("\n")
    for l in lines:
        l = l.strip()
        if "Forbidden" in l: return "403 禁止访问"
        if "ConnectionError" in l or "Connection" in l: return "网络连接失败"
        if "Timeout" in l or "timeout" in l.lower(): return "请求超时"
        if "not found" in l.lower(): return "包未找到"
        if "CondaHTTPError" in l: return "conda 源 403"
        if "ERR!" in l: return l[:80]
    return "未知错误"

def open_url(url):
    webbrowser.open(url)

def get_available_drives():
    drives = []
    for letter in string.ascii_uppercase:
        if os.path.exists(letter + ":\\"): drives.append(letter + ":")
    return drives

# ═══════════════════════════════════════════════════
# 全盘扫描引擎
# ═══════════════════════════════════════════════════

def _scan_drive_for_exe(drive, exe_name, patterns, version_args=["--version"],
                        version_transform=None, get_label=None, timeout=10):
    if get_label is None: get_label = os.path.basename
    if version_transform is None: version_transform = lambda v: v
    found = {}
    for pattern in patterns:
        full = pattern % drive
        matches = _glob.glob(full)
        for m in matches:
            if os.path.isdir(m):
                exe = os.path.join(m, exe_name)
                if os.path.isfile(exe):
                    try: rp = os.path.realpath(exe)
                    except: rp = exe
                    if rp not in found: found[rp] = (exe, get_label(os.path.basename(m)))
                for sub in ["Scripts", "bin"]:
                    exe2 = os.path.join(m, sub, exe_name)
                    if os.path.isfile(exe2):
                        try: rp = os.path.realpath(exe2)
                        except: rp = exe2
                        if rp not in found: found[rp] = (exe2, get_label(os.path.basename(m)))
            elif m.endswith(exe_name) and os.path.isfile(m):
                try: rp = os.path.realpath(m)
                except: rp = m
                if rp not in found: found[rp] = (m, get_label(os.path.basename(os.path.dirname(m))))
    results = []
    for rp, (exe_path, label) in found.items():
        rc, out = _run([exe_path] + version_args, timeout=timeout)
        if rc == 0 and out:
            v = version_transform(out)
            dl = os.path.splitdrive(exe_path)[0] or drive
            results.append((exe_path, v, label, dl))
    return results

def _simple_label(d):
    d = d.lower()
    if "anaconda" in d: return "Anaconda"
    if "miniconda" in d: return "Miniconda"
    if "python" in d: return d.title()
    if any(x in d for x in ("java", "jdk", "adoptium", "temurin")): return "JDK"
    if "node" in d: return "Node.js"
    if "git" in d: return "Git"
    if "go" in d: return "Go"
    if "dotnet" in d: return ".NET"
    if "docker" in d: return "Docker"
    if "mingw" in d or "msys" in d: return "MinGW/MSYS"
    if any(x in d for x in ("visual", "studio", "microsoft")): return "VS/MSVC"
    return d

_PYTHON_PATTERNS = [
    r"%s\Python*", r"%s\Program Files\Python*", r"%s\Program Files (x86)\Python*",
    r"%s\*anaconda*", r"%s\*miniconda*", r"%s\ProgramData\*anaconda*", r"%s\ProgramData\*miniconda*",
    r"%s\Users\*\AppData\Local\Programs\Python\*", r"%s\Users\*\anaconda*",
    r"%s\Users\*\miniconda*", r"%s\Users\*\.conda\envs\*",
]

_JAVA_PATTERNS = [
    r"%s\Program Files\Java\*", r"%s\Program Files (x86)\Java\*",
    r"%s\Program Files\Eclipse Adoptium\*", r"%s\Program Files\Eclipse Foundation\*",
    r"%s\Program Files\Microsoft\jdk*", r"%s\Program Files\Semeru\*",
    r"%s\Program Files\ojdkbuild\*", r"%s\Program Files\Zulu\*",
    r"%s\Program Files\Amazon Corretto\*",
]

_CPP_PATTERNS = [
    r"%s\msys64\*", r"%s\mingw64\*", r"%s\mingw32\*",
    r"%s\Program Files\mingw-w64\*", r"%s\Program Files (x86)\mingw-w64\*",
    r"%s\cygwin64\*", r"%s\cygwin\*",
    r"%s\Program Files\Microsoft Visual Studio\*\*\VC\Tools\MSVC\*\bin\Hostx64\x64\*",
    r"%s\Program Files (x86)\Microsoft Visual Studio\*\*\VC\Tools\MSVC\*\bin\Hostx64\x64\*",
    r"%s\Program Files\CMake\*", r"%s\Program Files (x86)\CMake\*",
]

_NODEJS_PATTERNS = [
    r"%s\Program Files\nodejs\*", r"%s\Program Files (x86)\nodejs\*",
    r"%s\Users\*\AppData\Roaming\npm\*", r"%s\Users\*\AppData\Local\Programs\nodejs\*",
]

_GIT_PATTERNS = [
    r"%s\Program Files\Git\bin\*", r"%s\Program Files (x86)\Git\bin\*",
    r"%s\Program Files\Git\cmd\*", r"%s\Program Files (x86)\Git\cmd\*",
]

def _dedup_by_install_root(results, root_level=2):
    seen_roots = set()
    deduped = []
    for item in results:
        parts = item[0].replace("\\", "/").split("/")
        idx = len(parts) - root_level - 1
        if idx < 0: deduped.append(item); continue
        root = "/".join(parts[:idx+1]).lower()
        if root not in seen_roots: seen_roots.add(root); deduped.append(item)
    return deduped

_GO_PATTERNS = [r"%s\Program Files\Go\*", r"%s\Program Files (x86)\Go\*"]
_DOTNET_PATTERNS = [r"%s\Program Files\dotnet\*", r"%s\Program Files (x86)\dotnet\*"]
_CONDA_PATTERNS = [
    r"%s\*anaconda*", r"%s\*miniconda*", r"%s\ProgramData\*anaconda*", r"%s\ProgramData\*miniconda*",
    r"%s\Users\*\anaconda*", r"%s\Users\*\miniconda*", r"%s\Users\*\.conda\envs\*",
]
_DOCKER_PATTERNS = [r"%s\Program Files\Docker\Docker\*", r"%s\Program Files\Docker\*"]

# ═══════════════════════════════════════════════════
# 构建结果
# ═══════════════════════════════════════════════════

def _make_result(name, found, version="", path="", details=None,
                 installed=None, missing=None, env_type="system", deletable=False):
    lookup = name.split("(")[0].strip() if "(" in name else name
    return {
        "name": name, "found": found, "version": version,
        "path": path, "details": details or {},
        "download_url": DOWNLOAD_URLS.get(lookup, ""),
        "installed_pkgs": installed or [], "missing_pkgs": missing or [],
        "env_type": env_type, "deletable": deletable,
        "supports_envs": env_type in ("python", "conda", "python_venv", "conda_env"),
        "children": [],
    }

def _display_name(base_name, label, drive_letter):
    return "%s (%s, %s)" % (base_name, label, drive_letter)

# ═══════════════════════════════════════════════════
# 包列表
# ═══════════════════════════════════════════════════

def _get_python_packages_for(python_exe):
    pip_exe = os.path.join(os.path.dirname(python_exe), "pip.exe")
    if not os.path.isfile(pip_exe):
        pip_exe = os.path.join(os.path.dirname(python_exe), "Scripts", "pip.exe")
    if not os.path.isfile(pip_exe):
        rc, out = _run([python_exe, "-m", "pip", "list", "--format=freeze"], timeout=20)
        if rc != 0: return []
    else:
        rc, out = _run([pip_exe, "list", "--format=freeze"], timeout=20)
        if rc != 0: return []
    return [l.split("==")[0].lower() for l in out.split("\n") if "==" in l]

def get_python_packages(): return _get_python_packages_for(sys.executable)

def get_node_packages():
    rc, out = _run(["npm", "list", "-g", "--depth=0"], timeout=20)
    if rc != 0: return []
    pkgs = []
    for line in out.split("\n"):
        line = line.strip()
        if line.startswith("├──") or line.startswith("└──") or line.startswith("+--") or line.startswith("`--"):
            pkg = line[4:].split("@")[0].strip() if len(line) > 4 else ""
            if pkg: pkgs.append(pkg.lower())
    return pkgs

def _get_conda_packages_with(conda_exe):
    rc, out = _run([conda_exe, "list"], timeout=30)
    if rc != 0: return []
    pkgs = []
    for line in out.split("\n"):
        if line.startswith("#") or not line.strip(): continue
        parts = line.split()
        if parts: pkgs.append(parts[0].lower())
    return pkgs

def get_conda_packages(): return _get_conda_packages_with("conda")

def get_dotnet_tools():
    rc, out = _run(["dotnet", "tool", "list", "-g"], timeout=20)
    if rc != 0: return []
    pkgs = []
    for line in out.split("\n"):
        parts = line.split()
        if parts and "." not in parts[0] and len(parts) >= 2: pkgs.append(parts[0].lower())
    return pkgs

# ═══════════════════════════════════════════════════
# 安装/卸载 — 带回退链 + 进度回调
# ═══════════════════════════════════════════════════

def _package_lookup_name(pkg):
    name = (pkg or "").strip().strip('"').strip("'")
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", " "):
        if sep in name: name = name.split(sep, 1)[0]
    return name.strip()

def _python_exe_for_target(target=None):
    if isinstance(target, dict):
        env_type = target.get("env_type", "")
        path = target.get("path", "")
        if env_type == "python_venv" and path:
            for rel in (r"Scripts\python.exe", r"bin\python", r"bin\python3"):
                cand = os.path.join(path, rel)
                if os.path.isfile(cand): return cand
        if env_type == "python" and path and os.path.isfile(path): return path
    return shutil.which("python") or shutil.which("python3") or sys.executable

def _conda_exe_for_target(target=None):
    if isinstance(target, dict):
        path = target.get("path", "")
        if target.get("env_type") == "conda" and path and os.path.isfile(path): return path
        conda_exe = target.get("details", {}).get("conda_exe", "")
        if conda_exe and os.path.isfile(conda_exe): return conda_exe
        conda_root = target.get("details", {}).get("conda根", "")
        for rel in (r"Scripts\conda.exe", r"condabin\conda.bat"):
            cand = os.path.join(conda_root, rel)
            if os.path.isfile(cand): return cand
    return shutil.which("conda") or "conda"

def _find_python_in_env(env_path):
    for sub in ["python.exe", os.path.join("Scripts", "python.exe"),
                os.path.join("bin", "python"), os.path.join("bin", "python3")]:
        py = os.path.join(env_path, sub)
        if os.path.isfile(py): return py
    return None

def _get_all_env_pkgs(conda_exe, env_path):
    pkgs = set()
    for p in _get_conda_env_packages(conda_exe, env_path): pkgs.add(p.lower())
    python = _find_python_in_env(env_path)
    if python:
        for p in _get_python_packages_for(python): pkgs.add(p.lower())
    return list(pkgs)

# --- 安装 ---

def install_python_package(pkg, target=None, cancel_event=None, on_progress=None):
    python = _python_exe_for_target(target)
    methods = []

    methods.append("pip-清华")
    if on_progress: on_progress("pip 清华镜像源")
    cmd = [python, "-m", "pip", "install", "-i", PYPI_MIRROR] + PIP_TRUSTED_HOSTS + [pkg]
    rc, out = _run_stream(cmd, timeout=300, cancel_event=cancel_event,
                          fail_keywords=["403 Forbidden", "ConnectionError"])
    if rc == 0 and "Successfully installed" in out: return True, out

    methods.append("pip-官方")
    if on_progress: on_progress("pip 切换到官方源")
    cmd2 = [python, "-m", "pip", "install", "-i", PYPI_OFFICIAL, pkg]
    rc, out = _run_stream(cmd2, timeout=300, cancel_event=cancel_event)
    if rc == -4: return False, out

    ok = rc == 0 and "Successfully installed" in (out or "")
    if not ok:
        brief = _short_error(out or "")
        out = (out or "") + "\n\n[已尝试] %s\n均失败，原因: %s" % (" → ".join(methods), brief)
    return ok, out or ""

def install_node_package(pkg, target=None, cancel_event=None, on_progress=None):
    if on_progress: on_progress("npm 淘宝镜像源")
    cmd = ["npm", "install", "-g", "--registry=" + NPM_MIRROR, pkg]
    rc, out = _run_stream(cmd, timeout=300, cancel_event=cancel_event)
    if rc == -4: return False, out
    ok = rc == 0 and "ERR!" not in out
    if not ok:
        brief = _short_error(out or "")
        out = (out or "") + "\n\n[已尝试] npm-淘宝镜像\n失败，原因: %s" % brief
    return ok, out or ""

def install_conda_package(pkg, target=None, cancel_event=None, on_progress=None):
    return _conda_install_or_remove(pkg, target, "install", cancel_event, on_progress)

def _conda_install_or_remove(pkg, target, action, cancel_event=None, on_progress=None):
    conda_exe = _conda_exe_for_target(target)
    env_path = ""
    if isinstance(target, dict) and target.get("env_type") == "conda_env":
        env_path = target.get("path", "")

    methods = []
    last_out = ""

    channel_sets = [
        (["-c", "conda-forge", "-c", "defaults"], "conda-forge+defaults"),
        (["-c", "conda-forge"], "conda-forge"),
        (["-c", "defaults"], "defaults"),
    ]
    all_failed = True
    for channels, label in channel_sets:
        methods.append("conda(%s)" % label)
        if on_progress: on_progress("conda %s (%s)" % (action, label))
        cmd = [conda_exe, action, "-y"] + channels
        if env_path: cmd.extend(["-p", env_path])
        cmd.append(pkg)
        rc, out = _run_stream(cmd, timeout=120, cancel_event=cancel_event,
                              fail_keywords=["CondaHTTPError", "403 Forbidden"])
        last_out = out or ""
        if rc == -4: return False, out or ""
        if rc == -5:
            err = _short_error(out or "")
            if on_progress: on_progress("conda 失败 (%s)" % err)
            continue
        if rc == 0 and "Executing transaction" in out:
            all_failed = False
            break
        err = _short_error(out or "")
        if on_progress: on_progress("conda 失败 (%s)" % err)

    if all_failed:
        python = _find_python_in_env(env_path) if env_path else _python_exe_for_target(target)
        if python:
            methods.append("pip-回退")
            if on_progress: on_progress("conda 全部失败，回退 pip")
            if action == "install":
                py_cmd = [python, "-m", "pip", "install",
                          "-i", PYPI_MIRROR] + PIP_TRUSTED_HOSTS + [pkg]
                rc2, out2 = _run_stream(py_cmd, timeout=300, cancel_event=cancel_event,
                                        fail_keywords=["403 Forbidden"])
                if rc2 != 0 or rc2 == -5 or "403" in (out2 or ""):
                    methods.append("pip-官方")
                    if on_progress: on_progress("pip 切换到官方源")
                    rc2, out2 = _run_stream(
                        [python, "-m", "pip", "install", "-i", PYPI_OFFICIAL, pkg],
                        timeout=300, cancel_event=cancel_event)
            else:
                py_cmd = [python, "-m", "pip", "uninstall", "-y", pkg]
                rc2, out2 = _run_stream(py_cmd, timeout=120, cancel_event=cancel_event)
            rc, last_out = rc2, out2 or ""

    lookup = _package_lookup_name(pkg)
    if action == "install":
        ok = rc == 0 and _pkg_in_list(lookup, _get_all_env_pkgs(conda_exe, env_path))
    else:
        ok = rc == 0 and not _pkg_in_list(lookup, _get_all_env_pkgs(conda_exe, env_path))

    if not ok:
        brief = _short_error(last_out or "")
        last_out = (last_out or "") + "\n\n[已尝试] %s\n均失败，原因: %s" % (" → ".join(methods), brief)
    return ok, last_out or ""

# --- 卸载 ---

def uninstall_python_package(pkg, target=None, on_progress=None):
    python = _python_exe_for_target(target)
    if on_progress: on_progress("pip uninstall")
    cmd = [python, "-m", "pip", "uninstall", "-y", pkg]
    rc, out = _run_stream(cmd, timeout=60)
    ok = rc == 0 and "Successfully uninstalled" in (out or "")
    if not ok:
        brief = _short_error(out or "")
        out = (out or "") + "\n\n卸载失败，原因: %s" % brief
    return ok, out or ""

def uninstall_node_package(pkg, target=None, on_progress=None):
    if on_progress: on_progress("npm uninstall")
    cmd = ["npm", "uninstall", "-g", pkg]
    rc, out = _run_stream(cmd, timeout=60)
    ok = rc == 0 and "ERR!" not in (out or "")
    if not ok:
        brief = _short_error(out or "")
        out = (out or "") + "\n\n卸载失败，原因: %s" % brief
    return ok, out or ""

def uninstall_conda_package(pkg, target=None, on_progress=None):
    return _conda_install_or_remove(pkg, target, "remove", None, on_progress)

# --- 删除环境 ---

def delete_conda_env(conda_exe, env_name_or_path):
    cmd = [conda_exe, "env", "remove", "-p", env_name_or_path, "-y"]
    rc, out = _run_stream(cmd, timeout=120)
    if rc != 0:
        cmd = [conda_exe, "env", "remove", "-n", env_name_or_path, "-y"]
        rc, out = _run_stream(cmd, timeout=120)
    return rc == 0, out or ""

def delete_python_venv(path):
    try:
        shutil.rmtree(path)
        return True, "已删除: %s" % path
    except Exception as e:
        return False, str(e)

def create_python_venv(python_exe, name, target_dir=None):
    """创建 Python 虚拟环境。python_exe 为要用的 Python，name 为环境名/路径。"""
    import venv
    if target_dir is None:
        target_dir = os.path.join(os.path.dirname(python_exe) or os.getcwd(), "..", name)
    target_dir = os.path.abspath(target_dir)
    if os.path.exists(target_dir):
        return False, "路径已存在: %s" % target_dir
    try:
        venv.create(target_dir, with_pip=True)
        return True, "Python 虚拟环境已创建: %s" % target_dir
    except Exception as e:
        return False, "创建失败: %s" % str(e)

def create_conda_env(conda_exe, name, python_version=""):
    """创建 Conda 虚拟环境，conda 全部 403 则回退 Python venv"""
    methods = []
    out = ""
    for channels, label in [(["-c", "conda-forge", "-c", "defaults"], "conda-forge+defaults"),
                             (["-c", "conda-forge"], "conda-forge")]:
        methods.append(label)
        cmd = [conda_exe, "create", "-y"] + channels + ["-n", name]
        if python_version:
            cmd.append("python=%s" % python_version)
        rc, out = _run_stream(cmd, timeout=120,
                              fail_keywords=["CondaHTTPError", "403 Forbidden"])
        if rc == 0 and "Executing transaction" in out:
            return True, out or ""

    # conda 全部 403 → 用 Python venv
    methods.append("python-venv(回退)")
    # 从 conda.exe (D:\Anaconda\Scripts\conda.exe) 反推 D:\Anaconda\python.exe
    python = None
    if os.path.isfile(conda_exe) and "Scripts" in conda_exe:
        root = os.path.dirname(os.path.dirname(conda_exe))
        candidate = os.path.join(root, "python.exe")
        if os.path.isfile(candidate):
            python = candidate
    if not python:
        python = shutil.which("python") or sys.executable
    target_dir = os.path.join(os.path.dirname(python), "envs", name)
    try:
        import venv
        if os.path.exists(target_dir):
            return False, "路径已存在: %s" % target_dir
        venv.create(target_dir, with_pip=True)
        return True, "[%s]\nconda 全部 403，已用 Python venv 创建: %s" % (
            " → ".join(methods), target_dir)
    except Exception as e:
        return False, "[%s]\n均失败: %s" % (" → ".join(methods), str(e))

# ═══════════════════════════════════════════════════
# Conda 虚拟环境扫描
# ═══════════════════════════════════════════════════

_CONDA_BASE_NAMES = {"base", "root"}

def _get_conda_envs(conda_exe, base_label=""):
    results = []
    seen_paths = set()
    # 1) conda env list
    rc, out = _run([conda_exe, "env", "list"], timeout=20)
    if rc == 0:
        envs = _parse_conda_env_list(out)
        for env_name, env_path in envs:
            seen_paths.add(os.path.realpath(env_path.replace("/", "\\")).lower())
            is_base = env_name.lower() in _CONDA_BASE_NAMES
            dl = os.path.splitdrive(env_path)[0] or "C:"
            label = "Conda env: %s (%s)" % (env_name, dl)
            pkgs = _get_conda_env_packages(conda_exe, env_path)
            installed = [p.lower() for p in pkgs]
            missing = _compute_missing(CONDA_COMMON, installed)
            results.append(_make_result(
                label, True, env_path, env_path,
                details={"conda根": base_label or os.path.dirname(os.path.dirname(conda_exe)),
                          "conda_exe": conda_exe},
                installed=installed, missing=missing,
                env_type="conda_env", deletable=not is_base,
            ))
    # 2) 扫描 conda 根目录下的 envs/ 目录（非 conda 管理的 venv）
    conda_root = os.path.dirname(os.path.dirname(conda_exe)) if "Scripts" in conda_exe else ""
    if conda_root:
        envs_dir = os.path.join(conda_root, "envs")
        if os.path.isdir(envs_dir):
            for entry in os.listdir(envs_dir):
                full = os.path.join(envs_dir, entry)
                if not os.path.isdir(full):
                    continue
                real = os.path.realpath(full).lower()
                if real in seen_paths:
                    continue
                seen_paths.add(real)
                # 检查是否为 Python 环境（有 python.exe 或 pyvenv.cfg）
                py = os.path.join(full, "python.exe")
                if not os.path.isfile(py):
                    py = os.path.join(full, "Scripts", "python.exe")
                if not os.path.isfile(py) and not os.path.isfile(os.path.join(full, "pyvenv.cfg")):
                    continue
                dl = os.path.splitdrive(full)[0] or "C:"
                label = "Conda env: %s (%s)" % (entry, dl)
                rc2, ver = _run([py, "--version"], timeout=10) if os.path.isfile(py) else (-1, "")
                v = ver.replace("Python ", "") if rc2 == 0 else "?"
                installed = _get_python_packages_for(py) if os.path.isfile(py) else []
                installed_lower = [p.lower() for p in installed]
                missing = _compute_missing(CONDA_COMMON, installed_lower)
                results.append(_make_result(
                    label, True, v, full,
                    details={"conda根": conda_root, "conda_exe": conda_exe},
                    installed=installed_lower, missing=missing,
                    env_type="conda_env", deletable=True,
                ))
    return results

def _parse_conda_env_list(output):
    envs = []
    for line in output.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"): continue
        parts = [p for p in line.split() if p != "*"]
        if len(parts) >= 2:
            name = parts[0]
            path = parts[-1]
            # Windows 盘符如 C:\ D:\ 或者路径中有 \ 或 /
            if len(path) >= 2 and path[1] == ":" or any(c in path for c in "\\/"):
                envs.append((name, path))
    return envs

def _get_conda_env_packages(conda_exe, env_path):
    rc, out = _run([conda_exe, "list", "-p", env_path], timeout=30)
    if rc != 0: return []
    pkgs = []
    for line in out.split("\n"):
        if line.startswith("#") or not line.strip(): continue
        parts = line.split()
        if parts: pkgs.append(parts[0])
    return pkgs

# ═══════════════════════════════════════════════════
# Python venv 扫描
# ═══════════════════════════════════════════════════

_VENV_PATTERNS = [
    r"%s\*\*\.venv", r"%s\*\*\venv", r"%s\*\*\*\.venv", r"%s\*\*\*\venv",
    r"%s\Users\*\.virtualenvs\*", r"%s\Users\*\Envs\*",
    r"%s\Users\*\.local\share\virtualenvs\*",
    r"%s\Users\*\AppData\Local\pypoetry\Cache\virtualenvs\*",
]

def _scan_python_venvs(drives):
    results = []
    scanned = set()
    for drive in drives:
        for pattern in _VENV_PATTERNS:
            for m in _glob.glob(pattern % drive):
                if not os.path.isdir(m): continue
                py = os.path.join(m, "Scripts", "python.exe")
                if not os.path.isfile(py):
                    py = os.path.join(m, "bin", "python")
                    if not os.path.isfile(py):
                        if not os.path.isfile(os.path.join(m, "pyvenv.cfg")): continue
                        py = os.path.join(m, "Scripts", "python.exe")
                        if not os.path.isfile(py): py = os.path.join(m, "bin", "python3")
                try: rp = os.path.realpath(py)
                except: rp = py
                if rp in scanned: continue
                scanned.add(rp)
                rc, ver = _run([py, "--version"], timeout=15)
                v = ver.replace("Python ", "") if rc == 0 and ver else "?"
                pkgs = _get_python_packages_for(py)
                dl = os.path.splitdrive(m)[0] or "C:"
                display = "Python venv: %s (%s)" % (os.path.basename(m), dl)
                results.append(_make_result(
                    display, True, v, m,
                    env_type="python_venv", deletable=True,
                    installed=pkgs[:50] if len(pkgs) > 50 else pkgs,
                ))
    return results

# ═══════════════════════════════════════════════════
# 检测函数
# ═══════════════════════════════════════════════════

def _python_label(d):
    dlow = d.lower()
    if "anaconda" in dlow: return "Anaconda"
    if "miniconda" in dlow: return "Miniconda"
    return d if dlow.startswith("python") else d

def check_python(drives=None):
    name = "Python"
    found_list = []
    if drives:
        scanned = set()
        for drive in drives:
            hits = _scan_drive_for_exe(drive, "python.exe", _PYTHON_PATTERNS,
                version_args=["--version"],
                version_transform=lambda v: v.replace("Python ", ""),
                get_label=_python_label)
            for exe_path, ver, label, dl in hits:
                try: rp = os.path.realpath(exe_path)
                except: rp = exe_path
                if rp in scanned: continue
                scanned.add(rp)
                installed = _get_python_packages_for(exe_path)
                missing = _compute_missing(PYTHON_COMMON, installed)
                found_list.append(_make_result(
                    _display_name(name, label, dl), True, ver, exe_path,
                    {"来源": "%s / %s" % (label, dl)}, installed, missing, env_type="python"))
        if found_list: return found_list
    rc, ver = _run(["python", "--version"])
    if rc == 0:
        path = shutil.which("python") or sys.executable
        installed = get_python_packages()
        missing = _compute_missing(PYTHON_COMMON, installed)
        found_list.append(_make_result(name, True, ver.replace("Python ", ""),
                                       path, {"pip": "via PATH"}, installed, missing,
                                       env_type="python"))
        return found_list
    return [_make_result(name, False)]

def check_java(drives=None):
    name = "Java JDK"
    found_list = []
    if drives:
        scanned = set()
        for drive in drives:
            hits = _scan_drive_for_exe(drive, "java.exe", _JAVA_PATTERNS,
                version_args=["-version"],
                version_transform=lambda v: v.split("\n")[0].replace('"', "") if v else v,
                get_label=_simple_label, timeout=10)
            for exe_path, ver, label, dl in hits:
                try: rp = os.path.realpath(exe_path)
                except: rp = exe_path
                if rp in scanned: continue
                scanned.add(rp)
                javac_exe = os.path.join(os.path.dirname(exe_path), "javac.exe")
                _, javac_ver = _run([javac_exe, "-version"])
                details = {"javac": javac_ver.replace("javac ", "") if javac_ver else "not found",
                           "JAVA_HOME": os.environ.get("JAVA_HOME", "not set")}
                found_list.append(_make_result(_display_name(name, label, dl), True, ver, exe_path, details))
        if found_list: return found_list
    rc, ver = _run(["java", "-version"])
    if rc == 0:
        lines = ver.split("\n") if ver else []
        v = lines[0].replace('"', "") if lines else ver
        _, javac_ver = _run(["javac", "-version"])
        details = {"javac": javac_ver.replace("javac ", "") if javac_ver else "not found",
                   "JAVA_HOME": os.environ.get("JAVA_HOME", "not set")}
        found_list.append(_make_result(name, True, v, shutil.which("java") or "", details))
        return found_list
    return [_make_result(name, False)]

def check_c_cpp(drives=None):
    name = "C/C++"
    details = {}
    found_list = []
    if drives:
        gcc_found, cl_found, cmake_found = [], [], []
        for drive in drives:
            for exe_path, ver, label, dl in _scan_drive_for_exe(drive, "gcc.exe", _CPP_PATTERNS,
                    version_args=["--version"], version_transform=lambda v: v.split("\n")[0] if v else v,
                    get_label=_simple_label):
                gcc_found.append((ver, label, dl))
            for exe_path, ver, label, dl in _scan_drive_for_exe(drive, "cl.exe", _CPP_PATTERNS,
                    version_args=[], get_label=_simple_label,
                    version_transform=lambda v: next((ln.strip() for ln in v.split("\n") if "Microsoft" in ln or "Version" in ln), v[:80])):
                cl_found.append((ver, label, dl))
            for exe_path, ver, label, dl in _scan_drive_for_exe(drive, "cmake.exe", _CPP_PATTERNS,
                    version_args=["--version"], version_transform=lambda v: v.split("\n")[0] if v else v,
                    get_label=_simple_label):
                cmake_found.append((ver, label, dl))
        if gcc_found:
            for ver, label, dl in gcc_found:
                found_list.append(_make_result(_display_name("C/C++ (GCC)", label, dl), True, ver, "", {"gcc": ver}))
        if cl_found:
            for ver, label, dl in cl_found:
                found_list.append(_make_result(_display_name("C/C++ (MSVC)", label, dl), True, ver, "", {"MSVC": ver}))
        if cmake_found:
            for ver, label, dl in cmake_found:
                found_list.append(_make_result(_display_name("CMake", label, dl), True, ver, "", {"cmake": ver}))
        if found_list: return found_list
    # PATH fallback
    found = False
    version_parts = []
    _, gcc = _run(["gcc", "--version"])
    if gcc: found = True; g_ver = gcc.split("\n")[0]; version_parts.append("gcc " + g_ver); details["gcc"] = g_ver
    else: details["gcc"] = "not found"
    _, gpp = _run(["g++", "--version"])
    if gpp: found = True; gp_ver = gpp.split("\n")[0]; version_parts.append("g++ " + gp_ver); details["g++"] = gp_ver
    else: details["g++"] = "not found"
    _, cl = _run(["cl"])
    if cl and "Microsoft" in cl: found = True; msvc_line = next((ln for ln in cl.split("\n") if "Microsoft" in ln), cl[:80]); version_parts.append(msvc_line.strip()); details["MSVC"] = msvc_line.strip()
    else: details["MSVC"] = "not found"
    _, cmake = _run(["cmake", "--version"])
    if cmake: found = True; cmv = cmake.split("\n")[0]; version_parts.append(cmv); details["cmake"] = cmv
    else: details["cmake"] = "not found"
    found_list.append(_make_result(name, found, "; ".join(version_parts),
        shutil.which("gcc") or shutil.which("cl") or "", details))
    return found_list

def check_nodejs(drives=None):
    name = "Node.js"
    found_list = []
    if drives:
        scanned = set()
        for drive in drives:
            hits = _scan_drive_for_exe(drive, "node.exe", _NODEJS_PATTERNS,
                version_args=["--version"], version_transform=lambda v: v, get_label=_simple_label)
            for exe_path, ver, label, dl in hits:
                try: rp = os.path.realpath(exe_path)
                except: rp = exe_path
                if rp in scanned: continue
                scanned.add(rp)
                npm_exe = os.path.join(os.path.dirname(exe_path), "npm.cmd")
                if not os.path.isfile(npm_exe): npm_exe = os.path.join(os.path.dirname(exe_path), "npm")
                _, npm_ver = _run([npm_exe, "--version"]) if os.path.isfile(npm_exe) else (-1, "")
                installed = get_node_packages()
                missing = _compute_missing(NODE_COMMON, installed)
                found_list.append(_make_result(_display_name(name, label, dl), True, ver, exe_path,
                    {"npm": npm_ver or "not found"}, installed, missing))
        if found_list: return found_list
    rc, ver = _run(["node", "--version"])
    if rc == 0:
        _, npm_ver = _run(["npm", "--version"])
        installed = get_node_packages()
        missing = _compute_missing(NODE_COMMON, installed)
        found_list.append(_make_result(name, True, ver, shutil.which("node") or "",
            {"npm": npm_ver or "not found"}, installed, missing))
        return found_list
    return [_make_result(name, False)]

def check_git(drives=None):
    name = "Git"
    found_list = []
    if drives:
        scanned = set()
        all_hits = []
        for drive in drives:
            all_hits.extend(_scan_drive_for_exe(drive, "git.exe", _GIT_PATTERNS,
                version_args=["--version"], version_transform=lambda v: v.replace("git version ", ""),
                get_label=lambda d: "Git"))
        all_hits = _dedup_by_install_root(all_hits, root_level=2)
        for exe_path, ver, label, dl in all_hits:
            try: rp = os.path.realpath(exe_path)
            except: rp = exe_path
            if rp in scanned: continue
            scanned.add(rp)
            found_list.append(_make_result(_display_name(name, label, dl), True, ver, exe_path))
        if found_list: return found_list
    rc, ver = _run(["git", "--version"])
    if rc == 0:
        found_list.append(_make_result(name, True, ver.replace("git version ", ""), shutil.which("git") or ""))
        return found_list
    return [_make_result(name, False)]

def check_go(drives=None):
    name = "Go"
    found_list = []
    if drives:
        scanned = set()
        for drive in drives:
            hits = _scan_drive_for_exe(drive, "go.exe", _GO_PATTERNS,
                version_args=["version"], version_transform=lambda v: v.replace("go version ", ""),
                get_label=_simple_label)
            for exe_path, ver, label, dl in hits:
                try: rp = os.path.realpath(exe_path)
                except: rp = exe_path
                if rp in scanned: continue
                scanned.add(rp)
                found_list.append(_make_result(_display_name(name, label, dl), True, ver, exe_path))
        if found_list: return found_list
    rc, ver = _run(["go", "version"])
    if rc == 0:
        found_list.append(_make_result(name, True, ver.replace("go version ", ""), shutil.which("go") or ""))
        return found_list
    return [_make_result(name, False)]

def check_dotnet(drives=None):
    name = ".NET"
    found_list = []
    if drives:
        scanned = set()
        for drive in drives:
            hits = _scan_drive_for_exe(drive, "dotnet.exe", _DOTNET_PATTERNS,
                version_args=["--version"], version_transform=lambda v: v, get_label=_simple_label)
            for exe_path, ver, label, dl in hits:
                try: rp = os.path.realpath(exe_path)
                except: rp = exe_path
                if rp in scanned: continue
                scanned.add(rp)
                _, sdks = _run([exe_path, "--list-sdks"])
                details = {"SDKs": sdks} if sdks else {}
                found_list.append(_make_result(_display_name(name, label, dl), True, ver, exe_path, details))
        if found_list: return found_list
    rc, ver = _run(["dotnet", "--version"])
    if rc == 0:
        _, sdks = _run(["dotnet", "--list-sdks"])
        found_list.append(_make_result(name, True, ver, shutil.which("dotnet") or "", {"SDKs": sdks} if sdks else {}))
        return found_list
    return [_make_result(name, False)]

def check_conda(drives=None):
    name = "Conda"
    found_list = []
    conda_exe = None
    if drives:
        scanned = set()
        for drive in drives:
            hits = _scan_drive_for_exe(drive, "conda.exe", _CONDA_PATTERNS,
                version_args=["--version"], version_transform=lambda v: v.replace("conda ", ""),
                get_label=_simple_label, timeout=15)
            for exe_path, ver, label, dl in hits:
                try: rp = os.path.realpath(exe_path)
                except: rp = exe_path
                if rp in scanned: continue
                scanned.add(rp)
                conda_exe = exe_path
                installed = _get_conda_packages_with(conda_exe)
                missing = _compute_missing(CONDA_COMMON, installed)
                parent = _make_result(_display_name(name, label, dl), True, ver, exe_path,
                    {}, installed, missing, env_type="conda")
                found_list.append(parent)
        if found_list and conda_exe:
            found_list[0]["children"] = _get_conda_envs(conda_exe)
            return found_list
    rc, ver = _run(["conda", "--version"])
    path = shutil.which("conda") or ""
    conda_exe = path if path.endswith(".exe") else (path + ".exe")
    if rc == 0 and ver:
        installed = _get_conda_packages_with(conda_exe)
        missing = _compute_missing(CONDA_COMMON, installed)
        parent = _make_result(name, True, ver.replace("conda ", ""), path,
            {}, installed, missing, env_type="conda")
        found_list.append(parent)
        if conda_exe and os.path.isfile(conda_exe):
            parent["children"] = _get_conda_envs(conda_exe)
        return found_list
    candidates = [
        os.path.expandvars(r"%USERPROFILE%\anaconda3"),
        os.path.expandvars(r"%USERPROFILE%\miniconda3"),
        r"C:\ProgramData\anaconda3", r"C:\ProgramData\miniconda3",
    ]
    for p in candidates:
        ce = os.path.join(p, "Scripts", "conda.exe")
        if os.path.exists(ce):
            rc2, ver2 = _run([ce, "--version"])
            if rc2 == 0 and ver2:
                parent = _make_result(name, True, ver2.replace("conda ", ""), ce, env_type="conda")
                parent["children"] = _get_conda_envs(ce)
                found_list.append(parent)
                return found_list
    return [_make_result(name, False)]

def check_docker(drives=None):
    name = "Docker"
    found_list = []
    if drives:
        scanned = set()
        for drive in drives:
            hits = _scan_drive_for_exe(drive, "docker.exe", _DOCKER_PATTERNS,
                version_args=["--version"],
                version_transform=lambda v: v.replace("Docker version ", "").split(",")[0],
                get_label=lambda d: "Docker", timeout=15)
            for exe_path, ver, label, dl in hits:
                try: rp = os.path.realpath(exe_path)
                except: rp = exe_path
                if rp in scanned: continue
                scanned.add(rp)
                daemon_ok, ps_out = _run([exe_path, "ps"], timeout=15)
                details = {"daemon_running": "是" if daemon_ok == 0 else "否"}
                if daemon_ok != 0 and ps_out: details["error"] = ps_out
                found_list.append(_make_result(_display_name(name, label, dl), True, ver, exe_path, details))
        if found_list: return found_list
    rc, ver = _run(["docker", "--version"], timeout=15)
    if rc == 0:
        v = ver.replace("Docker version ", "").split(",")[0] if ver else ""
        daemon_ok, ps_out = _run(["docker", "ps"], timeout=15)
        details = {"daemon_running": "是" if daemon_ok == 0 else "否"}
        if daemon_ok != 0: details["error"] = ps_out
        found_list.append(_make_result(name, True, v, shutil.which("docker") or "", details))
        return found_list
    return [_make_result(name, False)]

def check_custom(name, drives=None):
    label = name
    ver, exe_path = "", ""
    if drives:
        patterns = [
            r"%s\Program Files\%s\*" % ("%s", name.replace(".exe", "")),
            r"%s\Program Files (x86)\%s\*" % ("%s", name.replace(".exe", "")),
            r"%s\Program Files\%s.exe" % ("%s", name.replace(".exe", "")),
            r"%s\Program Files (x86)\%s.exe" % ("%s", name.replace(".exe", "")),
            r"%s\%s\*" % ("%s", name.replace(".exe", "")),
        ]
        exe_name = name if name.endswith(".exe") else name + ".exe"
        all_hits = []
        for drive in drives:
            all_hits.extend(_scan_drive_for_exe(drive, exe_name, patterns,
                version_args=["--version"], version_transform=lambda v: v,
                get_label=lambda d: label, timeout=10))
        if all_hits:
            exe_path, ver, _, dl = all_hits[0]
            return [_make_result("%s (自定义, %s)" % (name, dl), True, ver, exe_path)]
    exe_path = shutil.which(name) or ""
    if exe_path:
        rc, out = _run([exe_path, "--version"], timeout=10)
        if rc != 0: rc, out = _run([exe_path, "-version"], timeout=10)
        if rc != 0: rc, out = _run([exe_path, "version"], timeout=10)
        if rc == 0 and out: ver = out.split("\n")[0]
        return [_make_result(name + " (自定义)", True, ver, exe_path)]
    return [_make_result(name + " (自定义)", False)]

# ═══════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════

ALL_CHECKS = {
    "Python": check_python, "Java JDK": check_java, "C/C++": check_c_cpp,
    "Node.js": check_nodejs, "Git": check_git, "Go": check_go,
    ".NET": check_dotnet, "Conda": check_conda, "Docker": check_docker,
}
SCANNABLE = set(ALL_CHECKS.keys())

def run_checks(selected, drives=None, custom=None):
    results = []
    for key in selected:
        fn = ALL_CHECKS.get(key)
        if not fn:
            items = check_custom(key, drives=drives)
            results.extend(items if isinstance(items, list) else [items])
            continue
        items = fn(drives=drives)
        results.extend(items if isinstance(items, list) else [items])
    for name in (custom or []):
        if name in selected: continue
        items = check_custom(name, drives=drives)
        results.extend(items if isinstance(items, list) else [items])
    if drives and "Python" in selected:
        venvs = _scan_python_venvs(drives)
        if venvs:
            for r in results:
                if r["name"].startswith("Python") and r["env_type"] == "python":
                    r["children"] = venvs
                    break
    return results

if __name__ == "__main__":
    print("可用盘符:", get_available_drives())
    print("---")
    results = run_checks(list(ALL_CHECKS), drives=get_available_drives())
    for r in results:
        status = "OK" if r["found"] else "NO"
        print("[%s] %s: %s (%s)" % (status, r["name"], r.get("version", ""), r.get("path", "")))
        if r.get("installed_pkgs"): print("  pkgs: %d installed" % len(r["installed_pkgs"]))
        if r.get("missing_pkgs"): print("  missing: %s" % ", ".join(r["missing_pkgs"][:8]))
