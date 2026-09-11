# -*- coding: utf-8 -*-
import json
import re
import os
import subprocess
import datetime
from WindPy import w


# ------------------------- 工具函数 -------------------------

def format_date(dt):
    return dt.strftime("%Y-%m-%d")


def _safe_str(v, default=""):
    if v is None:
        return default
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "none", "nat"):
        return default
    return s


def _safe_float(v, default=0.0):
    try:
        if v is None:
            return default
        f = float(v)
        if f != f:
            return default
        return f
    except (TypeError, ValueError):
        return default


def _parse_date(s):
    """'YYYY-MM-DD ...' -> date，失败返回 None"""
    s = _safe_str(s)
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _week_range_2weeks_ago(today=None):
    """
    返回"今天往前推两周那一整周的工作日区间"（周一 ~ 周五）
    """
    today = today or datetime.date.today()
    target = today - datetime.timedelta(days=14)
    monday = target - datetime.timedelta(days=target.weekday())
    friday = monday + datetime.timedelta(days=4)
    return monday, friday


# ------------------------- 1. Wind 数据拉取 -------------------------

def get_launches(date_str):
    """新成立产品：指定日期"""
    print(f"🔄 正在拉取新成立产品 ({date_str})...")
    options = (
        f"startdate={date_str};enddate={date_str};"
        f"datetype=inceptiondate;isvalid=yes;deltranafter=no;"
        f"field=name,mergeissueshare,fundfounddate,investmenttype2,trustee"
    )
    data = w.wset("fundissuegeneralview", options)
    if data.ErrorCode != 0:
        print(f"⚠️  Wind 拉取失败，错误码: {data.ErrorCode}")
        return []
    if not data.Data or len(data.Data) < 5 or len(data.Data[0]) == 0:
        print("⚠️  成立产品返回数据为空")
        return []

    names       = data.Data[0]
    shares      = data.Data[1]
    found_dates = data.Data[2]
    inv_types   = data.Data[3]
    trustees    = data.Data[4]      # ✅ 托管人

    result = []
    for i in range(len(names)):
        result.append({
            "name":      _safe_str(names[i], "N/A"),
            "date":      _safe_str(found_dates[i], ""),
            "scale":     round(_safe_float(shares[i], 0.0), 2),
            "type":      _safe_str(inv_types[i], "未知"),
            "custodian": _safe_str(trustees[i], "-"),   # ✅ 前端字段仍叫 custodian
        })
    return result


def get_reports(date_str):
    """新产品上报：pending fund for approval，日期=前一日"""
    print(f"🔄 正在拉取新产品上报 ({date_str})...")
    options = (
        f"startdate={date_str};enddate={date_str};"
        f"fundstatus=pending fund for approval;"
        f"field=fundname,fundtype2,getfiledate"
    )
    data = w.wset("fundsonapproval", options)
    if data.ErrorCode != 0:
        print(f"⚠️  Wind 拉取失败，错误码: {data.ErrorCode}")
        return []
    if not data.Data or len(data.Data) < 3 or len(data.Data[0]) == 0:
        print("⚠️  上报产品返回数据为空")
        return []

    names, types, filedates = data.Data[0], data.Data[1], data.Data[2]
    result = []
    for i in range(len(names)):
        result.append({
            "name": _safe_str(names[i], "N/A"),
            "date": _safe_str(filedates[i], ""),
            "type": _safe_str(types[i], "未知"),
        })
    return result


def get_pending(start_date, end_date):
    """
    此前上报未受理
    - 日期：两周前那一整周工作日（周一~周五）
    - 上报日 = getfiledate
    - 筛选：acceptiondate 为空
    """
    print(f"🔄 正在拉取未受理基金 ({start_date} ~ {end_date})...")
    options = (
        f"startdate={start_date};enddate={end_date};"
        f"fundstatus=pending fund for approval;"
        f"field=fundname,fundtype2,getfiledate,acceptiondate"
    )
    data = w.wset("fundsonapproval", options)
    if data.ErrorCode != 0:
        print(f"⚠️  Wind 拉取失败，错误码: {data.ErrorCode}")
        return []
    if not data.Data or len(data.Data) < 4 or len(data.Data[0]) == 0:
        print("⚠️  未受理基金返回数据为空")
        return []

    names, types, filedates, acceptiondates = data.Data[0], data.Data[1], data.Data[2], data.Data[3]
    result = []
    for i in range(len(names)):
        file_date = _safe_str(filedates[i], "")
        accept    = _safe_str(acceptiondates[i], "")
        if accept == "":
            result.append({
                "name": _safe_str(names[i], "N/A"),
                "date": file_date if file_date else "-",
                "type": _safe_str(types[i], "未知"),
            })
    return result


