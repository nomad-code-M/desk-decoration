"""Build the end-user archive: runtime payload, installer, user docs only.

Dev files (tests, scripts, .github, .vscode, README, CHANGELOG) and the marketing
screenshots are never packed, so the download stays small and free of internals.
"""
import ast, hashlib, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'kindle-standalone'
VERSION = '1.0.0'
DIST = ROOT / 'dist'
PACKAGE = f'kindle-desk-{VERSION}'

# 用户下载包：程序本体 + KUAL 扩展 + 安装器 + 许可 + 面向用户的文档。
ROOT_FILES = ('install.py', 'requirements.txt', 'LICENSE', 'THIRD_PARTY_NOTICES.md')
APP_SUFFIXES = ('.py', '.pyw', '.sh', '.cmd')
DOCS = ('INSTALL.md', 'USAGE.md', 'FAQ.md')
# 只留在仓库、不进发行包的东西，写清楚便于以后审计。
DEV_ONLY = ('tests', 'scripts', '.github', '.vscode', '.gitignore', '.gitattributes',
            'docs/images', 'README.md', 'FKREADME.md', 'CHANGELOG.md', 'dev_preview.py')

ENTRY_NOTE = """Kindle Desk {version} · 老 Kindle 桌面看板
================================================

1. 电脑装 Python 3.9+，按 docs/INSTALL.md 先准备好 Kindle 的 Python 运行环境。
2. 解压本包，在当前目录执行：

       python -m pip install -r requirements.txt
       python install.py --check
       python install.py <Kindle 磁盘根目录>      例如 F:/ 或 /Volumes/Kindle

3. 安全弹出 USB，连接 Wi-Fi，在书库打开 IndependentDashboard，或从 KUAL 启动。

安装过程中遇到问题先看 docs/INSTALL.md 与 docs/FAQ.md。
本包不含开发与测试文件；需要源码请到仓库下载源码 ZIP。
"""


def _walk(*relative):
    for path in (ROOT / Path(*relative)).rglob('*'):
        if not path.is_file():
            continue
        parts = path.relative_to(ROOT).parts
        if '__pycache__' in parts or path.suffix in ('.pyc', '.pyo'):
            continue  # 本机跑过测试后生成的缓存，不属于发行内容
        yield path.relative_to(ROOT).as_posix()


def release_files():
    """Allowlisted manifest, sorted; raises before any private file can ship."""
    names = list(ROOT_FILES)
    names += [f'docs/{name}' for name in DOCS]
    names += [p.relative_to(ROOT).as_posix() for p in APP.iterdir()
              if p.is_file() and p.suffix in APP_SUFFIXES]
    for folder in ('kindle-standalone/assets', 'kindle-standalone/vendor', 'extensions'):
        names += list(_walk(folder))

    names = sorted(set(names))
    for name in names:
        parts = Path(name).parts
        if not (ROOT / name).is_file():
            raise ValueError('发行清单里的文件不存在：' + name)
        if any(part in ('data', 'backups', 'updates', '__pycache__') for part in parts):
            raise ValueError('私有或缓存文件混入发行清单：' + name)
        if 'wireless-device' in name:
            raise ValueError('连接凭据混入发行清单：' + name)
        if name.endswith(('.pyc', '.pyo')):
            raise ValueError('字节码文件混入发行清单：' + name)
        if name.endswith(('.ttc', '.ttf')) or Path(name).name.startswith(('msyh', 'arial')):
            raise ValueError('专有字体混入发行清单：' + name)
        if any(name == dev or name.startswith(dev + '/') for dev in DEV_ONLY):
            raise ValueError('开发文件混入发行清单：' + name)
    return names


def check_payload(names):
    """install.py 负责把程序复制上设备，清单里必须包含它要求的每个文件。"""
    tree = ast.parse((ROOT / 'install.py').read_text(encoding='utf-8'))
    device = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'FILES')
    missing = ['kindle-standalone/' + n for n in device if 'kindle-standalone/' + n not in names]
    if missing:
        raise ValueError('install.py 需要的文件没进发行包：' + '、'.join(missing))
    # 许可声明点名的三个许可文件必须随包发出，否则署名义务缺证据。
    for required in ('kindle-standalone/assets/ime/a.json',
                     'kindle-standalone/vendor/qrcode/__init__.py',
                     'kindle-standalone/vendor/qrcode-7.4.2.dist-info/LICENSE',
                     'kindle-standalone/vendor/pypng-0.20220715.0.dist-info/LICENCE',
                     'kindle-standalone/vendor/typing_extensions-4.7.1.dist-info/LICENSE'):
        if required not in names:
            raise ValueError('运行或许可必需文件缺失：' + required)


def build():
    names = release_files()
    check_payload(names)
    DIST.mkdir(exist_ok=True)
    path = DIST / f'{PACKAGE}.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(f'{PACKAGE}/使用说明.txt', ENTRY_NOTE.format(version=VERSION))
        for name in names:
            archive.write(ROOT / name, f'{PACKAGE}/{name}')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (DIST / 'SHA256SUMS.txt').write_text(digest + '  ' + path.name + '\n', encoding='utf-8')
    print(path.name, path.stat().st_size, 'bytes', len(names) + 1, 'files')
    print('SHA256', digest)


if __name__ == '__main__':
    build()