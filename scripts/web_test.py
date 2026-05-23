"""
QuantPro Web端完整链路测试 — Playwright
测试所有页面加载、API端点、核心交互功能
"""

import sys
import time
import json
import requests
from pathlib import Path
from datetime import datetime

BASE = "http://127.0.0.1:5000"
results = []


def log(name, status, detail=""):
    icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    msg = f"{icon} [{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append({"name": name, "status": status, "detail": detail})


def test_api_endpoints():
    print("\n" + "=" * 60)
    print("  1. API 端点测试")
    print("=" * 60)

    endpoints = [
        ("GET", "/api/health", "健康检查"),
        ("GET", "/api/system/status", "系统状态"),
        ("GET", "/api/stock/list?page=1&limit=5", "股票列表"),
        ("GET", "/api/stock/detail/sh600519", "股票详情(茅台)"),
        ("GET", "/api/stock/search?keyword=茅台", "股票搜索"),
        ("GET", "/api/stock/realtime?codes=sh600519", "实时行情"),
        ("GET", "/api/stock/daily/sh600519", "日线数据"),
        ("GET", "/api/news/latest", "最新新闻"),
        ("GET", "/api/train/status", "训练状态"),
        ("GET", "/api/train/factors", "因子库"),
        ("GET", "/api/train/reports", "训练报告"),
        ("GET", "/api/train/models", "模型列表"),
        ("GET", "/api/index/realtime", "大盘指数"),
        ("GET", "/api/market/overview", "市场概览"),
        ("GET", "/api/portfolio/summary", "组合概览"),
        ("GET", "/api/backtest/history", "回测历史"),
        ("GET", "/api/logs?limit=5", "操作日志"),
    ]

    for method, path, desc in endpoints:
        try:
            r = requests.request(method, BASE + path, timeout=10)
            if r.status_code == 200:
                d = r.json()
                if d.get("success") or d.get("data") is not None:
                    log(f"API {desc}", "PASS", f"status={r.status_code}")
                else:
                    log(f"API {desc}", "WARN", f"success=false, error={d.get('error','')[:60]}")
            else:
                log(f"API {desc}", "FAIL", f"status={r.status_code}")
        except Exception as e:
            log(f"API {desc}", "FAIL", str(e)[:80])


def test_pages_load():
    print("\n" + "=" * 60)
    print("  2. 页面加载测试 (Playwright)")
    print("=" * 60)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("Playwright", "FAIL", "未安装playwright")
        return

    pages = [
        ("/", "首页"),
        ("/stocks.html", "A股市场"),
        ("/stock-detail.html?code=sh600519", "股票详情(茅台)"),
        ("/positions.html", "持仓管理"),
        ("/backtest.html", "回测"),
        ("/model-training.html", "模型训练"),
        ("/ai.html", "AI助手"),
        ("/news.html", "资讯中心"),
        ("/daily-news.html", "每日讯息"),
        ("/history.html", "操作历史"),
        ("/settings.html", "设置"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})

        for path, name in pages:
            page = context.new_page()
            try:
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))

                page.goto(BASE + path, wait_until="networkidle", timeout=15000)
                title = page.title()

                if "404" in title:
                    log(f"页面 {name}", "FAIL", "404 Not Found")
                elif errors:
                    log(f"页面 {name}", "WARN", f"JS错误: {errors[0][:60]}")
                else:
                    log(f"页面 {name}", "PASS", f"title={title[:30]}")

            except Exception as e:
                log(f"页面 {name}", "FAIL", str(e)[:80])
            finally:
                page.close()

        browser.close()


def test_stock_detail_interactions():
    print("\n" + "=" * 60)
    print("  3. 股票详情页交互测试 (Playwright)")
    print("=" * 60)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        try:
            errors = []
            console_msgs = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.on("console", lambda msg: console_msgs.append(f"[{msg.type}] {msg.text[:100]}") if msg.type in ["error", "warning"] else None)

            page.goto(BASE + "/stock-detail.html?code=sh600519", wait_until="networkidle", timeout=20000)
            time.sleep(8)

            if errors:
                log("详情页JS错误", "WARN", f"errors={errors[:2]}")

            name_el = page.query_selector("#stockName")
            name_text = name_el.inner_text() if name_el else ""
            if name_text and name_text != "加载中..." and name_text != "sh600519":
                log("股票名称显示", "PASS", f"name={name_text}")
            else:
                log("股票名称显示", "FAIL", f"name={name_text}")

            price_el = page.query_selector("#stockPrice")
            price_text = price_el.inner_text() if price_el else ""
            if price_text and price_text not in ["加载中...", ""]:
                try:
                    float(price_text)
                    log("股票价格显示", "PASS", f"price={price_text}")
                except ValueError:
                    log("股票价格显示", "FAIL", f"非数字: {price_text}")
            else:
                log("股票价格显示", "FAIL", f"price={price_text}")

            change_el = page.query_selector("#stockChange")
            change_text = change_el.inner_text() if change_el else ""
            if change_text and "加载中" not in change_text:
                log("涨跌幅显示", "PASS", f"change={change_text[:20]}")
            else:
                log("涨跌幅显示", "FAIL", f"change={change_text}")

            canvas = page.query_selector("canvas")
            if canvas:
                log("K线图Canvas", "PASS", "canvas元素存在")
            else:
                log("K线图Canvas", "FAIL", "canvas元素不存在")

            pulse_dots = page.query_selector_all(".pulse-dot")
            if len(pulse_dots) == 0:
                log("pulse-dot已删除", "PASS")
            else:
                log("pulse-dot已删除", "FAIL", f"仍有{len(pulse_dots)}个pulse-dot")

            ai_company = page.query_selector_all(":text('AI公司分析')")
            if len(ai_company) == 0:
                log("AI公司分析已删除", "PASS")
            else:
                log("AI公司分析已删除", "FAIL", "仍存在AI公司分析板块")

        except Exception as e:
            log("股票详情交互", "FAIL", str(e)[:80])
        finally:
            browser.close()


