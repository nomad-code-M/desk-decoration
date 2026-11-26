import email.utils, html, json, re, ssl, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

from news_sources import NEWS_SOURCES, BOARD_SOURCES

TZ=timezone(timedelta(hours=8))              # 项目统一用北京时间
BROWSER_UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'  # 伪装成浏览器，避免被站点拒绝
AI_KW=re.compile(r'\bAI\b|AIGC|AGI\b|人工智能|大模型|OpenAI|DeepSeek|ChatGPT|智能体|算力|英伟达|NVIDIA|机器人|Anthropic|黄仁勋|具身智能|商汤|智谱|月之暗面|Kimi|豆包|通义|文心|Sora|Copilot',re.I)  # AI 主题关键词，单独抓华尔街见闻时按它过滤
# HTML 源里这些导航词不是新闻，标题完全等于就丢弃
NAV_WORDS={'首页','登录','注册','搜索','订阅','更多','下一页','上一页','客户端','关于我们','版权声明','RSS订阅','视频直播','财经娱乐'}
GITHUB_PLACE='spread'     # 榜单摆放：spread 穿插 / bottom 沉底 / top 置顶
NEWS_INTERVAL=1800        # 抓取周期，30 分钟一轮

def _now(now_fn=None):
    # 统一取"当前时间"：外部注入了就用注入的，否则取本机北京时间
    return now_fn() if now_fn else datetime.now(TZ)


def fetch_wallstreetcn(root,ai_only=True,limit=20):
    # 华尔街见闻快讯：接口返回 JSON，取标题/正文/链接；ai_only 为真时只要 AI 主题
    data=json.loads(news_get('https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=100',root))
    items=[]
    for raw in (data.get('data') or {}).get('items') or []:
        name=(raw.get('title') or raw.get('content_text') or '').strip()
        link=(raw.get('uri') or '').strip()
        if not name or not link or (ai_only and not AI_KW.search(name)): continue
        items.append({'name':name,'content':raw.get('content_text') or name,'url':link,'time':raw.get('display_time') or 0,'source':'华尔街见闻'})
        if len(items)>=limit: break
    return items


def news_get(url,root,referer=None):
    # 带浏览器身份请求一个网址并返回文本；证书优先用项目自带的 cacert.pem，缺文件时退回系统证书
    ca_file=root/'assets/cacert.pem'
    context=ssl.create_default_context(cafile=str(ca_file)) if ca_file.exists() else ssl.create_default_context()
    headers={'User-Agent':BROWSER_UA}
    if referer: headers['Referer']=referer
    request=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(request,context=context,timeout=25) as response:
        return response.read(2*1024*1024).decode('utf-8','ignore')


def parse_rss(text,name,limit):
    # 解析 RSS 2.0 和 Atom 两种格式，统一成 {name,content,url,time,source}
    import xml.etree.ElementTree as ET
    feed=ET.fromstring(text.encode('utf-8'))   # 用 feed 命名，避免和其他函数的路径参数 root 混淆
    atom='{http://www.w3.org/2005/Atom}'
    entries=feed.findall('.//item') or feed.findall('.//'+atom+'entry')
    items=[]
    for entry in entries:
        def field(tag):
            node=entry.find(tag)
            if node is None: node=entry.find(atom+tag)
            return (node.text or '').strip() if node is not None else ''
        title=field('title'); link=field('link')
        if not link:  # Atom 把链接写在属性里
            node=entry.find(atom+'link')
            if node is not None: link=(node.get('href') or '').strip()
        if not title or not link: continue
        stamp=0
        raw_time=field('pubDate') or field('published') or field('updated')  # RSS 用 pubDate，Atom 用 published/updated
        if raw_time:
            try: stamp=int(email.utils.parsedate_to_datetime(raw_time).timestamp())
            except (TypeError,ValueError):
                try: stamp=int(datetime.fromisoformat(raw_time.replace('Z','+00:00')).timestamp())
                except (TypeError,ValueError): stamp=0
        body=field('description') or field('summary') or ''
        content=re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html.unescape(body))).strip()  # 正文里的 HTML 标签去掉
        items.append({'name':title,'content':content or title,'url':link,'time':stamp,'source':name})
        if len(items)>=limit: break
    return items


