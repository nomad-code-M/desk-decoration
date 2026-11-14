"""Shared, versioned agenda storage for Kindle, browsers and USB editing."""
import copy, json, os, secrets, threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from contextlib import contextmanager

@contextmanager
def disk_lock(path):
    with Path(path).open('a+b') as handle:
        if os.name=='nt':
            import msvcrt
            if handle.tell()==0: handle.write(b'0'); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
        try: yield
        finally:
            if os.name=='nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

# ==================== 新闻源配置表（想加源，就在这里加一行） ====================
# 每个源是一行 dict：
#   key   : 唯一标识，设置页开关的名字是 news_<key>
#   name  : 界面/手机后台显示的名字
#   kind  : 抓取方式，见下面四种
#   limit : 这个源最多取几条（合并去重前的上限）
# 四种 kind：
#   'rss'  通用 RSS/Atom，最省事——找到站点的 RSS 地址，写一行就能加
#   'html' 网页列表，需要给两个正则参数：item_re 抓(链接,标题)，base 补全域名前缀
#   'json_douyin' 抖音热榜专用（接口返回 JSON）
#   'github'  GitHub 中文排行榜专用（要仓库名 + 中文简介，普通 html 抓不出简介）
#   'wallstreetcn' 华尔街见闻的专用接口
NEWS_SOURCES=(
    dict(key='wallstreetcn',name='华尔街见闻',kind='wallstreetcn',url='https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=100',limit=20),
    dict(key='douyin',name='抖音热榜',kind='json_douyin',url='https://www.douyin.com/aweme/v1/web/hot/search/list/',limit=20),
    # 微博热搜：接口返回 JSON（data.realtime），没有发布时间，所以和 GitHub 一样归入榜单组
    # 均匀穿插；右侧显示「热度」而不是时间
    dict(key='weibo',name='微博热搜',kind='json_weibo',url='https://weibo.com/ajax/side/hotSearch',limit=20),
    # 凤凰网：item_re 抓(链接,标题)，time_re 抓列表里的发布时间（如「今天 16:47」）
    dict(key='ifeng',name='凤凰网',kind='html',url='https://news.ifeng.com/',limit=20,
         item_re=r'href="(//news\.ifeng\.com/c/[0-9A-Za-z]+)"[^>]*>(.*?)</a>',base='https:',
         time_re=r'<time[^>]*>(.*?)</time>'),
    # GitHub 榜单：kind 改成 github 后走专门的解析，能同时拿到仓库名和一句中文简介
    dict(key='gitcn',name='GitHub中文',kind='github',url='https://gitcn.org/top-china',limit=20),
    dict(key='ithome',name='IT之家',kind='rss',url='https://www.ithome.com/rss/',limit=20),
    dict(key='tmtpost',name='钛媒体',kind='rss',url='https://www.tmtpost.com/rss',limit=20),
)

# 下面三样全部由 NEWS_SOURCES 自动派生：加源时不用再改任何地方
NEWS_SETTINGS=tuple('news_'+src['key'] for src in NEWS_SOURCES)                 # 设置的键名
NEWS_LABELS=tuple((('news_'+src['key']),src['name']) for src in NEWS_SOURCES)   # 键名 -> 界面显示名
NEWS_DEFAULTS={name:True for name in NEWS_SETTINGS}                             # 新源默认开启

DEFAULT_SETTINGS={
    'time_format':'24',
    # 每个新闻源一个开关，键名和默认值都由上面的 NEWS_SOURCES 自动生成
    **NEWS_DEFAULTS,
    'idle_minutes':15,
    'standby_wifi':True,
    'weather_interval':15,
    'full_refresh':10,
    'panel_module':'finance',
    'module_interval':30,
    'carousel_seconds':30,
    'sleep_display':'calendar',
    'panel_photo':'',
    'standby_photo':'',
}
BOOLEAN_SETTINGS={'standby_wifi'}|set(NEWS_SETTINGS)
# 需要「按秒自由填写」的数值设置：key -> (最小,最大)
RANGE_SETTINGS={'carousel_seconds':(5,300)}
CHOICE_SETTINGS={
    'time_format':('12','24'),
    'idle_minutes':(0,5,15,30,60),
    'weather_interval':(15,30,60),
    'full_refresh':(5,10,20,50),
    'panel_module':('finance','usage','photo'),
    'module_interval':(15,30,60),
    'sleep_display':('calendar','photo'),
}

def setting_value(key,value):
    # 旧的模块代号统一迁到新目录：用量类归 usage，资讯类归 finance（热点资讯）
    if key=='panel_module' and value in ('codex','deepseek'): value='usage'
    if key=='panel_module' and value in ('news','weibo'): value='finance'
    if key in ('panel_photo','standby_photo'):
        import re
        if isinstance(value,str) and (not value or re.fullmatch(r'[a-f0-9]{24}',value)): return value
    elif key in BOOLEAN_SETTINGS:
        if value in (True,'1','true','on'): return True
        if value in (False,'0','false','off'): return False
    elif key in CHOICE_SETTINGS:
        choices=CHOICE_SETTINGS[key]
        for choice in choices:
            if value==choice or str(value)==str(choice): return choice
    elif key in RANGE_SETTINGS:
        # 按秒填写的数值设置：必须是整数，且落在允许范围里
        low,high=RANGE_SETTINGS[key]
        try: number=int(value)
        except (TypeError,ValueError): raise ValueError('请填写整数。')
        if not low<=number<=high: raise ValueError(f'请填 {low} 到 {high} 之间的秒数。')
        return number
    else: raise ValueError('未知设置项。')
    raise ValueError('设置值无效。')

