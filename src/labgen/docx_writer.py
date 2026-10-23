"""把生成结果写成 Word：按设备分节，命令为等宽块，可整段复制。"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from labgen.requirements import Requirements
from labgen.topo import Topology

__all__ = ["build_document", "write_docx"]

CODE_FONT = "Consolas"
CODE_SIZE = Pt(9)


def _set_code_font(run) -> None:
    run.font.name = CODE_FONT
    run.font.size = CODE_SIZE
    run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CODE_FONT)


def _shade(paragraph, fill: str = "F2F2F2") -> None:
    pr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pr.append(shd)


def _command_block(doc: Document, commands: list[str]) -> None:
    """每行一个零间距段落：复制到命令行时换行不会丢。"""

    for line in commands:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1.0
        paragraph.paragraph_format.left_indent = Pt(6)
        _shade(paragraph)
        run = paragraph.add_run(line)
        _set_code_font(run)


def _device_table(doc: Document, topo: Topology) -> None:
    table = doc.add_table(rows=1, cols=4)
    table.style = "Light Grid Accent 1"
    for cell, title in zip(table.rows[0].cells, ("设备", "型号", "类型", "可连接口数")):
        cell.text = title
    for device in topo.devices:
        row = table.add_row().cells
        row[0].text = device.name
        row[1].text = device.model
        row[2].text = {"router": "路由器", "switch": "交换机", "pc": "终端"}.get(
            device.device_type, device.device_type
        )
        row[3].text = str(len(device.ports))


def _link_table(doc: Document, topo: Topology) -> None:
    if not topo.links:
        doc.add_paragraph("没有连线。")
        return
    table = doc.add_table(rows=1, cols=5)
    table.style = "Light Grid Accent 1"
    for cell, title in zip(table.rows[0].cells, ("设备 A", "接口 A", "设备 B", "接口 B", "线缆")):
        cell.text = title
    for link in topo.links:
        row = table.add_row().cells
        row[0].text = link.src.device
        row[1].text = link.src.port or "未知"
        row[2].text = link.dst.device
        row[3].text = link.dst.port or "未知"
        row[4].text = link.cable


def build_document(
    topo: Topology, req: Requirements, configs: dict[str, list[str]]
) -> Document:
    """构建文档对象；不写盘，便于测试。"""

    doc = Document()

    title = req.experiment or Path(topo.source).stem
    heading = doc.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    summary = doc.add_paragraph(
        f"拓扑文件：{Path(topo.source).name}　设备 {len(topo.devices)} 台　"
        f"连线 {len(topo.links)} 条"
    )
    summary.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in summary.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    note = doc.add_paragraph()
    note_run = note.add_run(
        "使用方式：按设备标题逐节复制命令，粘贴到该设备的用户视图（<Huawei>）后回车即可。"
        "命令块以 system-view 开头、return 结尾；执行完记得 save。"
    )
    note_run.font.size = Pt(9)
    note_run.font.color.rgb = RGBColor(0x99, 0x33, 0x00)

    doc.add_heading("拓扑概览", level=1)
    doc.add_heading("设备", level=2)
    _device_table(doc, topo)

    doc.add_heading("连线", level=2)
    _link_table(doc, topo)

    if topo.warnings:
        doc.add_heading("解析告警", level=2)
        for warning in topo.warnings:
            doc.add_paragraph(warning, style="List Bullet")

    used: set[str] = set()
    for device in topo.devices:
        commands = configs.get(device.name)
        if not commands:
            continue
        used.add(device.name)
        doc.add_page_break()
        doc.add_heading(f"{device.name}　{device.model}", level=1)

        info = doc.add_paragraph(
            f"类型：{'路由器' if device.device_type == 'router' else '交换机' if device.device_type == 'switch' else '终端'}"
            f"　接口：{len(device.ports)} 个"
        )
        info.runs[0].font.size = Pt(9)

        doc.add_paragraph("把下面整段命令复制到该设备：")
        _command_block(doc, commands)

        tail = doc.add_paragraph("执行完成后保存配置：save")
        tail.runs[0].font.size = Pt(9)

    idle = [d for d in topo.devices if d.name not in used]
    if idle:
        doc.add_heading("未生成配置的设备", level=1)
        doc.add_paragraph(
            "以下设备在 requirements.yaml 中没有配置意图，因此没有命令："
            + "、".join(d.name for d in idle)
        )

    return doc


def write_docx(
    topo: Topology, req: Requirements, configs: dict[str, list[str]], path: str | Path
) -> Path:
    """构建并写盘，返回实际路径。"""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    build_document(topo, req, configs).save(path)
    return path