def test_stocks_page():
    print("\n" + "=" * 60)
    print("  4. A股市场页测试 (Playwright)")
    print("=" * 60)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        try:
            page.goto(BASE + "/stocks.html", wait_until="networkidle", timeout=15000)
            time.sleep(3)

            rows = page.query_selector_all("table tbody tr")
            if len(rows) > 0:
                log("股票列表加载", "PASS", f"rows={len(rows)}")
            else:
                log("股票列表加载", "FAIL", "表格无数据")

            sh_btn = page.query_selector(":text('沪A')")
            sz_btn = page.query_selector(":text('深A')")
            if sh_btn and sz_btn:
                log("市场筛选按钮", "PASS", "沪A/深A按钮存在")
            else:
                log("市场筛选按钮", "FAIL", "按钮缺失")

            search_input = page.query_selector("input[placeholder*='搜索']")
            if search_input:
                log("搜索框", "PASS")
            else:
                log("搜索框", "WARN", "未找到搜索输入框")

        except Exception as e:
            log("A股市场页", "FAIL", str(e)[:80])
        finally:
            browser.close()


def test_training_page():
    print("\n" + "=" * 60)
    print("  5. 模型训练页测试 (Playwright)")
    print("=" * 60)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        try:
            page.goto(BASE + "/model-training.html", wait_until="networkidle", timeout=15000)
            time.sleep(3)

            start_btn = page.query_selector("#startBtn")
            if start_btn:
                log("训练启动按钮", "PASS")
            else:
                log("训练启动按钮", "FAIL", "按钮不存在")

            mode_select = page.query_selector("#mode")
            if mode_select:
                log("训练模式选择", "PASS")
            else:
                log("训练模式选择", "FAIL")

            alpha_toggle = page.query_selector("#alpha158")
            if alpha_toggle:
                log("Alpha158开关", "PASS")
            else:
                log("Alpha158开关", "FAIL")

            log_console = page.query_selector("#logConsole")
            if log_console:
                log("训练控制台", "PASS")
            else:
                log("训练控制台", "FAIL")

            factor_chips = page.query_selector_all(".factor-chip")
            if len(factor_chips) > 0:
                log("因子库展示", "PASS", f"显示{len(factor_chips)}个因子")
            else:
                log("因子库展示", "FAIL", "无因子显示")

        except Exception as e:
            log("模型训练页", "FAIL", str(e)[:80])
        finally:
            browser.close()


def test_data_integrity():
    print("\n" + "=" * 60)
    print("  6. 数据完整性测试")
    print("=" * 60)

    try:
        r = requests.get(BASE + "/api/stock/detail/sh600519", timeout=10)
        d = r.json().get("data", {})

        if d.get("name") and d["name"] not in ["sh600519", ""]:
            log("股票名称(茅台)", "PASS", f"name={d['name']}")
        else:
            log("股票名称(茅台)", "FAIL", f"name={d.get('name')}")

        if d.get("kline") and len(d["kline"]) > 0:
            log("K线数据", "PASS", f"bars={len(d['kline'])}")
        else:
            log("K线数据", "FAIL", "无K线数据")

        kline = d.get("kline", [])
        if kline:
            first = kline[0]
            required = ["date", "open", "high", "low", "close", "volume"]
            missing = [f for f in required if f not in first]
            if not missing:
                log("K线字段完整性", "PASS")
            else:
                log("K线字段完整性", "FAIL", f"缺失: {missing}")

        if d.get("change_pct") is not None:
            log("涨跌幅数据", "PASS", f"change_pct={d['change_pct']}")
        else:
            log("涨跌幅数据", "FAIL", "无涨跌幅")

    except Exception as e:
        log("数据完整性", "FAIL", str(e)[:80])

    try:
        r = requests.get(BASE + "/api/train/factors", timeout=10)
        d = r.json()
        total = d.get("total_count", 0)
        if total >= 100:
            log("因子库数量", "PASS", f"total={total}")
        else:
            log("因子库数量", "FAIL", f"total={total}")
    except Exception as e:
        log("因子库", "FAIL", str(e)[:80])


def print_summary():
    print("\n" + "=" * 60)
    print("  测试结果汇总")
    print("=" * 60)

    passed = sum(1 for r in results if r["status"] == "PASS")
    warned = sum(1 for r in results if r["status"] == "WARN")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)

    print(f"\n  ✅ 通过: {passed}")
    print(f"  ⚠️ 警告: {warned}")
    print(f"  ❌ 失败: {failed}")
    print(f"  📊 总计: {total}")
    print(f"  📈 通过率: {passed/total*100:.1f}%")

    if failed > 0:
        print("\n  ❌ 失败项:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    - {r['name']}: {r['detail']}")

    if warned > 0:
        print("\n  ⚠️ 警告项:")
        for r in results:
            if r["status"] == "WARN":
                print(f"    - {r['name']}: {r['detail']}")

    report_path = Path(__file__).parent / "data" / "test_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "passed": passed,
            "warned": warned,
            "failed": failed,
            "total": total,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  📄 报告已保存: {report_path}")


if __name__ == "__main__":
    print("=" * 60)
    print("  QuantPro Web端完整链路测试")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  目标: {BASE}")
    print("=" * 60)

    test_api_endpoints()
    test_pages_load()
    test_stock_detail_interactions()
    test_stocks_page()
    test_training_page()
    test_data_integrity()
    print_summary()
