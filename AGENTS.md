# 协作说明（AGENTS.md）

> 面向任何在这个仓库里干活的 AI 助手或协作者。项目要做成开源工具，进来的改动按「陌生人 clone 后能用」来要求。

## 这是什么

eNSP 配置生成器：读 eNSP 的 `.topo` 和结构化 `requirements.yaml`，确定性地生成每台设备的 VRP 命令，输出 Word 文档与逐设备 txt。

## 硬约束

1. **生成必须确定性**：同一输入，两次输出逐字节相同。不引入随机、时间戳、隐式网络请求。AI 只允许出现在「要求原文 → YAML」这一步，且必须可选（`--ai-input`），失败不能影响主流程。
2. **不猜**：原文没给的地址、网关、VLAN 不编。推不出来就写 `—` 或 `?`，交给用户确认。
3. **通用优先**：不为一台设备的残留状态、某个实验的特例写补丁。个性化走命令行参数或 YAML 字段，默认值服务大多数场景。
4. **改动必须带测试**：`pytest` 全绿才算完成；新增能力配对应用例，修 bug 先写复现用例。
5. **文档同步**：README、`docs/API.md`、`CHANGELOG.md` 跟着改。CHANGELOG 用「新增 / 变更 / 修复」分节，写给用户看不写给作者看。
6. **错误信息可自解释**：带设备名、字段名、原文片段；不要让用户去猜哪个字段错了。

## 产出必须能直接粘进 eNSP

- 文件无 BOM、`\r\n` 只出现一次、长设备按行数分段（`--chunk`）。
- 顶层视图用 `return` + `system-view` 收尾，不依赖 `quit` 累积（`labgen.pastestyle`）。
- 命令字段只用 ASCII：中文放 `department`、`experiment.name` 这类只进文档的字段。
- ACL 在交换机上要 `expand: true` 克隆编号，同一个 ACL 不能挂多个 Vlanif。

## 技术栈与目录

- Python 3.10+，依赖只有 `pyyaml` + `python-docx`，不加重依赖。
- 入口 `run.py` → `src/labgen/`；测试 `tests/`；辅助脚本 `scripts/`；文档 `docs/`。
- 模块职责见 `docs/API.md`。

## 不要动

- `.venv/`、`output/`、`ai.yaml`（含密钥，已在 `.gitignore`）不提交。
- `samples/` 里的要求文件是对外示例，改它们等于改契约，先讨论。

## 提交约定

- Conventional Commits：`feat(scope): …` / `fix(scope): …` / `docs: …` / `test: …`。
- 一个提交只做一件事；文档和代码可以分开提。
