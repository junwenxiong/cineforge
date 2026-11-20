"""Private read-only probe for the isolated Colab profile; never emit cell text/URLs."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

if len(sys.argv) > 1 and sys.argv[1] == "--drive":
    # Existing driver saves screenshots automatically. Mask credential-bearing cells.
    original = Page.screenshot
    def masked(self, *args, **kwargs):
        kwargs["mask"] = [self.locator(".cell"), self.locator(".xterm")]
        return original(self, *args, **kwargs)
    Page.screenshot = masked
    sys.argv = ["colab_drive.py", *sys.argv[2:]]
    import colab_drive
    colab_drive.main()
    raise SystemExit(0)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp('http://127.0.0.1:9333')
    result = []
    for page in browser.contexts[0].pages:
        if 'colab.research.google.com' not in page.url:
            continue
        title = page.title().removesuffix(' - Colab').removesuffix('.ipynb')
        # Whitelist names; arbitrary notebook titles and source are never logged.
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]+', title):
            title = 'unknown'
        body = page.locator('body').inner_text()
        limited = any(x in body for x in ('会话太多', 'Too many sessions'))
        connect = page.get_by_role('button', name=re.compile(r'^(连接|Connect)$')).count() > 0
        busy = page.locator('.cell.running, .cell.executing').count() > 0
        if len(sys.argv) > 1 and title == sys.argv[1]:
            # Mask all cell content, including credentials in bootstrap code/output.
            page.screenshot(path=str(Path(__file__).resolve().parents[2] / 'renders/farm' / f'supervisor_{title}.png'),
                            mask=[page.locator('.cell'), page.locator('.xterm')])
        result.append(dict(name=title, limited=limited, disconnected=connect, busy=busy))
    print(json.dumps(result))
