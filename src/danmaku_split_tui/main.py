"""DanmakuSplitTUI — 弹幕 XML 分领区切割器"""

from .tui import DanmakuSplitTUI


def main():
    app = DanmakuSplitTUI()
    app.run()


if __name__ == "__main__":
    main()
