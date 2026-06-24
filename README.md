# Echecker - Windows 编程环境检测工具

一键检测 Windows 上安装的编程环境及包版本，支持全盘扫描、包安装卸载、虚拟环境管理。

## 快速开始

### 方式一：直接运行 exe（推荐）

👉 下载 [Echecker.exe](https://github.com/sweeet1/Echecker/releases/latest/download/Echecker.exe)，双击即可运行，无需安装任何依赖。

### 方式二：从源码运行

```bash
pip install -r requirements.txt
python main.py
```

### 方式三：自行打包

```bash
pip install pyinstaller
./build.bat
# exe 产物在 dist/ 目录
```

---

## 功能

### 环境检测（9 项内置）

| 环境 | 检测内容 |
|------|---------|
| Python | `python --version`、`pip --version`、全局包列表 |
| Java JDK | `java -version`、`javac -version`、JAVA_HOME |
| C/C++ | gcc、g++、MSVC cl.exe、cmake |
| Node.js | `node --version`、`npm --version`、全局包列表 |
| Git | `git --version` |
| Go | `go version` |
| .NET | `dotnet --version`、SDK 列表 |
| Conda | conda 版本、子环境、包列表 |
| Docker | `docker --version`、daemon 运行状态 |

### 扫描模式

- **仅 PATH**：取消"全盘扫描"即可，只检测当前 PATH 中的环境
- **全盘扫描**：勾选各盘符（C:、D: 等），搜索 Program Files、Anaconda、Miniconda 等常见安装位置

### 包管理

- **安装**：推荐市面上最常用的 Top 10 包（缺失的自动列出），选择安装时可自定义输入任何包名
- **卸载**：勾选已安装的包，批量卸载
- **镜像加速**：pip 使用清华镜像，npm 使用淘宝镜像，403 时自动回退官方源
- **进度显示**：安装/卸载过程中详情区实时显示每一步的状态

### 虚拟环境

- **检测**：自动发现 Conda 子环境和 Python venv
- **创建**：点击 Python 或 Conda 主环境的"创建虚拟环境"按钮，输入名称即可
- **删除**：点击子环境的"删除此环境"按钮
- **包隔离**：每个子环境独立检测包列表和推荐安装

### 自定义环境

- 在左侧"自定义检测"框中输入任意 exe 名（如 `wsl`、`curl`、`ffmpeg`）
- 添加后在检测项中出现蓝色的 checkbox，可单独勾选检测

### 其他

- **复制报告**：一键生成完整检测报告到剪贴板
- **下载指引**：未安装的环境提供官方下载页面链接
- **取消安装**：安装过程中可随时取消

---

## 技术栈

- Python 3 + tkinter（GUI）
- PyInstaller（打包成单文件 exe）
- 零外部运行时依赖（exe 自带 Python 解释器）

## License

MIT
