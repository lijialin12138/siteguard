r"""SQL 练习小工具：在终端里对着 siteguard.db 敲 SQL，回车看结果。

用法（在 siteguard 目录下执行）：
    .\.venv\Scripts\python.exe scripts\sql.py

进入后：
    - 直接输入 SQL，以分号 ; 结束并回车 → 执行
    - SQL 可以跨多行写，看到 ...> 提示就继续敲
    - 输入 exit（或 quit / \\q）退出

这个脚本只是「连接 + 执行 + 打印」，它不帮你写 SQL——
SQL 得你自己敲，敲错就报错，报错信息正好是学习材料。
"""

import sqlite3
import sys
from pathlib import Path

# 让脚本能 import 到项目里的 app 包（scripts/ 的上一级就是项目根）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DB_PATH  # noqa: E402


def _print_rows(cur: sqlite3.Cursor) -> None:
    if cur.description is None:
        print("执行成功（这类语句不返回结果集）")
        return
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(" | ".join(cols))
    print("-" * 60)
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))
    print(f"（{len(rows)} 行）")


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    print(f"已连接：{DB_PATH}")
    print("输入 SQL，以分号 ; 结束并回车执行；输入 exit 退出。\n")

    buffer = ""
    while True:
        try:
            line = input("sql> " if not buffer else "...> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not buffer and line.strip().lower() in ("exit", "quit", r"\q"):
            break

        buffer += " " + line
        if ";" not in buffer:
            continue

        sql, _, buffer = buffer.partition(";")
        sql = sql.strip()
        if not sql:
            continue

        try:
            _print_rows(conn.execute(sql))
        except Exception as exc:  # 报错原文就是最好的教材，原样打印
            print(f"SQL 错误：{type(exc).__name__}: {exc}")
        print()


if __name__ == "__main__":
    main()
