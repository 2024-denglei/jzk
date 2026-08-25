"""从 Excel 导入捐精人到 PostgreSQL（联调/初始灌库）。

正式数据请使用《文本信息》模板；人造 xlsx 仅作联调（缺列置空）。
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db.database import init_db
from db.donor_import import import_excel_bytes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=config.DATA_FILE_PATH)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="导入前清空 donor.donors，再写入本文件全部有效行",
    )
    args = parser.parse_args()
    if not os.path.isfile(args.file):
        raise SystemExit(f"文件不存在: {args.file}")
    init_db()
    with open(args.file, "rb") as f:
        content = f.read()
    result = import_excel_bytes(
        content,
        os.path.basename(args.file),
        operator_id=None,
        replace=args.replace,
    )
    print(result)


if __name__ == "__main__":
    main()
