"""弹幕 XML 解析与切割逻辑"""

import xml.etree.ElementTree as ET
import math
from pathlib import Path
from typing import Generator


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

    def load(self) -> int:
        """加载 XML 并按时间排序"""
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

    def plan(self) -> list[dict]:
        """计算分片方案"""
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

    def write_all(self) -> Generator[Path, None, None]:
        """逐块写入文件（生成器）"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for chunk in self.chunks:
            root = ET.Element('i')
            for h in self.header_nodes:
                node = ET.Element(h.tag)
                node.text = h.text
                root.append(node)
            for d in chunk['data']:
                root.append(d)
            ET.indent(root, space="  ")
            ET.ElementTree(root).write(
                chunk['path'], encoding='utf-8', xml_declaration=True,
            )
            yield chunk['path']

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()


def fmt_time(s: str) -> str:
    """格式化秒数为 mm:ss"""
    try:
        m, sec = divmod(int(float(s)), 60)
        return f"{m:02d}:{sec:02d}"
    except Exception:
        return "--:--"