def parse_cn_time(raw,now_fn=None):
    # 把网页上的中文时间换成时间戳；认不出来的返回 0，表示"没有发布时间"
    # 支持：刚刚 / 36分钟前 / 2小时前 / 今天 16:47 / 昨天 23:10 / 11-12 08:30
    raw=(raw or '').strip()
    if not raw: return 0
    current=_now(now_fn)
    found=re.search(r'(\d+)\s*分钟前',raw)
    if found: return int((current-timedelta(minutes=int(found.group(1)))).timestamp())
    found=re.search(r'(\d+)\s*小时前',raw)
    if found: return int((current-timedelta(hours=int(found.group(1)))).timestamp())
    if '刚刚' in raw: return int(current.timestamp())
    found=re.search(r'(?:(\d{4})-)?(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})',raw)  # 没写年份就按今年算
    if found:
        year=int(found.group(1) or current.year)
        try: return int(datetime(year,int(found.group(2)),int(found.group(3)),int(found.group(4)),int(found.group(5)),tzinfo=TZ).timestamp())
        except ValueError: return 0
    found=re.search(r'(今天|昨天)?\s*(\d{1,2}):(\d{2})',raw)
    if found:
        base=current-timedelta(days=1) if found.group(1)=='昨天' else current
        try: return int(base.replace(hour=int(found.group(2)),minute=int(found.group(3)),second=0,microsecond=0).timestamp())
        except ValueError: return 0
    return 0


def parse_html(text,name,item_re,base,limit,time_re=None,now_fn=None):
    # 用正则从网页挖出 (链接, 标题)；只适合列表结构固定的站
    # time_re 可选：给一个能抓到"时间文字"的正则，就能拿到真实发布时间，抓不到就是 0
    items=[]; seen=set()
    matches=list(re.finditer(item_re,text,re.S))
    for index,match in enumerate(matches):
        link,raw_title=match.group(1),match.group(2)
        title=re.sub(r'\s+',' ',re.sub(r'<[^>]+>','',raw_title)).strip()
        if not title or title in NAV_WORDS or len(title)<4: continue
        if not link.startswith('http'): link=base+link
        link=link.replace('http://','https://',1) if link.startswith('http://') else link
        if link in seen: continue
        seen.add(link)
        stamp=0
        if time_re:
            # 时间文字在"本条标题"到"下一条标题"之间的 HTML 里，去这段里找
            end=matches[index+1].start() if index+1<len(matches) else len(text)
            found=re.search(time_re,text[match.end():end],re.S)
            if found: stamp=parse_cn_time(re.sub(r'<[^>]+>',' ',found.group(1)),now_fn)
        items.append({'name':title,'content':title,'url':link,'time':stamp,'source':name})
        if len(items)>=limit: break
    return items


def parse_github(text,name,limit,now_fn=None):
    # GitHub 中文榜：按仓库链接把页面切成一段段，每段里取仓库名 + 那一段的中文简介
    items=[]
    links=list(re.finditer(r'href="(https://github\.com/[^/"]+/[^/"]+)"',text))
    for index,match in enumerate(links):
        end=links[index+1].start() if index+1<len(links) else len(text)  # 本段结尾=下个链接开头，避免简介错位
        block=text[match.end():end]
        link=match.group(1).split('?')[0].rstrip('/')
        parts=link.replace('https://github.com/','').split('/')  # 取 owner/repo 两段当仓库名
        if len(parts)<2 or not parts[0] or not parts[1]: continue
        repo=parts[0]+'/'+parts[1]
        desc=''
        found=re.search(r'line-clamp-6[^"]*">(.*?)</div>',block,re.S)  # 站点给的中文简介在这个 div 里
        if found:
            desc=html.unescape(re.sub(r'<[^>]+>',' ',found.group(1)))
            desc=re.sub(r'\s+',' ',desc).strip()
        label=''
        stamps=re.findall(r'(\d+)\s*(秒|分钟|小时|天|个?月|年)前',block)
        if stamps:
            number,unit=stamps[-1]; number=int(number); moment=_now(now_fn)
            if unit=='秒': moment=moment-timedelta(seconds=number)
            elif unit=='分钟': moment=moment-timedelta(minutes=number)
            elif unit=='小时': moment=moment-timedelta(hours=number)
            elif unit=='天': moment=moment-timedelta(days=number)
            elif unit in ('月','个月'): moment=moment-timedelta(days=30*number)
            else: moment=moment-timedelta(days=365*number)
            # 本年度显示 月/日，跨年显示两位年份
            if moment.year==_now(now_fn).year: label=f'{moment.month}/{moment.day}'
            else: label=f'{moment.year%100}年'
        items.append({'name':repo,'content':desc or repo,'url':link,'time':0,'source':name,'date_label':label})  # 榜单无发布时间，time 给 0
        if len(items)>=limit: break
    return items


