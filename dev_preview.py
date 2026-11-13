#!/usr/bin/env python3
"""Kindle Desk 本地开发预览：浏览器里按 600x800 渲染真实界面，改完源码自动重载。

放在仓库根目录（与 kindle-standalone/ 同级）后运行：
    python dev_preview.py                 # 预览真实数据（kindle-standalone/data/agenda.json）
    python dev_preview.py --demo          # 用示例日程/待办填充，方便调版式
    python dev_preview.py --port 8800     # 换端口（默认 8770）

打开终端打印的地址：页面每秒自动刷新，顶部按钮切换界面，
保存 kindle-standalone/ 里任意 .py 或 assets 资源后自动用新代码重新渲染。
"""
import argparse, copy, io, sys, threading, time, traceback
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / 'kindle-standalone'
sys.path.insert(0, str(APP_DIR))

PROJECT_MODULES = ('renderer', 'store', 'native_input', 'pages', 'phone',
                   'modules', 'updater', 'device_control', 'app')

# 可在预览里切换的界面（form 需要输入法状态、pair 需要二维码组件，暂不列入）
SCREENS = [
    ('dashboard', '首页'),
    ('todos', '待办'),
    ('agenda', '日程'),
    ('calendar', '月历'),
    ('weather', '天气'),
    ('news_history', '资讯'),
    ('pomodoro', '番茄钟'),
    ('settings', '设置'),
    ('wifi', '网络'),
    ('screensaver', '待机'),
    ('module', '自选模块'),
    ('module_picker', '模块选择'),
    ('photo_picker', '图片选择'),
]

# 参与热重载判断的扩展名；data/、backups/、updates/ 是运行时目录，必须排除
WATCHED_SUFFIX = ('.py', '.otf', '.ttf', '.ttc', '.png', '.jpg', '.json', '.pem', '.js', '.css')
IGNORED_PARTS = ('data', 'backups', 'updates', '__pycache__')


