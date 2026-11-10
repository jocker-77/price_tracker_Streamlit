"""
商品价格追踪器 - 主界面
支持京东价格实时监控，淘宝/拼多多链接聚合，降价邮件提醒
"""

import streamlit as st
import requests
import pandas as pd
import sqlite3
import re
from datetime import datetime
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
import time
import plotly.graph_objects as go

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="商品价格追踪器",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# 路径与常量
# ============================================================
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")
DB_PATH   = os.path.join(DATA_DIR, "tracker.db")
os.makedirs(DATA_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.jd.com/",
}

# ============================================================
# 自定义样式
# ============================================================
st.markdown("""
<style>
/* 顶部标题区 */
.block-container { padding-top: 1.5rem; }
/* 价格颜色 */
.price-low  { color: #e74c3c; font-weight: bold; font-size: 1.1em; }
.price-ok   { color: #2c3e50; font-size: 1.1em; }
.price-hit  { color: #27ae60; font-weight: bold; font-size: 1.1em; }
/* 商品卡片分隔 */
.product-row { border-bottom: 1px solid #f0f0f0; padding: 8px 0; }
/* Tab 间距 */
.stTabs [data-baseweb="tab-list"] { gap: 24px; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 数据库 ——————————————————————————————————————————————————————
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            jd_url        TEXT,
            jd_sku        TEXT,
            store_type    TEXT    DEFAULT '自营',
            taobao_url    TEXT,
            pdd_url       TEXT,
            target_price  REAL,
            notes         TEXT,
            current_price REAL,
            last_checked  TEXT,
            added_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
            is_active     INTEGER DEFAULT 1
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            platform   TEXT DEFAULT 'JD',
            price      REAL,
            checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()


def _conn():
    return sqlite3.connect(DB_PATH)


def db_run(sql, params=()):
    conn = _conn()
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()
    lid = c.lastrowid
    conn.close()
    return lid


def db_rows(sql, params=()):
    conn = _conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def db_df(sql, params=()):
    conn = _conn()
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df


def get_setting(key, default=""):
    rows = db_rows("SELECT value FROM settings WHERE key=?", (key,))
    return rows[0]["value"] if rows else default


def save_setting(key, value):
    db_run("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


# ============================================================
# 京东数据获取 ————————————————————————————————————————————————
# ============================================================
def extract_sku(url: str) -> str | None:
    """从京东链接中解析 SKU ID"""
    m = re.search(r"item\.jd\.com[/\\](\d+)", url)
    return m.group(1) if m else None


def fetch_jd_price(sku_id: str) -> float | None:
    """调用京东价格接口获取当前价格（免登录公开接口）"""
    api = f"https://p.3.cn/prices/mgets?skuIds=J_{sku_id}&type=1&area=1_72_2799_0"
    try:
        r = requests.get(api, headers=HEADERS, timeout=10)
        data = r.json()
        if data:
            p = data[0].get("p", "")
            return float(p) if p else None
    except Exception:
        pass
    return None


def fetch_jd_name(sku_id: str) -> str:
    """从商品页面标题中提取商品名称"""
    url = f"https://item.jd.com/{sku_id}.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = "utf-8"
        m = re.search(r"<title>(.*?)</title>", r.text, re.I)
        if m:
            t = m.group(1)
            t = re.sub(r"【京东】|【JD\.COM】|_?-?京东$|商品详情", "", t).strip()
            return t[:60]
    except Exception:
        pass
    return f"京东商品 {sku_id}"


# ============================================================
# 核心操作 ————————————————————————————————————————————————————
# ============================================================
def add_product(name, jd_url, store_type, taobao_url, pdd_url, target_price, notes):
    sku = extract_sku(jd_url) if jd_url else None
    price = fetch_jd_price(sku) if sku else None
    now = datetime.now().isoformat(timespec="seconds")
    pid = db_run("""
        INSERT INTO products
            (name, jd_url, jd_sku, store_type, taobao_url, pdd_url,
             target_price, notes, current_price, last_checked, added_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (name, jd_url, sku, store_type, taobao_url, pdd_url,
          target_price, notes, price, now, now))
    if price:
        db_run("INSERT INTO price_history (product_id, price) VALUES (?,?)", (pid, price))
    return pid, price


def refresh_all_prices() -> tuple[int, list]:
    """刷新所有商品价格，返回更新数量和需要提醒的商品"""
    rows = db_rows("""
        SELECT id, name, jd_sku, current_price, target_price
        FROM products WHERE is_active=1 AND jd_sku IS NOT NULL
    """)
    alerts, updated = [], 0
    for row in rows:
        pid, name, sku, old_price, target = (
            row["id"], row["name"], row["jd_sku"],
            row["current_price"], row["target_price"]
        )
        new_price = fetch_jd_price(sku)
        if new_price is None:
            continue
        now = datetime.now().isoformat(timespec="seconds")
        db_run("UPDATE products SET current_price=?, last_checked=? WHERE id=?",
               (new_price, now, pid))
        db_run("INSERT INTO price_history (product_id, price) VALUES (?,?)", (pid, new_price))
        updated += 1

        # 目标价提醒
        if target and new_price <= target:
            alerts.append({"name": name, "price": new_price, "target": target, "type": "target"})
        # 降幅 ≥5% 提醒
        elif old_price and new_price < old_price * 0.95:
            drop_pct = (old_price - new_price) / old_price * 100
            alerts.append({"name": name, "price": new_price, "old_price": old_price,
                           "drop_pct": drop_pct, "type": "drop"})

        time.sleep(0.3)   # 适当延迟，避免请求过快
    return updated, alerts


def get_products_df() -> pd.DataFrame:
    return db_df("""
        SELECT id, name, store_type, current_price, target_price,
               last_checked, jd_url, taobao_url, pdd_url, notes
        FROM products WHERE is_active=1 ORDER BY added_at DESC
    """)


def get_history_df(product_id: int) -> pd.DataFrame:
    df = db_df("""
        SELECT price, checked_at FROM price_history
        WHERE product_id=? ORDER BY checked_at ASC
    """, params=(product_id,))
    if not df.empty:
        df["checked_at"] = pd.to_datetime(df["checked_at"])
    return df


def delete_product(pid: int):
    db_run("UPDATE products SET is_active=0 WHERE id=?", (pid,))


# ============================================================
# 邮件发送 ————————————————————————————————————————————————————
# ============================================================
def build_email_html(alerts: list) -> str:
    rows = ""
    for a in alerts:
        if a["type"] == "target":
            rows += (
                f"<tr><td>{a['name']}</td>"
                f"<td style='color:#27ae60'>达到目标价</td>"
                f"<td style='color:#e74c3c;font-weight:bold'>¥{a['price']:.2f}</td>"
                f"<td>目标 ¥{a['target']:.2f}</td></tr>"
            )
        else:
            rows += (
                f"<tr><td>{a['name']}</td>"
                f"<td style='color:#e74c3c'>降价 {a['drop_pct']:.1f}%</td>"
                f"<td style='color:#e74c3c;font-weight:bold'>¥{a['price']:.2f}</td>"
                f"<td>原价 ¥{a['old_price']:.2f}</td></tr>"
            )
    return f"""
    <html><body style="font-family:sans-serif;max-width:600px;margin:auto">
    <h2>🔔 商品价格提醒</h2>
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
      <tr style="background:#f5f5f5">
        <th>商品</th><th>状态</th><th>当前价格</th><th>参考</th>
      </tr>
      {rows}
    </table>
    <p style="color:#999;font-size:12px;margin-top:20px">来自 商品价格追踪器</p>
    </body></html>
    """


def send_email(alerts: list) -> bool:
    cfg = {k: get_setting(k) for k in
           ("smtp_host", "smtp_port", "email_from", "email_pass", "email_to")}
    if not cfg["email_from"] or not cfg["email_to"]:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔔 价格提醒：{len(alerts)} 个商品值得关注"
    msg["From"]    = cfg["email_from"]
    msg["To"]      = cfg["email_to"]
    msg.attach(MIMEText(build_email_html(alerts), "html", "utf-8"))

    try:
        port = int(cfg["smtp_port"] or 465)
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["smtp_host"], port, context=ctx) as s:
                s.login(cfg["email_from"], cfg["email_pass"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["smtp_host"], port) as s:
                s.starttls()
                s.login(cfg["email_from"], cfg["email_pass"])
                s.send_message(msg)
        return True
    except Exception as e:
        st.error(f"邮件发送失败：{e}")
        return False


# ============================================================
# Excel 导出 ——————————————————————————————————————————————————
# ============================================================
def to_excel(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    df_out = df.copy()
    df_out.columns = ["ID", "商品名称", "店铺类型", "当前价格(¥)", "目标价格(¥)",
                      "最后检查时间", "京东链接", "淘宝链接", "拼多多链接", "备注"]
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df_out.to_excel(w, index=False, sheet_name="价格追踪")
        ws = w.sheets["价格追踪"]
        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=0)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)
    return buf.getvalue()


