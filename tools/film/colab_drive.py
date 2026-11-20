"""通过本机调试端口接管独立 Chrome（colab-film 配置），在 Colab 里开 H3 工作机。

用法（Windows Python，项目根目录）：
  python -X utf8 tools/film/colab_drive.py new <worker名> <GPU标签，如 "G4 GPU">   # 新建笔记本→设运行时→粘贴启动单元→运行
  python -X utf8 tools/film/colab_drive.py shot <worker名|index> <输出png>
  python -X utf8 tools/film/colab_drive.py list
派片地址和令牌从 renders/farm/url、renders/farm/token 读取，只写进该笔记本单元，不写项目文件。
"""
import argparse
from film_config import FilmConfig, add_film_args
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FILM = FilmConfig()
CDP = "http://127.0.0.1:9333"


LAB = None   # 设为 lab 脚本名（tools/film/lab/<名>）时，启动单元改跑模型测试


def boot_code(worker):
    b = (ROOT / "renders/farm/url").read_text().strip()
    t = (ROOT / "renders/farm/token").read_text().strip()
    path = f"/lab/file/{LAB}" if LAB else "/boot.py"
    return (f'B="{b}"; T="{t}"; W="{worker}"\n'
            'import urllib.request\n'
            f'exec(urllib.request.urlopen(f"{{B}}{path}?t={{T}}", timeout=60).read().decode())')


def click_text(page, texts, timeout=8000):
    last = None
    for t in texts:
        try:
            page.get_by_text(t, exact=True).first.click(timeout=timeout)
            return t
        except Exception as e:
            last = e
    raise last


def find_page(ctx, key):
    pages = [p for p in ctx.pages if "colab.research.google.com" in p.url]
    if key.isdigit():
        return pages[int(key)]
    for p in pages:   # 精确匹配笔记本名（前缀匹配会把 ltx_echo 认成 ltx_echoB，曾因此删错运行时）
        t = p.evaluate("document.title")
        if t.startswith(key + ".ipynb") or t == key:
            return p
    raise SystemExit(f"找不到页面 {key}")


def new_worker(ctx, worker, gpu):
    page = ctx.new_page()
    page.goto("https://colab.research.google.com/#create=true", wait_until="domcontentloaded")
    page.wait_for_selector(".cell", timeout=60000)
    time.sleep(3)
    # 改名，方便区分
    try:
        title = page.locator("#doc-name, input.doc-name, [aria-label='笔记本名称'], [aria-label='Notebook name']").first
        title.click(timeout=5000)
        page.keyboard.press("Control+A")
        page.keyboard.insert_text(f"{FILM.name}_{worker}.ipynb")
        page.keyboard.press("Enter")
    except Exception as e:
        print("rename skipped:", str(e)[:120])
    # 运行时类型
    click_text(page, ["代码执行程序", "Runtime", "运行时"])
    time.sleep(1)
    click_text(page, ["更改运行时类型", "Change runtime type"])
    time.sleep(2)
    page.get_by_text(gpu, exact=True).first.click(timeout=10000)
    time.sleep(1)
    boot_cell(page, worker)


def save_dialog(page):
    for name in ("保存", "Save"):
        try:
            page.get_by_role("button", name=name, exact=True).last.click(timeout=5000)
            return
        except Exception:
            pass
    page.locator("mwc-dialog[open] [dialogaction=ok], md-dialog[open] [value=ok], .mdc-dialog--open button").last.click(timeout=5000)


def boot_cell(page, worker):
    if page.get_by_text("更改运行时类型", exact=True).count() or page.get_by_text("Change runtime type", exact=True).count():
        save_dialog(page)
    time.sleep(3)
    # 粘贴启动单元并运行
    editor = page.locator(".cell .monaco-editor, .cell .inputarea, .cell textarea").first
    editor.click(timeout=10000)
    page.keyboard.insert_text(boot_code(worker))
    time.sleep(1)
    page.keyboard.press("Control+Enter")
    time.sleep(8)
    page.screenshot(path=str(ROOT / f"renders/farm/{worker}_start.png"))
    print("started", worker, page.url)


