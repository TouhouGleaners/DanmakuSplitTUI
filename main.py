"""DanmakuSplitCLI — 弹幕 XML 分领区切割器 (TUI 版)"""

import xml.etree.ElementTree as ET
import math
import time
from pathlib import Path
from typing import Generator

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import (
    Header, Footer, Static, Button, Input,
    RadioSet, RadioButton, DataTable, Label, ProgressBar
)
from textual.binding import Binding
from textual import on, work
from textual.reactive import reactive


# ═══════════════════════════════════════════
#  业务层: 纯逻辑，零 UI
# ═══════════════════════════════════════════
class DanmakuSplitter:
    """解析 XML → 按时间排序 → 按策略切块 → 逐块写入"""

    def __init__(self, input_path: str, users: list[str] | None = None,
                 limit: int | None = None, p_num: str = "1"):
        self.input_file = Path(input_path).resolve()
        self.users = users or []
        self.limit = limit
        self.p_num = p_num
        self.danmakus: list[ET.Element] = []
        self.header_nodes: list[ET.Element] = []
        self.chunks: list[dict] = []
        self.output_dir = self.input_file.parent / f"Split_{self.input_file.stem}"

    # ── 阶段 1: 加载 + 排序 ──
    def load(self) -> int:
        if not self.input_file.exists():
            raise FileNotFoundError(f"找不到输入文件: {self.input_file}")

        tree = ET.parse(str(self.input_file))
        root = tree.getroot()
        self.header_nodes = [c for c in root if c.tag != 'd']

        scored: list[tuple[float, ET.Element]] = []
        for d in root.findall('d'):
            p_val = d.get('p')
            if p_val is not None:
                try:
                    scored.append((float(p_val.split(',')[0]), d))
                except (IndexError, ValueError):
                    continue

        scored.sort(key=lambda x: x[0])
        self.danmakus = [elem for _, elem in scored]
        return len(self.danmakus)

    # ── 阶段 2: 切块 ──
    def plan(self) -> list[dict]:
        total = len(self.danmakus)
        if self.limit:
            size = self.limit
        elif self.users:
            size = math.ceil(total / len(self.users))
        else:
            size = 1000

        self.chunks = []
        for i in range(math.ceil(total / size)):
            start = i * size
            end = min(start + size, total)
            if start >= total:
                break

            has_user = i < len(self.users)
            assignee = self.users[i] if has_user else f"Part_{i + 1}"
            clean = self._safe_name(assignee)

            if has_user:
                fname = f"P{self.p_num}_Part{i + 1}_[{clean}].xml"
            else:
                fname = f"P{self.p_num}_Part{i + 1}.xml"

            self.chunks.append({
                "index": i + 1,
                "assignee": assignee,
                "data": self.danmakus[start:end],
                "path": self.output_dir / fname,
            })
        return self.chunks

    # ── 阶段 3: 逐块写入 (生成器，供外部驱动进度条) ──
    def write_all(self) -> Generator[Path, None, None]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for chunk in self.chunks:
            root = ET.Element('i')
            for h in self.header_nodes:
                node = ET.Element(h.tag)
                node.text = h.text
                root.append(node)
            for d in chunk['data']:
                root.append(d)
            # 格式化 XML
            ET.indent(root, space="  ")
            ET.ElementTree(root).write(
                chunk['path'], encoding='utf-8', xml_declaration=True,
            )
            yield chunk['path']

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()


def _fmt_time(s: str) -> str:
    try:
        m, sec = divmod(int(float(s)), 60)
        return f"{m:02d}:{sec:02d}"
    except Exception:
        return "--:--"


