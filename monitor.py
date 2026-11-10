"""
monitor.py —— 价格监控独立脚本
可通过 Windows 任务计划程序或 Claude Desktop 定时任务定期执行
用法：python monitor.py
"""

import requests
import sqlite3
import smtplib
import ssl
import time
import os
import re
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "tracker.db")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.jd.com/",
}

def db_conn():
    return sqlite3.connect(DB_PATH)

def get_setting(key, default=""):
    conn = db_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default

def fetch_jd_price(sku_id):
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

def send_alert(alerts):
    cfg = {k: get_setting(k) for k in
           ("smtp_host", "smtp_port", "email_from", "email_pass", "email_to")}
    if not cfg["email_from"] or not cfg["email_to"]:
        print("未配置邮件，跳过发送")
        return

    rows = ""
    for a in alerts:
        if a["type"] == "target":
            rows += f"<tr><td>{a['name']}</td><td style='color:green'>达到目标价</td><td style='color:red;font-weight:bold'>¥{a['price']:.2f}</td><td>目标 ¥{a['target']:.2f}</td></tr>"
        else:
            rows += f"<tr><td>{a['name']}</td><td style='color:red'>降价 {a['drop_pct']:.1f}%</td><td style='color:red;font-weight:bold'>¥{a['price']:.2f}</td><td>原价 ¥{a['old_price']:.2f}</td></tr>"

    html = f"""
    <html><body style="font-family:sans-serif">
    <h2>🔔 商品价格提醒 ({datetime.now().strftime('%Y-%m-%d %H:%M')})</h2>
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse">
      <tr style="background:#eee"><th>商品</th><th>状态</th><th>当前价格</th><th>参考</th></tr>
      {rows}
    </table>
    <p style="color:#999;font-size:12px">来自 商品价格追踪器 · 自动监控</p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔔 价格提醒：{len(alerts)} 个商品值得关注"
    msg["From"]    = cfg["email_from"]
    msg["To"]      = cfg["email_to"]
    msg.attach(MIMEText(html, "html", "utf-8"))

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
        print(f"[{datetime.now()}] 提醒邮件已发送至 {cfg['email_to']}")
    except Exception as e:
        print(f"[{datetime.now()}] 邮件发送失败: {e}")


def run():
    if not os.path.exists(DB_PATH):
        print("数据库不存在，请先启动 app.py 并添加商品")
        return

    conn = db_conn()
    rows = conn.execute("""
        SELECT id, name, jd_sku, current_price, target_price
        FROM products WHERE is_active=1 AND jd_sku IS NOT NULL
    """).fetchall()
    conn.close()

    print(f"[{datetime.now()}] 开始检查 {len(rows)} 个商品价格...")
    alerts, updated = [], 0

    for pid, name, sku, old_price, target in rows:
        new_price = fetch_jd_price(sku)
        if new_price is None:
            print(f"  ✗ {name}：获取失败")
            continue

        now = datetime.now().isoformat(timespec="seconds")
        conn = db_conn()
        conn.execute("UPDATE products SET current_price=?, last_checked=? WHERE id=?",
                     (new_price, now, pid))
        conn.execute("INSERT INTO price_history (product_id, price) VALUES (?,?)", (pid, new_price))
        conn.commit()
        conn.close()
        updated += 1

        status = ""
        if target and new_price <= target:
            alerts.append({"name": name, "price": new_price, "target": target, "type": "target"})
            status = f"✅ 达目标价 ¥{target}"
        elif old_price and new_price < old_price * 0.95:
            drop = (old_price - new_price) / old_price * 100
            alerts.append({"name": name, "price": new_price, "old_price": old_price,
                           "drop_pct": drop, "type": "drop"})
            status = f"🔻 降价 {drop:.1f}%"
        print(f"  ✓ {name}：¥{new_price:.2f}  {status}")
        time.sleep(0.3)

    print(f"[{datetime.now()}] 更新完成：{updated} 个，提醒 {len(alerts)} 个")
    if alerts:
        send_alert(alerts)


if __name__ == "__main__":
    run()
