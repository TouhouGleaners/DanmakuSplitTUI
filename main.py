import xml.etree.ElementTree as ET
import argparse
import math
import sys
from datetime import datetime
from pathlib import Path


class DanmakuSplitter:
    def __init__(self, input_path, users=None, limit=None, p_num: str = "1"):
        self.input_file = Path(input_path).resolve()
        self.users = users or []
        self.limit = limit
        self.p_num = p_num
        self.danmakus = []
        self.header_nodes = []
        self.chunks = []
        self.output_dir = self.input_file.parent / f"Split_{self.input_file.stem}"

    def load_and_sort(self) -> int:
        """解析 XML 并按时间轴升序"""
        if not self.input_file.exists():
            raise FileNotFoundError(f"找不到输入文件: {self.input_file}")
        
        tree = ET.parse(str(self.input_file))
        root = tree.getroot()

        self.header_nodes = [child for child in root if child.tag != 'd']
        
        # 预提取并转换
        scored_danmakus = []
        for d in root.findall('d'):
            p_val = d.get('p')
            if p_val is not None:
                try:
                    # 预先计算好时间轴数值
                    time_tick = float(p_val.split(',')[0])
                    scored_danmakus.append((time_tick, d))
                except (IndexError, ValueError):
                    continue
        
        # 基于预计算的时间值进行排序
        scored_danmakus.sort(key=lambda x: x[0])
        
        # 还原回纯 Element 列表
        self.danmakus = [item[1] for item in scored_danmakus]
        
        return len(self.danmakus)
    
    def _sanitize_name(self, name):
        """清理非法文件名字符"""
        return "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip()
    
    def split(self):
        """计算切块"""
        total = len(self.danmakus)

        # 优先级: Limit > Users > Default(1000)
        if self.limit:
            chunk_size = self.limit
        elif self.users:
            chunk_size = math.ceil(total / len(self.users))
        else:
            chunk_size = 1000

        num_chunks = math.ceil(total / chunk_size)

        for i in range(num_chunks):
            start = i * chunk_size
            end = min((i + 1) * chunk_size, total)
            if start >= total:
                break

            chunk_data = self.danmakus[start:end]
            
            # 判断是否有真人名可分
            has_real_user = i < len(self.users)
            assignee = self.users[i] if has_real_user else f"Part_{i+1}"

            # 生成文件名
            if has_real_user:
                # P1_Part1_[负责人].xml
                clean_name = self._sanitize_name(assignee)
                filename = f"P{self.p_num}_Part{i+1}_[{clean_name}].xml"
            else:
                # P1_Part1.xml
                filename = f"P{self.p_num}_Part{i+1}.xml"

            self.chunks.append({
                "index": i + 1,
                "assignee": assignee,
                "data": chunk_data,
                "path": self.output_dir / filename
            })

        return self.chunks
    
    def save(self):
        """保存切块"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        for chunk in self.chunks:
            new_root = ET.Element('i')

            # 还原 Header
            for node in self.header_nodes:
                header_node = ET.Element(node.tag)
                header_node.text = node.text
                new_root.append(header_node)

            # 添加弹幕
            for d in chunk['data']:
                new_root.append(d)

            tree = ET.ElementTree(new_root)
            tree.write(chunk['path'], encoding='utf-8', xml_declaration=True)
        
        return self.output_dir
    

class AuditReporter:
    @staticmethod
    def format_time(seconds: str):
        try:
            m, s = divmod(int(float(seconds)), 60)
            return f"{m:02d}:{s:02d}"
        except:
            return "00:00"

    @staticmethod
    def get_width(s):
        """计算字符串在终端的实际显示宽度(中文占2格)"""
        return sum(2 if ord(c) > 0x4e00 else 1 for c in str(s))

    @classmethod
    def pad(cls, s, width):
        """根据显示宽度填充空格"""
        return str(s) + " " * (width - cls.get_width(s))

    @classmethod
    def show(cls, chunks, output_path):
        # 定义列宽
        w_idx, w_user, w_num, w_time = 10, 18, 8, 15

        print("\n" + "="*85)
        print(f" DanmakuSplitCLI 任务分配快照 (视频分P: P{chunks[0]['path'].stem.split('_')[0][1:]})")
        print("-" * 85)
        
        # 打印表头
        header = (cls.pad("序号", w_idx) + 
                  cls.pad("负责人", w_user) + 
                  cls.pad("数量", w_num) + 
                  cls.pad("时间区间", w_time) + 
                  "起始锚点内容 (用于校验)")
        print(header)
        print("-" * 85)

        for c in chunks:
            t_start = cls.format_time(c['data'][0].get('p').split(',')[0])
            t_end = cls.format_time(c['data'][-1].get('p').split(',')[0])
            anchor = (c['data'][0].text or "[空]").replace('\n', ' ')[:30]
            
            line = (cls.pad(f"Part {c['index']}", w_idx) + 
                    cls.pad(c['assignee'], w_user) + 
                    cls.pad(len(c['data']), w_num) + 
                    cls.pad(f"{t_start}-{t_end}", w_time) + 
                    anchor)
            print(line)

        print("-" * 85)
        print(f"[*] 输出目录: {output_path}")
        print(f"[*] 如有需要，请截图保存此表。\n")


def main():
    parser = argparse.ArgumentParser(description="DanmakuSplitCLI - 基于领区制与时间轴排序的弹幕分割器")
    parser.add_argument("-i", "--input", required=True, help="输入的 XML 文件路径")
    parser.add_argument("-u", "--users", help="负责人列表 (空格或逗号分隔)")
    parser.add_argument("-l", "--limit", type=int, help="单个文件弹幕上限")
    parser.add_argument("-p", "--p", default="1", help="对应视频的分P号")

    if len(sys.argv) == 1:
        parser.print_help()
        return

    args = parser.parse_args()
    user_list = args.users.replace(',', ' ').split() if args.users else []

    try:
        splitter = DanmakuSplitter(args.input, user_list, args.limit, args.p)
        
        print(f"[*] 正在解析 XML: {splitter.input_file.name}")
        splitter.load_and_sort()
        
        chunks = splitter.split()
        final_dir = splitter.save()
        
        AuditReporter.show(chunks, final_dir)
        
    except Exception as e:
        print(f"[!] 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()