def main():
    global FILM
    ap = argparse.ArgumentParser(add_help=False)
    add_film_args(ap)
    args, rest = ap.parse_known_args()
    FILM = FilmConfig(args.film)
    sys.argv = [sys.argv[0]] + rest
    cmd = sys.argv[1]
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        if cmd == "list":
            for i, pg in enumerate([x for x in ctx.pages if "colab" in x.url]):
                print(i, pg.evaluate("document.title"), pg.url[:100])
        elif cmd == "shot":
            find_page(ctx, sys.argv[2]).screenshot(path=sys.argv[3])
        elif cmd == "new":
            new_worker(ctx, sys.argv[2], sys.argv[3])
        elif cmd == "newlab":     # newlab <worker> <GPU> <lab脚本名>
            global LAB
            LAB = sys.argv[4]
            new_worker(ctx, sys.argv[2], sys.argv[3])
        elif cmd == "boot":
            boot_cell(find_page(ctx, sys.argv[2]), sys.argv[3])
        elif cmd == "rerun":      # 中断当前单元并重跑（重新下载 boot.py）
            pg = find_page(ctx, sys.argv[2])
            pg.bring_to_front()
            click_text(pg, ["代码执行程序", "Runtime"])
            time.sleep(1)
            pg.locator("[role=menuitem]:visible", has_text="中断执行").first.click(timeout=8000)
            time.sleep(6)
            pg.locator(".cell .monaco-editor").first.click(timeout=10000)
            pg.keyboard.press("Control+Enter")
            time.sleep(10)
            pg.screenshot(path=str(ROOT / f"renders/farm/rerun_{sys.argv[2]}.png"))
            print("rerun", sys.argv[2])
        elif cmd == "kill":       # 断开连接并删除运行时（停止计费）
            pg = find_page(ctx, sys.argv[2])
            pg.bring_to_front()
            click_text(pg, ["代码执行程序", "Runtime"])
            time.sleep(1)
            pg.locator("[role=menuitem]:visible", has_text="断开连接并删除运行时").first.click(timeout=8000)
            time.sleep(2)
            for name in ("是", "Yes", "确定", "OK"):
                try:
                    pg.get_by_role("button", name=name, exact=True).last.click(timeout=3000)
                    break
                except Exception:
                    pass
            time.sleep(3)
            pg.screenshot(path=str(ROOT / f"renders/farm/kill_{sys.argv[2]}.png"))
            print("killed", sys.argv[2])
        elif cmd == "stop":       # 只中断当前单元，不删运行时（权重保留，之后可 run 续跑）
            pg = find_page(ctx, sys.argv[2])
            pg.bring_to_front()
            click_text(pg, ["代码执行程序", "Runtime"])
            time.sleep(1)
            pg.locator("[role=menuitem]:visible", has_text="中断执行").first.click(timeout=8000)
            time.sleep(3)
            print("stopped", sys.argv[2])
        elif cmd == "reboot":     # 隧道地址变了：中断，把单元整体换成新的启动代码再运行（运行时和权重保留）
            pg = find_page(ctx, sys.argv[2])
            pg.bring_to_front()
            if "--reload" in sys.argv:    # 页面和运行时断开时（中断无效、一直"正在执行"），先刷新页面重连
                sys.argv.remove("--reload")
                pg.reload(wait_until="domcontentloaded"); time.sleep(25)
            pg.keyboard.press("Escape")
            pg.keyboard.press("Control+M"); pg.keyboard.press("I")      # Colab 快捷键：中断执行
            time.sleep(6)
            # 直接改 Monaco 模型的文本（键盘 Ctrl+A 在焦点不在编辑器时会全选整页，旧代码就这样失败过）
            code = boot_code(sys.argv[3] if len(sys.argv) > 3 else sys.argv[2].removeprefix("starcore_"))
            n = pg.evaluate("""c => { let n = 0; for (const m of monaco.editor.getModels())
                    if (m.getValue().startsWith('B="https://')) { m.setValue(c); n++ } return n }""", code)
            if n < 1:
                raise SystemExit(f"启动单元匹配到 {n} 个，未重启")
            pg.locator(".cell").first.click(timeout=10000)
            pg.locator(".cell colab-run-button").first.click(timeout=10000)
            time.sleep(8)
            pg.screenshot(path=str(ROOT / f"renders/farm/reboot_{sys.argv[2]}.png"))
            print("rebooted", sys.argv[2])
        elif cmd == "restart":    # 中断无效（主线程卡在网络调用里）时：重启会话（保留运行时和磁盘上的权重）再运行第一个单元
            pg = find_page(ctx, sys.argv[2])
            pg.bring_to_front()
            pg.keyboard.press("Escape")
            click_text(pg, ["代码执行程序", "Runtime"])
            time.sleep(1)
            pg.locator("[role=menuitem]:visible", has_text="重启会话").first.click(timeout=8000)
            time.sleep(2)
            for name in ("是", "Yes", "确定", "OK"):
                try:
                    pg.get_by_role("button", name=name, exact=True).last.click(timeout=3000)
                    break
                except Exception:
                    pass
            time.sleep(12)
            pg.locator(".cell colab-run-button").first.click(timeout=10000)
            time.sleep(10)
            pg.screenshot(path=str(ROOT / f"renders/farm/restart_{sys.argv[2]}.png"))
            print("restarted", sys.argv[2])
        elif cmd == "close":      # 关掉已删除运行时的页面标签
            find_page(ctx, sys.argv[2]).close()
            print("closed", sys.argv[2])
        elif cmd == "run":        # 单元已结束时直接重跑第一个单元（rerun 的「中断执行」在空闲时不可点）
            pg = find_page(ctx, sys.argv[2])
            pg.bring_to_front()
            pg.locator(".cell .monaco-editor").first.click(timeout=10000)
            pg.keyboard.press("Control+Enter")
            time.sleep(8)
            pg.screenshot(path=str(ROOT / f"renders/farm/run_{sys.argv[2]}.png"))
            print("run", sys.argv[2])
        elif cmd == "term":       # term <worker> "<shell命令>" <输出png>：在 Colab 自带终端里执行（单元在跑时也能看日志）
            pg = find_page(ctx, sys.argv[2])
            pg.bring_to_front()
            if not pg.locator(".xterm:visible").count():
                pg.get_by_text("终端").last.click(timeout=8000)
                time.sleep(8)
            pg.locator(".xterm:visible").last.click(timeout=10000)
            pg.keyboard.type(sys.argv[3] + "\n", delay=5)
            time.sleep(4)
            pg.screenshot(path=sys.argv[4])
        elif cmd == "click":
            pg = find_page(ctx, sys.argv[2])
            click_text(pg, sys.argv[3:])
            time.sleep(2)
        browser.close() if False else None


if __name__ == "__main__":
    main()