# ============================================================
# 主界面 ——————————————————————————————————————————————————————
# ============================================================
def sidebar_add_product():
    """侧边栏：添加商品"""
    st.sidebar.header("➕ 添加商品")

    jd_url = st.sidebar.text_input(
        "京东商品链接 *",
        key="sidebar_url",
        placeholder="https://item.jd.com/XXXXXXXX.html"
    )

    if st.sidebar.button("🔍 自动获取商品信息", use_container_width=True):
        if not jd_url:
            st.sidebar.error("请先填写京东商品链接")
        else:
            sku = extract_sku(jd_url)
            if not sku:
                st.sidebar.error("无法解析链接，请粘贴完整的京东商品页面链接")
            else:
                with st.sidebar.status("正在获取商品信息..."):
                    name  = fetch_jd_name(sku)
                    price = fetch_jd_price(sku)
                st.session_state["_fetched"] = {
                    "url": jd_url, "sku": sku, "name": name, "price": price
                }

    if st.session_state.get("_fetched"):
        info = st.session_state["_fetched"]
        if info.get("price"):
            st.sidebar.success(f"💰 当前价格：**¥{info['price']:.2f}**")
        else:
            st.sidebar.warning("未能获取价格，可能是京东临时限制，稍后再试")

        st.sidebar.divider()
        name       = st.sidebar.text_input("商品名称 *", value=info.get("name", ""), key="add_name")
        store_type = st.sidebar.selectbox("店铺类型", ["自营", "官方旗舰店", "品牌旗舰店", "其他"], key="add_store")
        target     = st.sidebar.number_input(
            "目标价（降至此价格提醒，不填则只监控5%以上降幅）",
            min_value=0.0, value=0.0, step=1.0, key="add_target"
        )

        with st.sidebar.expander("其他平台链接（选填）"):
            taobao = st.text_input("淘宝/天猫链接", key="add_taobao")
            pdd    = st.text_input("拼多多链接",   key="add_pdd")

        notes = st.sidebar.text_input("备注", key="add_notes", placeholder="如：等618大促")

        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.button("✅ 添加", type="primary", use_container_width=True, key="btn_add"):
                if not name:
                    st.sidebar.error("请填写商品名称")
                else:
                    pid, price = add_product(
                        name, info["url"], store_type,
                        st.session_state.get("add_taobao", ""),
                        st.session_state.get("add_pdd", ""),
                        target if target > 0 else None,
                        st.session_state.get("add_notes", "")
                    )
                    st.session_state.pop("_fetched", None)
                    st.sidebar.success("✅ 已添加！")
                    time.sleep(0.8)
                    st.rerun()
        with col2:
            if st.button("取消", use_container_width=True, key="btn_cancel"):
                st.session_state.pop("_fetched", None)
                st.rerun()