class Conflict(ValueError):
    pass

def event_fields(data):
    date=datetime.strptime(str(data.get('date','')).strip(),'%Y-%m-%d').date().isoformat()
    clock=str(data.get('time','')).strip()
    if clock: clock=datetime.strptime(clock,'%H:%M').strftime('%H:%M')
    title=str(data.get('title','')).strip()
    note=str(data.get('note','')).strip()
    if not title: raise ValueError('请填写日程内容。')
    if len(title)>100 or len(note)>200: raise ValueError('内容最多 100 字，备注最多 200 字。')
    return dict(date=date,time=clock,title=title,note=note)

def atomic_json(path, value):
    path=Path(path)
    temporary=path.with_suffix('.tmp')
    with temporary.open('w',encoding='utf-8',newline='\n') as output:
        json.dump(value,output,ensure_ascii=False,indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(str(temporary),str(path))

class Store:
    def __init__(self,path):
        self.path=Path(path)
        self.lock=threading.RLock()

    def read(self):
        with self.lock:
            result=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(result.get('events'),list): raise ValueError('日程文件格式不正确。')
            result.setdefault('revision',0)
            result.setdefault('todos',[])
            if not isinstance(result['todos'],list): raise ValueError('待办文件格式不正确。')
            settings=result.setdefault('settings',{})
            if not isinstance(settings,dict): raise ValueError('设置文件格式不正确。')
            # 清掉已经废弃的设置项（例如已下线的东方财富开关），避免旧配置里一直留着垃圾值
            for stale in [key for key in settings if key not in DEFAULT_SETTINGS]:
                settings.pop(stale,None)
            for key,default in DEFAULT_SETTINGS.items():
                settings[key]=setting_value(key,settings.get(key,default))
            return result

    def change(self,revision,action,data):
        with self.lock, disk_lock(self.path.with_suffix('.lock')):
            value=self.read()
            if int(revision)!=value['revision']:
                raise Conflict('内容已在另一入口更新，请重新打开页面后再修改。')
            if action in ('save','delete'):
                identity=str(data.get('id',''))
                old=next((e for e in value['events'] if e['id']==identity),None)
                if identity and old is None: raise Conflict('这条日程已被删除，请刷新列表。')
                if action=='delete':
                    if not identity: raise ValueError('未指定日程。')
                    value['events']=[e for e in value['events'] if e['id']!=identity]
                else:
                    entry=event_fields(data)
                    entry['id']=identity or secrets.token_hex(6)
                    value['events']=[e for e in value['events'] if e['id']!=identity]+[entry]
            elif action in ('todo_save','todo_state','todo_delete'):
                identity=str(data.get('id',''))
                old=next((e for e in value['todos'] if e['id']==identity),None)
                if identity and old is None: raise Conflict('这条待办已被删除，请刷新列表。')
                if action=='todo_save':
                    title=str(data.get('title','')).strip()
                    note=str(data.get('note','')).strip()
                    if not title or len(title)>100 or len(note)>200:
                        raise ValueError('请填写待办内容，最多 100 字；备注最多 200 字。')
                    entry=dict(old) if old else dict(id=secrets.token_hex(6),done=False,completed_at='')
                    entry.update(title=title,note=note)
                    if old: value['todos']=[entry if e['id']==identity else e for e in value['todos']]
                    else: value['todos'].append(entry)
                elif not old: raise ValueError('未指定待办。')
                elif action=='todo_delete': value['todos']=[e for e in value['todos'] if e['id']!=identity]
                else:
                    if str(data.get('done','')) not in ('0','1'): raise ValueError('待办状态无效。')
                    done=str(data['done'])=='1'
                    if old.get('done',False)==done: return copy.deepcopy(value)
                    old['done']=done
                    old['completed_at']=datetime.now(timezone(timedelta(hours=8))).isoformat() if done else ''
            elif action=='city':
                city=str(data.get('city','')).strip()
                if len(city)>80: raise ValueError('城市名称太长。')
                value['city']=city
            elif action=='settings':
                updates=data.get('settings')
                if not isinstance(updates,dict) or not updates: raise ValueError('请选择要修改的设置。')
                for key,item in updates.items():
                    if key not in DEFAULT_SETTINGS: raise ValueError('未知设置项。')
                    value['settings'][key]=setting_value(key,item)
                if 'city' in data:
                    city=str(data['city']).strip()
                    if len(city)>80: raise ValueError('城市名称太长。')
                    value['city']=city
            elif action=='setting':
                key=str(data.get('key',''))
                if key not in DEFAULT_SETTINGS: raise ValueError('未知设置项。')
                updated=setting_value(key,data.get('value'))
                if value['settings'][key]==updated: return copy.deepcopy(value)
                value['settings'][key]=updated
            else: raise ValueError('不支持的操作。')
            value['revision']+=1
            atomic_json(self.path.with_suffix('.backup.json'),self.read())
            atomic_json(self.path,value)
            return copy.deepcopy(value)


def initialize_data(path):
    """First boot only: each installation gets its own random pairing credential."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with disk_lock(path.with_suffix('.lock')):
        if path.exists():
            value=Store(path).read()
            if not isinstance(value.get('token'),str) or len(value['token'])<32:
                raise ValueError('已有配置的连接凭据无效，请从备份恢复；不会覆盖原数据。')
            return False
        atomic_json(path,dict(revision=0,token=secrets.token_hex(24),city='',events=[],todos=[]))
        return True
