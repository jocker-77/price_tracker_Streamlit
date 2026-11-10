# 商品价格追踪器 — 安装部署指南

## 功能概览
- 添加京东商品链接，自动抓取名称和当前价格
- 设置目标价，降价时邮件提醒
- 淘宝/拼多多同款链接一并保存，方便跳转对比
- 价格走势图表，历史最低价一目了然
- 一键导出 Excel

---

## 第一步：安装 Python

1. 访问 https://www.python.org/downloads/ 下载 Python 3.11 或以上版本
2. 安装时勾选 **"Add Python to PATH"**（重要！）
3. 安装完成后，打开「命令提示符」（Win+R → 输入 cmd → 回车）
4. 输入 `python --version`，显示版本号表示安装成功

---

## 第二步：安装依赖

把整个 `price_tracker` 文件夹复制到你的电脑（例如桌面）。

打开命令提示符，进入该文件夹：
```
cd C:\Users\你的用户名\Desktop\price_tracker
```

安装所需的库：
```
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```
（使用清华镜像加速，国内下载更快）

---

## 第三步：启动工具

在命令提示符中运行：
```
streamlit run app.py
```

浏览器会自动打开，显示追踪器界面。
如未自动打开，手动访问 http://localhost:8501

---

## 第四步：分享给他人（局域网内）

同一 WiFi 下，其他人可以通过你的电脑 IP 地址访问：
```
http://你的IP地址:8501
```
查看本机 IP：命令提示符输入 `ipconfig`，找到「IPv4 地址」

---

## 第五步（可选）：公网分享

使用 Streamlit Cloud 免费部署，获得一个永久可访问的网址：

1. 注册 GitHub 账号：https://github.com
2. 新建一个仓库，上传 `price_tracker` 文件夹中的所有文件
3. 注册 Streamlit 账号：https://share.streamlit.io
4. 点击 "New app" → 选择你的 GitHub 仓库 → 主文件填 `app.py`
5. 部署完成后得到形如 `https://你的名字-tracker.streamlit.app` 的链接

---

## 自动定时监控（可选）

工具本身支持手动点击「刷新价格」。如需每天自动检查：

**方法：Windows 任务计划程序**
1. 搜索「任务计划程序」打开
2. 右键「创建基本任务」
3. 触发器选「每天」，时间设你想要的时间（如早上 9 点）
4. 操作选「启动程序」
5. 程序填：`python`，参数填：`C:\你的路径\price_tracker\monitor.py`

---

## 注意事项

- 京东价格接口偶尔会临时返回空，属正常现象，重新刷新即可
- 淘宝、拼多多价格需手动填写（目前不支持自动获取）
- 邮件提醒使用 QQ 邮箱时，密码栏填「授权码」而非登录密码