def fingerprint():
    """源码与资源的修改时间指纹，变了就重建 Application。"""
    items = []
    for path in sorted(APP_DIR.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in WATCHED_SUFFIX:
            continue
        relative = path.relative_to(APP_DIR)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        stat = path.stat()
        items.append((str(relative), stat.st_mtime_ns, stat.st_size))
    return tuple(items)


class Previewer:
    def __init__(self, demo=False):
        self.demo = demo
        self.app = None
        self.stamp = None
        self.reloaded_at = '—'
        self.reload_count = 0
        self.error = ''
        self.render_ms = 0
        self.lock = threading.RLock()

    def ensure(self):
        """指纹变化就重新导入模块并重建 Application（等价于重启一次设备进程）。"""
        stamp = fingerprint()
        if self.app is not None and stamp == self.stamp:
            return
        for name in PROJECT_MODULES:
            sys.modules.pop(name, None)
        app_module = __import__('app')
        app_module.initialize_data(APP_DIR / 'data' / 'agenda.json')
        application = app_module.Application(native=False)
        if self.demo:
            self.inject_demo(application)
        self.app = application
        self.stamp = stamp
        self.reloaded_at = time.strftime('%H:%M:%S')
        self.reload_count += 1
        self.error = ''

    def inject_demo(self, application):
        """用示例数据替换只读配置，不写入设备上的真实数据文件。"""
        config = copy.deepcopy(application.store.read())
        today = datetime.now().date()
        samples = [
            ('09:30', '站会：本周看板进度'),
            ('11:00', '和设计师过一版首页布局'),
            ('14:30', '把天气模块换成两栏'),
            ('16:00', '整理日程模块的空状态'),
            ('20:00', '读完两章《设计中的设计》'),
        ]
        config['events'] = [
            dict(id='demo%02d' % index,
                 date=(today + timedelta(days=index // 3)).isoformat(),
                 time=clock, title=title, note='')
            for index, (clock, title) in enumerate(samples)
        ]
        config['todos'] = [
            dict(id='todo1', title='调一下日期字重', note='', done=False, completed_at=''),
            dict(id='todo2', title='番茄钟圆环粗细', note='', done=False, completed_at=''),
            dict(id='todo3', title='待办方框对不齐', note='', done=True,
                 completed_at=datetime.now().isoformat(timespec='seconds')),
            dict(id='todo4', title='给资讯列表加分页', note='', done=False, completed_at=''),
        ]
        config['city'] = config.get('city') or '上海'
        if not isinstance(config.get('settings'), dict):
            config['settings'] = {}

        class ReadOnlyStore:
            def read(self_inner):
                return copy.deepcopy(config)

        application.store = ReadOnlyStore()
        application.config = config

    def frame(self, mode, page):
        with self.lock:
            self.ensure()
            application = self.app
            if mode not in dict(SCREENS):
                mode = 'dashboard'
            application.mode = mode
            if mode == 'settings':
                import renderer as ui
                tabs = list(ui.SETTINGS_TABS)  # ('content','display','network')
                application.settings_page = tabs[max(0, page) % len(tabs)]
            if mode == 'module':
                application.module_page = max(0, page)
            started = time.perf_counter()
            image = application.frame()
            self.render_ms = int((time.perf_counter() - started) * 1000)
            return image

    def settings_pages(self):
        try:
            import renderer as ui
            return max(1, len(ui.SETTINGS_TABS))
        except Exception:
            return 1


PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Kindle Desk 本地预览</title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#141414;color:#e8e8e8;font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{display:flex;flex-wrap:wrap;gap:6px;padding:10px 14px;align-items:center;border-bottom:1px solid #2c2c2c;position:sticky;top:0;background:#141414;z-index:2}
button{background:#242424;color:#ddd;border:1px solid #383838;border-radius:6px;padding:5px 11px;font-size:13px;cursor:pointer}
button:hover{background:#2f2f2f}
button.on{background:#e8e8e8;color:#111;border-color:#e8e8e8}
#reload{margin-left:8px;border-color:#4a4a4a;color:#9ad}
main{display:flex;justify-content:center;padding:18px}
.screen{background:#fff;box-shadow:0 6px 26px rgba(0,0,0,.55);line-height:0}
img{width:600px;height:800px;image-rendering:pixelated;display:block}
footer{padding:0 14px 18px;color:#8b8b8b;font-size:12px}
code{background:#222;padding:1px 5px;border-radius:4px}
.err{color:#ff8a80;white-space:pre-wrap;padding:0 14px;font-family:ui-monospace,monospace;font-size:12px}
#pager{display:none;gap:4px;align-items:center;margin-left:8px}
#pager span{color:#8b8b8b;font-size:12px;min-width:54px;text-align:center}
</style></head><body>
<header>%(buttons)s
  <span id="pager"><button id="prev">‹</button><span id="pnum"></span><button id="next">›</button></span>
  <button id="reload" title="清空缓存重建 Application">↻ 重载</button>
  <span style="margin-left:auto;color:#7d7d7d" id="meta"></span>
</header>
<main><div class="screen"><img id="shot" alt="Kindle 预览" src="/frame.png?mode=%(mode)s"></div></main>
<div class="err" id="err"></div>
<footer>每秒自动刷新 · 保存 <code>kindle-standalone/</code> 下的 .py 或字体/图片后自动重载 · 输出为 600×800 灰度</footer>
<script>
var mode='%(mode)s', page=0, maxPage=%(pages)d;
var shot=document.getElementById('shot'), meta=document.getElementById('meta'), err=document.getElementById('err');
var pager=document.getElementById('pager'), pnum=document.getElementById('pnum');
function paintPager(){
  var on=(mode==='settings'||mode==='module');
  pager.style.display=on?'flex':'none';
  pnum.textContent=(mode==='settings')?((page+1)+' / '+maxPage):(page+1);
}
document.querySelectorAll('header button[data-mode]').forEach(function(b){
  b.onclick=function(){
    document.querySelectorAll('header button[data-mode]').forEach(function(x){x.classList.remove('on');});
    b.classList.add('on'); mode=b.dataset.mode; page=0; paintPager(); tick();
  };
});
document.getElementById('prev').onclick=function(){ if(page>0){page--;paintPager();tick();} };
document.getElementById('next').onclick=function(){ page++;paintPager();tick(); };
document.getElementById('reload').onclick=function(){
  fetch('/reload').then(function(){ tick(); });
};
function tick(){
  var started=Date.now();
  shot.onload=function(){
    var cost=Date.now()-started;
    meta.textContent=mode+' · '+cost+'ms';
    err.textContent='';
    fetch('/status.json').then(function(r){return r.json();}).then(function(s){
      meta.textContent=mode+' · '+cost+'ms · 第'+s.reload_count+'次加载 '+s.reloaded_at;
    }).catch(function(){});
  };
  shot.onerror=function(){
    meta.textContent='渲染失败';
    fetch('/last-error').then(function(r){return r.text();}).then(function(t){err.textContent=t;});
  };
  shot.src='/frame.png?mode='+mode+'&page='+page+'&t='+Date.now();
}
paintPager();
setInterval(tick,1000);
tick();
</script></body></html>"""


def make_handler(preview):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, kind='text/html; charset=utf-8'):
            try:
                self.send_response(code)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                # 页面每秒轮询会主动取消上一个请求，浏览器已断开就静默丢弃，
                # 避免 Windows 上刷屏 ConnectionAbortedError [WinError 10053]。
                pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            mode = query.get('mode', ['dashboard'])[0]
            try:
                page = int(query.get('page', ['0'])[0] or 0)
            except ValueError:
                page = 0
            if parsed.path == '/frame.png':
                try:
                    buffer = io.BytesIO()
                    preview.frame(mode, page).save(buffer, 'PNG')
                    return self.send(200, buffer.getvalue(), 'image/png')
                except Exception:
                    preview.error = traceback.format_exc()
                    print(preview.error, file=sys.stderr, flush=True)
                    return self.send(500, preview.error.encode('utf-8'), 'text/plain; charset=utf-8')
            if parsed.path == '/last-error':
                return self.send(200, (preview.error or '（没有记录到错误）').encode('utf-8'),
                                 'text/plain; charset=utf-8')
            if parsed.path == '/reload':
                preview.stamp = None
                try:
                    preview.frame(mode, page)
                except Exception:
                    preview.error = traceback.format_exc()
                return self.send(200, b'ok', 'text/plain')
            if parsed.path == '/status.json':
                import json
                return self.send(200, json.dumps(dict(
                    mode=mode, page=page, demo=preview.demo,
                    reloaded_at=preview.reloaded_at, reload_count=preview.reload_count,
                    render_ms=preview.render_ms, files=len(preview.stamp or ())),
                    ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')
            if parsed.path in ('/', '/index.html'):
                buttons = ''.join(
                    '<button data-mode="%s" class="%s">%s</button>'
                    % (key, 'on' if key == mode else '', label)
                    for key, label in SCREENS)
                return self.send(200, (PAGE % dict(buttons=buttons, mode=mode,
                                                   pages=preview.settings_pages())).encode('utf-8'))
            return self.send(404, b'Not found', 'text/plain')

    return Handler


def main():
    parser = argparse.ArgumentParser(description='Kindle Desk 本地预览服务器')
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--demo', action='store_true', help='用示例日程和待办填充预览')
    parser.add_argument('--once', metavar='OUT',
                        help='只渲染一次并保存为 PNG，例如 --once calendar.png --mode calendar')
    parser.add_argument('--mode', default='dashboard')
    parser.add_argument('--page', type=int, default=0,
                        help='配合 --once 使用：设置页 0/1/2 = 内容/显示·待机/网络·天气')
    args = parser.parse_args()

    preview = Previewer(demo=args.demo)
    if args.once:
        preview.frame(args.mode, args.page).save(args.once)
        print('已保存', args.once)
        return

    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(preview))
    server.daemon_threads = True
    print('预览地址： http://127.0.0.1:%d/   （Ctrl+C 结束）' % args.port, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
