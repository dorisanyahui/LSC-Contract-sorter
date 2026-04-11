"""
批量修复年份问题：
1. 未知年份文件夹中文件名含明确年份的记录
2. audit.jsonl 年份与文件名年份不一致的记录（273条）
3. 同时移动 PDF 到正确的年份文件夹

规则：文件名中的年份优先于 audit 年份（依据 CLAUDE.md 字段提取优先级）
"""
import json, sys, io, re, shutil
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT_PATH = Path("output/audit.jsonl")
OUTPUT_BASE = Path("output")

YEAR_RE = re.compile(r'(19|20)\d{2}')


def get_filename_year(fn: str) -> int | None:
    """从文件名提取最早的有效年份（优先匹配明确日期模式）"""
    # 优先：完整日期 2007年01月05日 / 2009.10.21 / 20110422 / 2021.12.16
    date_patterns = [
        r'(20\d{2})年\d{1,2}月',      # 2007年01月
        r'(20\d{2})\.\d{1,2}\.\d{1,2}', # 2021.12.16
        r'(20\d{2})\.\d{1,2}月',      # 2015.6月
        r'(20\d{2})_\d{1,2}_\d{1,2}', # 2015_06_11
        r'(20\d{2})年',               # 2008年
    ]
    for pat in date_patterns:
        m = re.search(pat, fn)
        if m:
            y = int(m.group(1))
            if 1995 <= y <= 2026:
                return y

    # 其次：任何 19xx/20xx 的第一个
    years = [int(m.group()) for m in YEAR_RE.finditer(fn)]
    valid = [y for y in years if 1995 <= y <= 2026]
    return valid[0] if valid else None


def move_pdf(src: Path, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists() or dest.exists():
        return False
    try:
        shutil.copy2(str(src), str(dest))
        try:
            src.unlink()
        except PermissionError:
            pass
        return True
    except Exception as e:
        print(f"  [error] {e}")
        return False


def main():
    records = []
    with open(AUDIT_PATH, encoding='utf-8') as f:
        for line in f:
            records.append(json.loads(line))

    changes = 0
    pdf_moves = 0
    move_plans = []

    for r in records:
        fn = r.get('file_name', '')
        cur_year = r.get('report_year')
        group = r.get('detected_group', '')

        fn_year = get_filename_year(fn)
        if fn_year is None:
            continue

        # 决定是否需要改：
        # - 当前年份为空 → 用文件名年份
        # - 当前年份不等于文件名年份 → 用文件名年份（文件名优先）
        need_update = False
        if cur_year is None or cur_year == '' or cur_year == 0:
            need_update = True
        elif cur_year != fn_year:
            need_update = True

        if not need_update:
            continue

        old_year = cur_year
        r['report_year'] = fn_year
        changes += 1
        if changes <= 20:
            print(f"[{group}] {fn[:60]}  {old_year} → {fn_year}")

        # 计划 PDF 移动
        if not group or group in ('其他',):
            continue

        group_dir = OUTPUT_BASE / group
        if not group_dir.exists():
            continue

        # 查找 PDF 实际位置
        found_paths = list(group_dir.rglob(fn))
        if not found_paths:
            continue
        src = found_paths[0]

        # 目标：group/年份/fn
        correct_dir = group_dir / str(fn_year)
        dest = correct_dir / fn
        if src.parent != correct_dir:
            move_plans.append((src, dest, group, fn))

    print(f"\n共更新 {changes} 条 audit 记录")

    # 保存 audit
    if changes > 0:
        with open(AUDIT_PATH, 'w', encoding='utf-8') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        shutil.copy(AUDIT_PATH, 'output/audit_fixed.jsonl')
        print(f"audit.jsonl 已保存")

    # 执行 PDF 移动
    print(f"\n--- 移动 PDF（计划 {len(move_plans)}）---")
    for src, dest, group, fn in move_plans:
        if move_pdf(src, dest):
            pdf_moves += 1
            if pdf_moves <= 15:
                print(f"  [{group}] {src.parent.name} → {dest.parent.name}/  {fn[:50]}")

    print(f"\n移动了 {pdf_moves} 个 PDF")

    # 清理空年份文件夹
    cleaned = 0
    for group_dir in OUTPUT_BASE.iterdir():
        if not group_dir.is_dir():
            continue
        for year_dir in group_dir.iterdir():
            if year_dir.is_dir() and not any(year_dir.iterdir()):
                year_dir.rmdir()
                cleaned += 1
    print(f"清理 {cleaned} 个空文件夹")


if __name__ == '__main__':
    main()