# ═══════════════════════════════════════════
#  TUI 层: Textual 应用
# ═══════════════════════════════════════════
class DanmakuApp(App):
    """弹幕切割 TUI 应用"""

    TITLE = "DanmakuSplitCLI"
    SUB_TITLE = "弹幕 XML 领区切割工具"

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("p", "preview", "预览", show=True),
        Binding("ctrl+s", "split", "切割", show=True),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }

    #form-container {
        height: auto;
        max-height: 50%;
        padding: 1 2;
        overflow-y: auto;
    }

    .form-label {
        margin-top: 1;
        margin-bottom: 0;
        color: $text;
        text-style: bold;
    }

    .form-hint {
        color: $text-muted;
        text-style: italic;
        margin-bottom: 1;
    }

    Input {
        margin-bottom: 1;
    }

    #split-mode {
        height: auto;
        margin-bottom: 1;
    }

    #preview-table {
        height: 1fr;
        min-height: 10;
    }

    #status-bar {
        height: auto;
        padding: 0 2;
        background: $surface;
        color: $text-muted;
    }

    #button-container {
        height: 3;
        dock: bottom;
        align: center middle;
        padding: 0 2;
    }

    Button {
        margin: 0 1;
    }

    #progress-container {
        height: auto;
        padding: 0 2;
        display: none;
    }

    #progress-bar {
        margin: 1 0;
    }
    """

    # 响应式状态
    status_text = reactive("就绪")
    is_processing = reactive(False)

    def compose(self) -> ComposeResult:
        yield Header()

        with Container(id="form-container"):
            yield Label("📁 输入文件", classes="form-label")
            yield Input(
                placeholder="XML 文件路径...",
                id="input-path"
            )

            yield Label("👥 负责人列表", classes="form-label")
            yield Input(
                placeholder="用逗号或空格分隔多个负责人...",
                id="users"
            )
            yield Label("留空则按数量分割", classes="form-hint")

            yield Label("📊 分割设置", classes="form-label")
            with RadioSet(id="split-mode"):
                yield RadioButton("按人头平分", value=True, id="by-users")
                yield RadioButton("按数量限制", id="by-limit")

            yield Label("🔢 单片上限", classes="form-label")
            yield Input(
                placeholder="留空=自动计算",
                id="limit"
            )

            yield Label("🎬 分P号", classes="form-label")
            yield Input(
                value="1",
                id="pnum"
            )

        yield DataTable(id="preview-table")

        with Container(id="progress-container"):
            yield Label("处理中...", id="progress-label")
            yield ProgressBar(id="progress-bar")

        yield Static("就绪", id="status-bar")

        with Horizontal(id="button-container"):
            Button("预览 (P)", variant="primary", id="preview")
            Button("开始切割 (Ctrl+S)", variant="success", id="split")
            Button("退出 (Q)", variant="error", id="quit")

        yield Footer()

    def on_mount(self) -> None:
        """初始化表格列"""
        table = self.query_one("#preview-table", DataTable)
        table.add_columns("#", "负责人", "数量", "时间区间", "起始锚点")

    def watch_status_text(self, text: str) -> None:
        """状态栏更新"""
        self.query_one("#status-bar", Static).update(text)

    @on(Input.Submitted, "#input-path")
    def on_input_path_submitted(self) -> None:
        """文件路径回车后跳转到下一个输入框"""
        self.query_one("#users", Input).focus()

    @on(Input.Submitted, "#users")
    def on_users_submitted(self) -> None:
        """负责人列表回车后跳转到下一个输入框"""
        self.query_one("#limit", Input).focus()

    @on(Input.Submitted, "#limit")
    def on_limit_submitted(self) -> None:
        """限制回车后跳转到下一个输入框"""
        self.query_one("#pnum", Input).focus()

    def action_preview(self) -> None:
        """预览分割结果"""
        if self.is_processing:
            return
        self._do_preview()

    def action_split(self) -> None:
        """执行切割"""
        if self.is_processing:
            return
        self._do_split()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮点击处理"""
        if event.button.id == "preview":
            self._do_preview()
        elif event.button.id == "split":
            self._do_split()
        elif event.button.id == "quit":
            self.exit()

    def _get_splitter(self) -> DanmakuSplitter | None:
        """从表单获取参数并创建 splitter"""
        input_path = self.query_one("#input-path", Input).value.strip()
        # 去除 Windows 复制路径自带的引号
        if (input_path.startswith('"') and input_path.endswith('"')) or \
           (input_path.startswith("'") and input_path.endswith("'")):
            input_path = input_path[1:-1]
        if not input_path:
            self.status_text = "❌ 请输入 XML 文件路径"
            return None

        users_str = self.query_one("#users", Input).value.strip()
        users = [u.strip() for u in users_str.replace(',', ' ').split() if u.strip()]

        limit_str = self.query_one("#limit", Input).value.strip()
        limit = None
        if limit_str:
            try:
                limit = int(limit_str)
                if limit <= 0:
                    self.status_text = "❌ 单片上限必须大于 0"
                    return None
            except ValueError:
                self.status_text = "❌ 单片上限必须是整数"
                return None

        p_num = self.query_one("#pnum", Input).value.strip() or "1"

        # 检查分割模式
        by_users = self.query_one("#by-users", RadioButton).value
        if by_users and not users:
            self.status_text = "❌ 按人头平分模式需要输入负责人列表"
            return None

        return DanmakuSplitter(input_path, users, limit, p_num)

    def _do_preview(self) -> None:
        """预览分割结果"""
        splitter = self._get_splitter()
        if not splitter:
            return

        try:
            # 加载
            self.status_text = "⏳ 解析 XML 中..."
            count = splitter.load()

            # 计算分片
            chunks = splitter.plan()

            # 更新表格
            table = self.query_one("#preview-table", DataTable)
            table.clear()

            for chunk in chunks:
                t0 = _fmt_time(chunk['data'][0].get('p').split(',')[0])
                t1 = _fmt_time(chunk['data'][-1].get('p').split(',')[0])
                anchor = (chunk['data'][0].text or "").replace('\n', ' ')[:30]

                table.add_row(
                    str(chunk['index']),
                    chunk['assignee'],
                    f"{len(chunk['data']):,}",
                    f"{t0} → {t1}",
                    anchor
                )

            # 更新状态
            self.status_text = f"✓ 预览完成 | 弹幕 {count:,} 条 | 分片 {len(chunks)} 个"

        except FileNotFoundError as e:
            self.status_text = f"❌ {e}"
        except Exception as e:
            self.status_text = f"❌ 解析失败: {e}"

    @work(exclusive=True, thread=True)
    def _do_split(self) -> None:
        """执行切割（后台线程）"""
        splitter = self._get_splitter()
        if not splitter:
            return

        self.is_processing = True

        try:
            # 阶段 1: 加载
            self.app.call_from_thread(
                self._update_status, "⏳ 解析 XML 中..."
            )
            count = splitter.load()

            # 阶段 2: 计算分片
            self.app.call_from_thread(
                self._update_status, "⏳ 计算分片中..."
            )
            chunks = splitter.plan()

            # 更新预览表格
            self.app.call_from_thread(
                self._update_preview, chunks
            )

            # 阶段 3: 写入文件
            self.app.call_from_thread(
                self._show_progress, len(chunks)
            )

            t_start = time.time()
            for i, _ in enumerate(splitter.write_all()):
                self.app.call_from_thread(
                    self._update_progress, i + 1, len(chunks)
                )
                time.sleep(0.05)  # 动画效果

            elapsed = time.time() - t_start

            # 完成
            self.app.call_from_thread(
                self._hide_progress
            )
            self.app.call_from_thread(
                self._update_status,
                f"✓ 切割完成 | 弹幕 {count:,} 条 | 分片 {len(chunks)} 个 | 耗时 {elapsed:.1f}s | 输出: {splitter.output_dir}"
            )

        except FileNotFoundError as e:
            self.app.call_from_thread(
                self._update_status, f"❌ {e}"
            )
        except Exception as e:
            self.app.call_from_thread(
                self._update_status, f"❌ 切割失败: {e}"
            )
        finally:
            self.is_processing = False

    def _update_status(self, text: str) -> None:
        """更新状态栏（线程安全）"""
        self.status_text = text

    def _update_preview(self, chunks: list[dict]) -> None:
        """更新预览表格（线程安全）"""
        table = self.query_one("#preview-table", DataTable)
        table.clear()

        for chunk in chunks:
            t0 = _fmt_time(chunk['data'][0].get('p').split(',')[0])
            t1 = _fmt_time(chunk['data'][-1].get('p').split(',')[0])
            anchor = (chunk['data'][0].text or "").replace('\n', ' ')[:30]

            table.add_row(
                str(chunk['index']),
                chunk['assignee'],
                f"{len(chunk['data']):,}",
                f"{t0} → {t1}",
                anchor
            )

    def _show_progress(self, total: int) -> None:
        """显示进度条（线程安全）"""
        container = self.query_one("#progress-container")
        container.display = True

        progress = self.query_one("#progress-bar", ProgressBar)
        progress.total = total
        progress.progress = 0

        label = self.query_one("#progress-label", Label)
        label.update(f"写入文件中... (0/{total})")

    def _update_progress(self, current: int, total: int) -> None:
        """更新进度条（线程安全）"""
        progress = self.query_one("#progress-bar", ProgressBar)
        progress.progress = current

        label = self.query_one("#progress-label", Label)
        label.update(f"写入文件中... ({current}/{total})")

    def _hide_progress(self) -> None:
        """隐藏进度条（线程安全）"""
        container = self.query_one("#progress-container")
        container.display = False


# ═══════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════
def main():
    app = DanmakuApp()
    app.run()


if __name__ == "__main__":
    main()
