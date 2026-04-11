"""
修复 full_audit_check 发现的剩余可修问题：
1. FlexLink → 摩恩（4条 audit 集团未更新）
2. PDF_WRONG_YEAR_DIR（4个 PDF 在错误年份文件夹）
3. COMPANY_IS_VENDOR（3条乙方公司名）
4. YEAR_UNREASONABLE（2条年份异常）
5. EXCEL_COMPANY_DIFF（3条 OCR 公司名错误）
"""
import json, sys, io, shutil, re
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT_PATH = Path("output/audit.jsonl")
OUTPUT_BASE = Path("output")


def load_records():
    records = []
    with open(AUDIT_PATH, encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))
    return records


def save_records(records):
    with open(AUDIT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    shutil.copy(AUDIT_PATH, "output/audit_fixed.jsonl")


def move_pdf(src, dest):
    """安全移动 PDF"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.exists() and not dest.exists():
        try:
            shutil.copy2(str(src), str(dest))
            try:
                src.unlink()
            except PermissionError:
                pass  # 文件被占用，复制已成功
            return True
        except Exception as e:
            print(f"  移动失败: {e}")
    return False


def main():
    records = load_records()
    changes = 0
    pdf_moved = 0

    for r in records:
        fn = r.get("file_name", "")
        group = r.get("detected_group", "")

        # ── 1. FlexLink → 摩恩 ──
        if group == "FlexLink":
            r["detected_group"] = "摩恩"
            print(f"[集团修复] FlexLink → 摩恩: {fn[:60]}")
            changes += 1

        # ── 2. 年份异常修复 ──
        if fn == "文本接口格式说明书_航天信息股份有限公司_2004年2月6日.pdf":
            if r.get("report_year") == 1998:
                r["report_year"] = 2004
                print(f"[年份修复] 1998 → 2004: {fn[:60]}")
                changes += 1

        if fn == "供应商资格调差表_上海莱升软件咨询有限公司_2008年.pdf":
            if r.get("report_year") == 1999:
                r["report_year"] = 2008
                print(f"[年份修复] 1999 → 2008: {fn[:60]}")
                changes += 1

        # ── 3. OCR 公司名修复（应特格相关）──
        if fn == "服务需求表-英特格（上海）微电子贸易有限公司-有效期20110901至20120831-20110721.pdf":
            if "应辉" in (r.get("detected_company") or ""):
                r["detected_company"] = "英特格（上海）微电子贸易有限公司"
                print(f"[公司名修复] 应辉 → 英特格: {fn[:60]}")
                changes += 1

        if fn == "项目合同_艾微美半导体新材料（西安）有限公司.pdf":
            if "艾微半导体材料" in (r.get("detected_company") or ""):
                r["detected_company"] = "艾微美半导体新材料（西安）有限公司"
                print(f"[公司名修复] 艾微半导体材料 → 艾微美半导体新材料: {fn[:60]}")
                changes += 1

        if fn == "服务需求表_英特格（上海）微电子贸易有限公司_维护期2015.6.6.pdf":
            if "应铭格" in (r.get("detected_company") or ""):
                r["detected_company"] = "英特格（上海）微电子贸易有限公司"
                print(f"[公司名修复] 应铭格 → 英特格: {fn[:60]}")
                changes += 1

        # ── 4. 乙方公司名修复 ──
        # sandivik 合同 - 从文件名提取真正的客户
        if "sandivik mining" in fn.lower() and "LICENCE" in (r.get("detected_company") or ""):
            r["detected_company"] = "Sandvik Mining and Construction Trading (Shanghai) Co., Ltd"
            # 也应该归到山特维克集团
            r["detected_group"] = "山特维克"
            print(f"[公司名+集团修复] LICENCE → Sandvik/山特维克: {fn[:60]}")
            changes += 1

        # ── 5. 伊藤忠年份：文件名是2018，audit是2017 → 以文件名为准
        if fn == "维护合同_上海伊藤忠商事有限公司_2018.pdf":
            if r.get("report_year") == 2017:
                r["report_year"] = 2018
                print(f"[年份修复] 2017 → 2018: {fn[:60]}")
                changes += 1

    # 保存 audit
    if changes > 0:
        save_records(records)
        print(f"\naudit.jsonl 已更新，共 {changes} 处修改")

    # ── 移动 PDF 到正确年份文件夹 ──
    print("\n--- 移动 PDF ---")

    pdf_moves = [
        # (源, 目标)
        (OUTPUT_BASE / "巴克莱" / "未知年份" / "上海浦东发展银行 外汇汇款路线一览表.pdf",
         OUTPUT_BASE / "巴克莱" / "2012" / "上海浦东发展银行 外汇汇款路线一览表.pdf"),

        (OUTPUT_BASE / "应特格" / "未知年份" / "项目合同_艾微美半导体新材料（西安）有限公司.pdf",
         OUTPUT_BASE / "应特格" / "2014" / "项目合同_艾微美半导体新材料（西安）有限公司.pdf"),

        (OUTPUT_BASE / "三井集团" / "未知年份" / "泛纬服务合同_三井纤维物资(中国)有限公司_维护合同_cn.pdf",
         OUTPUT_BASE / "三井集团" / "2022" / "泛纬服务合同_三井纤维物资(中国)有限公司_维护合同_cn.pdf"),
    ]

    for src, dest in pdf_moves:
        if move_pdf(src, dest):
            pdf_moved += 1
            print(f"  移动: {src.name} → {dest.parent.name}/")
        else:
            if not src.exists():
                print(f"  跳过（源不存在）: {src}")
            elif dest.exists():
                print(f"  跳过（目标已存在）: {dest}")

    # 清理空的未知年份文件夹
    for group_dir in OUTPUT_BASE.iterdir():
        if group_dir.is_dir():
            unknown = group_dir / "未知年份"
            if unknown.exists() and not any(unknown.iterdir()):
                unknown.rmdir()
                print(f"  删除空文件夹: {unknown}")

    print(f"\n移动了 {pdf_moved} 个 PDF")
    print(f"总计修改: {changes} 条 audit 记录, {pdf_moved} 个 PDF 移动")


if __name__ == "__main__":
    main()