def fetch_source(src,root,now_fn=None):
    # 按配置里的 kind 选一种抓取方式，统一返回同样的字段结构
    kind=src['kind']; name=src['name']; limit=src.get('limit',20)
    if kind=='wallstreetcn': return fetch_wallstreetcn(root,ai_only=False,limit=limit)
    if kind=='json_douyin':
        raw=json.loads(news_get(src['url'],root,referer='https://www.douyin.com/'))
        stamp=int(time.time()); items=[]
        for row in (raw.get('data') or {}).get('word_list') or []:
            title=(row.get('word') or '').strip()
            if not title: continue
            items.append({'name':title,'content':title,
                          'url':'https://www.douyin.com/hot/'+str(row.get('sentence_id') or ''),
                          'time':int(row.get('event_time') or stamp),'source':name})
            if len(items)>=limit: break
        return items
    if kind=='json_weibo':
        # 微博热搜：跳过广告位；没有发布时间，热度放进 date_label 给界面右列显示
        raw=json.loads(news_get(src['url'],root,referer='https://weibo.com/'))
        items=[]
        for row in (raw.get('data') or {}).get('realtime') or []:
            if not isinstance(row,dict) or row.get('is_ad'): continue
            title=str(row.get('word') or row.get('note') or '').strip()[:150]
            if not title: continue
            rank=len(items)+1
            try: heat=int(row.get('num') or 0)
            except (TypeError,ValueError): heat=0
            if heat>=100000000: label=('%.1f'%(heat/1e8)).rstrip('0').rstrip('.')+'亿'  # 热度换成人看的"亿/万"
            elif heat>=10000: label=('%.1f'%(heat/10000)).rstrip('0').rstrip('.')+'万'
            elif heat>0: label=str(heat)
            else: label='#'+str(rank)
            items.append({'name':title,'content':title+'\n热度：'+(str(heat) if heat else '—'),
                          'url':'https://s.weibo.com/weibo?q='+urllib.parse.quote('#'+title+'#'),
                          'time':0,'source':name,'date_label':label[:20]})
            if len(items)>=limit: break
        return items
    text=news_get(src['url'],root)
    if kind=='rss': return parse_rss(text,name,limit)
    if kind=='html': return parse_html(text,name,src['item_re'],src.get('base',''),limit,src.get('time_re'),now_fn)
    if kind=='github': return parse_github(text,name,limit,now_fn)
    return []


def fetch_news(store,root,ai_only=True,now_fn=None,log=None):
    # 把所有开启的源抓一遍，合并去重后按时间倒序返回；ai_only 保留但不再用（热点全量）
    config=store.read()
    settings=config.get('settings',{})
    merged=[]; errors=[]; ok=0
    def info(*args):
        if log: log.info(*args)  # 不传 log 就静默，方便测试直接调用
    for src in NEWS_SOURCES:
        if not settings.get('news_'+src['key'],True): continue  # 关掉的源不抓
        try:
            items=fetch_source(src,root,now_fn)
            if items: ok+=1
            merged.extend(items)
            info('NEWS_SRC %s=%s',src['name'],len(items))
        except Exception as error:
            errors.append(src['name']+'：'+type(error).__name__)
            info('NEWS_SRC_FAIL %s %s',src['name'],error)
    # 去重：链接（去掉 ?# 参数和末尾斜杠）或标题（去空白取前 30 字）重复只留一条
    seen_url=set(); seen_title=set(); uniq=[]
    for item in merged:
        url_key=re.sub(r'[?#].*$','',item.get('url') or '').rstrip('/').lower()
        title_key=re.sub(r'\s+','',item.get('name') or '')[:30].lower()
        if not title_key or url_key in seen_url or title_key in seen_title: continue
        seen_url.add(url_key); seen_title.add(title_key); uniq.append(item)
    # 排序：有发布时间的排前面且新的在前；无时间的榜单（time=0）排后面
    uniq.sort(key=lambda row:(1 if int(row.get('time') or 0) else 0,int(row.get('time') or 0)),reverse=True)
    info('NEWS_MERGE raw=%s uniq=%s sources_ok=%s',len(merged),len(uniq),ok)
    if uniq: return uniq
    if errors: raise ValueError('资讯获取失败（'+'，'.join(errors)+'）')
    return []


def place_github(items):
    # 榜单源没有发布时间，按时间排会全沉底；这里把它们均匀穿插进新闻里
    if GITHUB_PLACE=='bottom': return items
    board=[item for item in items if item.get('source') in BOARD_SOURCES]
    news=[item for item in items if item.get('source') not in BOARD_SOURCES]
    if not board or not news: return items
    if GITHUB_PLACE=='top': return board+news
    mixed=[]; queues={name:[] for name in BOARD_SOURCES}
    for item in board: queues[item.get('source')].append(item)
    while any(queues.values()):
        for name in BOARD_SOURCES:  # 两个榜单交替取，避免开头全是同一个源
            if queues[name]: mixed.append(queues[name].pop(0))
    step=max(1,len(news)//len(mixed))   # 每隔多少条新闻插一条榜单
    out=[]; index=0
    for order,item in enumerate(news):
        out.append(item)
        if index<len(mixed) and (order+1)%step==0:
            out.append(mixed[index]); index+=1
    out.extend(mixed[index:])
    return out