def get_approvals(start_date, end_date):
    """
    最新审批产品
    - 日期：start_date ~ end_date（end_date 为前一日）
    - 筛选：approvaldate == end_date
    - 新增列 days = approvaldate - getfiledate
    """
    print(f"🔄 正在拉取新获批基金 ({start_date} ~ {end_date})...")
    options = (
        f"startdate={start_date};enddate={end_date};"
        f"fundstatus=approval of the fund to be issued;"
        f"field=fundname,fundtype2,getfiledate,approvaldate"
    )
    data = w.wset("fundsonapproval", options)
    if data.ErrorCode != 0:
        print(f"⚠️  Wind 拉取失败，错误码: {data.ErrorCode}")
        return []
    if not data.Data or len(data.Data) < 4 or len(data.Data[0]) == 0:
        print("⚠️  获批基金返回数据为空")
        return []

    names, types, filedates, approvaldates = data.Data[0], data.Data[1], data.Data[2], data.Data[3]
    result = []
    for i in range(len(names)):
        file_date = _safe_str(filedates[i], "")
        appr_date = _safe_str(approvaldates[i], "")
        if appr_date[:10] != end_date:
            continue
        days = 0
        d1 = _parse_date(file_date)
        d2 = _parse_date(appr_date)
        if d1 and d2:
            days = (d2 - d1).days
        result.append({
            "name":    _safe_str(names[i], "N/A"),
            "type":    _safe_str(types[i], "未知"),
            "receive": file_date if file_date else "-",
            "decide":  appr_date if appr_date else "-",
            "days":    days,
        })
    return result


# ------------------------- 2. 更新 HTML -------------------------

def update_html_file(html_path):
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    long_ago = datetime.date(2022, 1, 1)

    mon_2w, fri_2w = _week_range_2weeks_ago(today)

    launch_data   = get_launches(format_date(yesterday))
    report_data   = get_reports(format_date(yesterday))
    pending_data  = get_pending(format_date(mon_2w), format_date(fri_2w))
    approval_data = get_approvals(format_date(long_ago), format_date(yesterday))

    print(f"✅ 数据拉取完成: 成立{len(launch_data)}只, "
          f"上报{len(report_data)}只, 未受理{len(pending_data)}只, "
          f"获批{len(approval_data)}只")

    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    def replace_array(html, var_name, new_data):
        json_str = json.dumps(new_data, ensure_ascii=False, indent=4)
        pattern = rf'(const\s+{var_name}\s*=\s*)\[[\s\S]*?\];'
        replacement = rf'\g<1>{json_str};'
        new_html, cnt = re.subn(pattern, replacement, html, flags=re.DOTALL)
        if cnt == 0:
            print(f"⚠️  未在 HTML 中找到 const {var_name} 数组，跳过替换")
        return new_html

    content = replace_array(content, 'launchData',   launch_data)
    content = replace_array(content, 'reportData',   report_data)
    content = replace_array(content, 'pendingData',  pending_data)
    content = replace_array(content, 'approvalData', approval_data)

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"🎉 HTML 文件已更新: {html_path}")


# ------------------------- 3. 推送到 GitHub -------------------------

def git_push(file_path, repo_dir=None):
    """
    把更新后的文件推送到 GitHub Pages 仓库
    file_path: 要提交的文件（比如 "dashboard.html"）
    repo_dir : Git 仓库根目录。不传则用当前脚本所在目录
    """
    repo_dir = repo_dir or os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.abspath(file_path)

    if not os.path.exists(file_path):
        print(f"⚠️  文件不存在，跳过 push: {file_path}")
        return

    try:
        rel_path = os.path.relpath(file_path, repo_dir)
        subprocess.run(["git", "add", rel_path], check=True, cwd=repo_dir)

        status = subprocess.run(
            ["git", "status", "--porcelain", rel_path],
            check=True, capture_output=True, text=True, cwd=repo_dir
        )
        if status.stdout.strip() == "":
            print("ℹ️  文件无变化，跳过 commit / push")
            return

        msg = f"auto update {datetime.datetime.now():%Y-%m-%d %H:%M}"
        subprocess.run(["git", "commit", "-m", msg], check=True, cwd=repo_dir)
        subprocess.run(["git", "push"], check=True, cwd=repo_dir)

        print("✅ 已推送到 GitHub，Pages 将在 1-2 分钟内自动发布")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  git 操作失败: {e}")


# ------------------------- 4. 主程序 -------------------------

if __name__ == "__main__":
    w.start()
    print("✅ Wind 接口已启动")

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    mon_2w, fri_2w = _week_range_2weeks_ago(today)
    long_ago = datetime.date(2022, 1, 1)

    print(f"📅 今天: {today}")
    print(f"📅 前一日: {format_date(yesterday)}")
    print(f"📅 两周前那一周工作日: {format_date(mon_2w)} ~ {format_date(fri_2w)}")

    print("\n🧪 测试 get_launches ...")
    t1 = get_launches(format_date(yesterday))
    print(f"  -> {len(t1)} 条")
    if t1: print("  样例:", t1[0])

    print("\n🧪 测试 get_reports ...")
    t2 = get_reports(format_date(yesterday))
    print(f"  -> {len(t2)} 条")
    if t2: print("  样例:", t2[0])

    print("\n🧪 测试 get_pending ...")
    t3 = get_pending(format_date(mon_2w), format_date(fri_2w))
    print(f"  -> {len(t3)} 条")
    if t3: print("  样例:", t3[0])

    print("\n🧪 测试 get_approvals ...")
    t4 = get_approvals(format_date(long_ago), format_date(yesterday))
    print(f"  -> {len(t4)} 条")
    if t4: print("  样例:", t4[0])

    # --- 更新 HTML ---
    HTML_FILE = "dashboard.html"
    update_html_file(HTML_FILE)

    # --- 推送到 GitHub ---
    git_push(HTML_FILE)
    print("\n⏳ 完成后约 1-2 分钟，可在 GitHub Pages 链接查看最新数据")