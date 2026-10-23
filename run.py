"""免安装入口：python run.py <topo> [--req 要求.yaml] [--out 文档.docx]

把 src 加进 import 路径，省去 pip 安装这一步。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from labgen.topo import _main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_main())