def tab_watchlist(df: pd.DataFrame):
    """追踪列表 Tab"""
    if df.empty:
        st.info("🔍 还没有追踪的商品，请在左侧粘贴京东链接开始添加")
        return

    for _, row in df.iterrows():
        with st.container():
            c1, c2, c3, c4, c5 = st.columns([5, 2, 2, 3, 1])

            with c1:
                st.markdown(f"**{row['name']}**")
                badge = row['store_type'] or '—'
                note  = f"　{row['notes']}" if row['notes'] else ""
                st.caption(f"🏪 {badge}{note}")

            with c2:
                price  = row["current_price"]
                target = row["target_price"]
                if price is None or pd.isna(price):
                    st.markdown("*价格待获取*")
                elif target and not pd.isna(target) and price <= target:
                    st.markdown(f"<span class='price-hit'>¥{price:.2f} ✅</span>",
                                unsafe_allow_html=True)
                else:
                    st.markdown(f"<span class='price-ok'>¥{price:.2f}</span>",
                                unsafe_allow_html=True)

            with c3:
                if target and not pd.isna(target) and target > 0:
                    st.caption(f"目标价: ¥{target:.2f}")
                else:
                    st.caption("未设目标价")

            with c4:
                links = []
                if row["jd_url"]:
                    links.append(f"[京东 🔗]({row['jd_url']})")
                if row["taobao_url"]:
                    links.append(f"[淘宝 🔗]({row['taobao_url']})")
                if row["pdd_url"]:
                    links.append(f"[拼多多 🔗]({row['pdd_url']})")
                st.markdown("　".join(links) if links else "—")

            with c5:
                if st.button("🗑️", key=f"del_{row['id']}", help="从列表移除"):
                    delete_product(int(row["id"]))
                    st.rerun()

        st.markdown('<hr style="margin:4px 0;border-color:#f0f0f0">', unsafe_allow_html=True)

    # 底部操作栏
    st.markdown("")
    col_l, col_r = st.columns([2, 8])
    with col_l:
        xlsx = to_excel(df)
        st.download_button(
            "📥 导出 Excel",
            data=xlsx,
            file_name=f"价格追踪_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def tab_history(df: pd.DataFrame):
    """价格走势 Tab"""
    if df.empty:
        st.info("还没有追踪的商品")
        return

    names = df["name"].tolist()
    ids   = df["id"].tolist()
    sel   = st.selectbox("选择商品", names, key="hist_sel")
    sel_id = ids[names.index(sel)]

    hist = get_history_df(sel_id)
    if hist.empty or len(hist) < 2:
        st.info("价格历史记录不足（至少需要 2 次采集），请多点几次「刷新价格」后再来查看")
        return

    target = df.loc[df["id"] == sel_id, "target_price"].values[0]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist["checked_at"], y=hist["price"],
        mode="lines+markers",
        name="京东价格",
        line=dict(color="#e74c3c", width=2),
        marker=dict(size=5),
        hovertemplate="日期: %{x|%Y-%m-%d %H:%M}<br>价格: ¥%{y:.2f}<extra></extra>"
    ))
    if target and not pd.isna(target) and target > 0:
        fig.add_hline(y=target, line_dash="dash", line_color="#27ae60",
                      annotation_text=f"目标价 ¥{target:.2f}",
                      annotation_position="bottom right")
    fig.update_layout(
        title=dict(text=f"📈 {sel[:40]} 价格走势", font=dict(size=15)),
        xaxis_title="时间", yaxis_title="价格 (¥)",
        hovermode="x unified", height=380,
        margin=dict(l=20, r=20, t=50, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)

    # 统计摘要
    low, high, cur = hist["price"].min(), hist["price"].max(), hist["price"].iloc[-1]
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("历史最低价", f"¥{low:.2f}")
    mc2.metric("历史最高价", f"¥{high:.2f}")
    mc3.metric("当前价格",   f"¥{cur:.2f}")
    delta = cur - low
    mc4.metric("距最低价还差", f"¥{delta:.2f}" if delta > 0 else "🎉 当前即最低价",
               delta=f"-¥{abs(delta):.2f}" if delta > 0 else None,
               delta_color="inverse")


def tab_settings():
    """设置 Tab"""
    st.subheader("📧 邮件提醒设置")
    st.markdown("配置后，当商品达到目标价或降幅 ≥5% 时，系统自动发送邮件提醒。")
    st.markdown("""
    > **QQ 邮箱用户注意**：请使用「授权码」而非登录密码。
    > 进入 QQ 邮箱 → 设置 → 账户 → 开启 IMAP/SMTP 服务 → 生成授权码。
    """)

    provider = st.selectbox("邮箱类型", ["QQ邮箱 (推荐)", "163邮箱", "Gmail", "企业邮箱/自定义"])
    presets = {
        "QQ邮箱 (推荐)": ("smtp.qq.com",  "465"),
        "163邮箱":       ("smtp.163.com", "465"),
        "Gmail":         ("smtp.gmail.com", "587"),
        "企业邮箱/自定义": ("", "465"),
    }
    default_host, default_port = presets[provider]

    with st.form("email_form"):
        c1, c2 = st.columns(2)
        smtp_host = c1.text_input("SMTP 服务器", value=get_setting("smtp_host", default_host))
        smtp_port = c2.text_input("端口",        value=get_setting("smtp_port", default_port))
        email_from = st.text_input("发件邮箱",   value=get_setting("email_from"))
        email_pass = st.text_input("密码/授权码", value=get_setting("email_pass"), type="password")
        email_to   = st.text_input("收件邮箱（可与发件相同）", value=get_setting("email_to"))

        b1, b2 = st.columns(2)
        saved = b1.form_submit_button("💾 保存设置", type="primary", use_container_width=True)
        tested = b2.form_submit_button("📤 发送测试邮件", use_container_width=True)

    if saved:
        for k, v in [("smtp_host", smtp_host), ("smtp_port", smtp_port),
                     ("email_from", email_from), ("email_pass", email_pass),
                     ("email_to", email_to)]:
            save_setting(k, v)
        st.success("✅ 设置已保存")

    if tested:
        # 临时保存再发
        for k, v in [("smtp_host", smtp_host), ("smtp_port", smtp_port),
                     ("email_from", email_from), ("email_pass", email_pass),
                     ("email_to", email_to)]:
            save_setting(k, v)
        ok = send_email([{"name": "iPhone 16 Pro 测试商品", "price": 7999.0,
                           "target": 8499.0, "type": "target"}])
        if ok:
            st.success("✅ 测试邮件已发送，请检查收件箱（也查一下垃圾箱）")


# ============================================================
# 入口 ————————————————————————————————————————————————————————
# ============================================================
def main():
    init_db()
    sidebar_add_product()

    # ——— 顶部标题 + 操作栏 ———
    h1, h2 = st.columns([7, 3])
    with h1:
        st.title("🛍️ 商品价格追踪器")
        st.caption("京东实时价格监控 · 目标价提醒 · 淘宝/拼多多链接聚合")
    with h2:
        st.markdown("")
        refresh_btn = st.button("🔄 立即刷新所有价格", type="primary",
                                 use_container_width=True, key="refresh_top")

    # ——— 刷新逻辑 ———
    if refresh_btn:
        with st.spinner("正在逐个检查价格，请稍候..."):
            updated, alerts = refresh_all_prices()
        if updated:
            st.success(f"✅ 已更新 {updated} 个商品的价格")
        else:
            st.warning("没有找到可更新的商品（确认商品已添加且链接有效）")
        if alerts:
            st.balloons()
            names_str = "、".join(a["name"][:10] for a in alerts[:3])
            st.warning(f"🔔 价格变动提醒：{names_str} 等 {len(alerts)} 个商品")
            sent = send_email(alerts)
            if sent:
                st.info("📧 提醒邮件已发送")
            elif get_setting("email_from"):
                st.error("邮件发送失败，请在「设置」中检查邮件配置")
        st.rerun()

    # ——— 统计卡片 ———
    df = get_products_df()
    total = len(df)
    with_price = df[df["current_price"].notna()]
    hit_target = df[
        df["target_price"].notna() &
        (df["target_price"] > 0) &
        df["current_price"].notna() &
        (df["current_price"] <= df["target_price"])
    ]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("追踪商品数",   total)
    m2.metric("已达目标价",   len(hit_target),
              delta="件可考虑购入" if hit_target.shape[0] > 0 else None)
    m3.metric("监控总金额",   f"¥{with_price['current_price'].sum():.0f}" if not with_price.empty else "—")
    if not with_price.empty:
        last = with_price["last_checked"].max()
        m4.metric("最近更新", str(last)[:16] if last else "—")
    else:
        m4.metric("最近更新", "—")

    st.divider()

    # ——— 主 Tabs ———
    tab1, tab2, tab3 = st.tabs(["📋 追踪列表", "📈 价格走势", "⚙️ 邮件设置"])
    with tab1:
        tab_watchlist(df)
    with tab2:
        tab_history(df)
    with tab3:
        tab_settings()


if __name__ == "__main__":
    main()
