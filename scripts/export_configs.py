"""把生成的命令按设备拆成独立的 .txt，方便在 eNSP 里整段粘贴。

用法：
    python scripts/export_configs.py <topo> <requirements.yaml> <输出目录> [--encoding gbk]

输出：
    <输出目录>/<设备名>.txt      每台设备一份，纯命令，整段选中复制
    <输出目录>/README.txt        说明 + 设备清单 + 粘贴顺序

注意：默认写 utf-8 且**不带 BOM**。带 BOM 的文件粘到 eNSP 命令行时，
第一行会变成「\ufeffsystem-view」，命令报错、停在用户视图，后面全部失败。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from labgen.generators import build_configs  # noqa: E402
from labgen.pastestyle import to_safe_paste  # noqa: E402
from labgen.requirements import load_requirements  # noqa: E402
from labgen.topo import parse_topo  # noqa: E402


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把命令按设备拆成 txt")
    parser.add_argument("topo", help=".topo 文件路径")
    parser.add_argument("req", help="requirements.yaml")
    parser.add_argument("out_dir", help="输出目录")
    parser.add_argument(
        "--encoding",
        default="utf-8",
        choices=("utf-8", "gbk", "ascii"),
        help="写文件用的编码，默认 utf-8（无 BOM）；设备名/描述含中文且控制台吃 GBK 时用 gbk",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="不要粘贴安全样式（默认把顶层 quit 换成 return + system-view）",
    )
    parser.add_argument(
        "--chunk",
        type=int,
        default=40,
        help="每份 txt 最多多少行，超过就切成 设备-01.txt、设备-02.txt；0 表示不切",
    )
    return parser.parse_args(argv[1:])


def _split_blocks(commands: list[str]) -> list[list[str]]:
    """按 return 切块：每块从 system-view 到 return，单独粘也能跑。"""

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in commands:
        current.append(line)
        if line.strip() == "return":
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _chunked(commands: list[str], limit: int) -> list[list[str]]:
    if limit <= 0:
        return [commands]

    chunks: list[list[str]] = []
    current: list[str] = []
    for block in _split_blocks(commands):
        if current and len(current) + len(block) > limit:
            chunks.append(current)
            current = []
        current.extend(block)
    if current:
        chunks.append(current)
    return chunks


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    topo = parse_topo(args.topo)
    req = load_requirements(args.req)
    configs = build_configs(topo, req)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    chunks_written: list[str] = []

    for name in sorted(configs):
        lines = configs[name]
        if not lines:
            continue
        if not args.plain:
            lines = to_safe_paste(lines)

        chunks = _chunked(lines, args.chunk)
        if len(chunks) == 1:
            (out_dir / f"{name}.txt").write_text(
                "\r\n".join(chunks[0]) + "\r\n", encoding=args.encoding, newline=""
            )
            written.append(name)
            continue

        for index, chunk in enumerate(chunks, start=1):
            filename = f"{name}-{index:02d}.txt"
            (out_dir / filename).write_text(
                "\r\n".join(chunk) + "\r\n", encoding=args.encoding, newline=""
            )
            chunks_written.append(filename)

    skipped = [d.name for d in topo.devices if d.name not in configs]

    readme = [
        f"实验：{req.experiment}",
        f"拓扑：{Path(args.topo).name}",
        f"要求：{Path(args.req).name}",
        f"编码：{args.encoding}（无 BOM）",
        "",
        "用法：打开 eNSP 对应设备 → 进入命令行 → 选中 txt 全文 → 粘贴。",
        "每份 txt 以 system-view 开头、return 结尾，单独粘也能跑；",
        "顶层收尾用 return + system-view，不依赖 quit，粘错了也不会掉进用户视图。",
    ]
    if chunks_written:
        readme += [
            "",
            f"大设备被切成 {args.chunk} 行一份（eNSP 一次粘贴行数有上限，太长会中断）：",
            "按文件名顺序逐份粘贴，每份贴完再贴下一份。",
            *[f"  {n}" for n in chunks_written],
        ]
    readme += ["", f"有命令的设备（{len(written)} 台）：", *[f"  {n}.txt" for n in written]]
    if skipped:
        readme += ["", f"不需要配置的设备（{len(skipped)} 台）：" + "、".join(skipped)]
    readme += ["", "生成自 ensp-project / labgen，改动请改 requirements.yaml 后重跑，别直接改 txt。"]

    (out_dir / "README.txt").write_text(
        "\r\n".join(readme) + "\r\n", encoding=args.encoding, newline=""
    )

    print(f"输出目录：{out_dir}")
    for name in written:
        print(f"  {name}.txt  {len(configs[name])} 行")
    if skipped:
        print("未生成：" + "、".join(skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
