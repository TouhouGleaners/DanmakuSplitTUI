"""TUI 界面"""

import time
import xml.etree.ElementTree as ET
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import (
    Header, Footer, Static, Button, Input,
    RadioSet, RadioButton, DataTable, Label, ProgressBar
)
from textual.binding import Binding
from textual import on, work
from textual.reactive import reactive

from .splitter import DanmakuSplitter, fmt_time


class DanmakuSplitTUI(App):
    """弹幕切割 TUI 应用"""

    TITLE = "DanmakuSplitTUI"
    SUB_TITLE = "弹幕 XML 领区切割工具"
    CSS_PATH = Path(__file__).parent / "styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("p", "preview", "预览", show=True),
        Binding("ctrl+s", "split", "切割", show=True),
    ]

    status_text = reactive("就绪")
    is_processing = reactive(False)

    def compose(self) -> ComposeResult:
        yield Header()

        with Container(id="form-container"):
            yield Label("📁 输入文件", classes="form-label")
            yield Input(placeholder="XML 文件路径...", id="input-path")

            yield Label("👥 负责人列表", classes="form-label")
            yield Input(placeholder="用逗号或空格分隔多个负责人...", id="users")
            yield Label("留空则按数量分割", classes="form-hint")

            yield Label("📊 分割设置", classes="form-label")
            with RadioSet(id="split-mode"):
                yield RadioButton("按人头平分", value=True, id="by-users")
                yield RadioButton("按数量限制", id="by-limit")

            yield Label("🔢 单片上限", classes="form-label")
            yield Input(placeholder="留空=自动计算", id="limit")

            yield Label("🎬 分P号", classes="form-label")
            yield Input(value="1", id="pnum")

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
        table = self.query_one("#preview-table", DataTable)
        table.add_columns("#", "负责人", "数量", "时间区间", "起始锚点")

    def watch_status_text(self, text: str) -> None:
        self.query_one("#status-bar", Static).update(text)

    # ── 输入框回车跳转 ──

    @on(Input.Submitted, "#input-path")
    def on_input_path_submitted(self) -> None:
        self.query_one("#users", Input).focus()

    @on(Input.Submitted, "#users")
    def on_users_submitted(self) -> None:
        self.query_one("#limit", Input).focus()

    @on(Input.Submitted, "#limit")
    def on_limit_submitted(self) -> None:
        self.query_one("#pnum", Input).focus()

    # ── 快捷键 ──

    def action_preview(self) -> None:
        if not self.is_processing:
            self._do_preview()

    def action_split(self) -> None:
        if not self.is_processing:
            self._do_split()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "preview":
            self._do_preview()
        elif event.button.id == "split":
            self._do_split()
        elif event.button.id == "quit":
            self.exit()

    # ── 参数解析 ──

    def _get_splitter(self) -> DanmakuSplitter | None:
        input_path = self.query_one("#input-path", Input).value.strip()
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

        by_users = self.query_one("#by-users", RadioButton).value
        if by_users:
            if not users:
                self.status_text = "❌ 按人头平分模式需要输入负责人列表"
                return None
        else:
            if not limit:
                self.status_text = "❌ 按数量限制模式需要填写单片上限"
                return None

        return DanmakuSplitter(input_path, users, limit, p_num)

    # ── 预览 ──

    def _do_preview(self) -> None:
        splitter = self._get_splitter()
        if not splitter:
            return

        try:
            self.status_text = "⏳ 解析 XML 中..."
            count = splitter.load()
            chunks = splitter.plan()

            self._fill_preview_table(chunks)

            self.status_text = f"✓ 预览完成 | 弹幕 {count:,} 条 | 分片 {len(chunks)} 个"

        except FileNotFoundError as e:
            self.status_text = f"❌ {e}"
        except (ET.ParseError, ValueError) as e:
            self.status_text = f"❌ XML 解析失败: {e}"

    # ── 切割 ──

    @work(exclusive=True, thread=True)
    def _do_split(self) -> None:
        splitter = self._get_splitter()
        if not splitter:
            return

        self.is_processing = True
        try:
            self.app.call_from_thread(self._update_status, "⏳ 解析 XML 中...")
            count = splitter.load()

            self.app.call_from_thread(self._update_status, "⏳ 计算分片中...")
            chunks = splitter.plan()

            self.app.call_from_thread(self._update_preview, chunks)
            self.app.call_from_thread(self._show_progress, len(chunks))

            t_start = time.time()
            for i, _ in enumerate(splitter.write_all()):
                self.app.call_from_thread(self._update_progress, i + 1, len(chunks))
                time.sleep(0.05)

            elapsed = time.time() - t_start
            self.app.call_from_thread(self._hide_progress)
            self.app.call_from_thread(
                self._update_status,
                f"✓ 切割完成 | 弹幕 {count:,} 条 | 分片 {len(chunks)} 个 | 耗时 {elapsed:.1f}s | 输出: {splitter.output_dir}"
            )

        except FileNotFoundError as e:
            self.app.call_from_thread(self._update_status, f"❌ {e}")
        except (ET.ParseError, ValueError, OSError) as e:
            self.app.call_from_thread(self._update_status, f"❌ 切割失败: {e}")
        finally:
            self.is_processing = False

    # ── 线程安全的 UI 更新 ──

    def _update_status(self, text: str) -> None:
        self.status_text = text

    def _update_preview(self, chunks: list[dict]) -> None:
        self._fill_preview_table(chunks)

    def _fill_preview_table(self, chunks: list[dict]) -> None:
        """填充预览表格"""
        table = self.query_one("#preview-table", DataTable)
        table.clear()
        for chunk in chunks:
            t0 = fmt_time(chunk['data'][0].get('p').split(',')[0])
            t1 = fmt_time(chunk['data'][-1].get('p').split(',')[0])
            anchor = (chunk['data'][0].text or "").replace('\n', ' ')[:30]
            table.add_row(
                str(chunk['index']),
                chunk['assignee'],
                f"{len(chunk['data']):,}",
                f"{t0} → {t1}",
                anchor
            )

    def _show_progress(self, total: int) -> None:
        self.query_one("#progress-container").display = True
        progress = self.query_one("#progress-bar", ProgressBar)
        progress.total = total
        progress.progress = 0
        self.query_one("#progress-label", Label).update(f"写入文件中... (0/{total})")

    def _update_progress(self, current: int, total: int) -> None:
        self.query_one("#progress-bar", ProgressBar).progress = current
        self.query_one("#progress-label", Label).update(f"写入文件中... ({current}/{total})")

    def _hide_progress(self) -> None:
        self.query_one("#progress-container").display = False
