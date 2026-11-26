# 绘图原语（Image / font / Draw 等）仍在 renderer，按函数运行时取用，避免导入环。
from datetime import datetime

from news_sources import NEWS_LABELS

# 各来源的开关名与显示名来自 news_sources（唯一配置源）
# NEWS_KEYS 供 app.py 判断「改了来源设置要不要立刻重抓」
NEWS_KEYS=tuple(key for key,_ in NEWS_LABELS)
# 来源开关页每行的点击区域：行高按源数量自适应，加源也不会挤出屏幕
_SOURCE_TOP=112
_SOURCE_ROW=min(86,(700-_SOURCE_TOP)//max(1,len(NEWS_LABELS)))
SOURCE_ROWS=[(30,_SOURCE_TOP+i*_SOURCE_ROW,570,_SOURCE_TOP+(i+1)*_SOURCE_ROW-8) for i in range(len(NEWS_LABELS))]
CAROUSEL_STEPS=(15,30,45,60,90,120) # 首页轮播秒数（手机后台可填 5-300 任意整数）
HOME_NEWS_PER_PAGE=6                # 首页资讯区一屏显示几条（同时也是轮播的翻页步长）


def _now(now_fn=None):
    # 取当前时间：注入了时钟就用注入的，否则借 renderer 的 now，保持全项目同一时钟
    return now_fn() if now_fn else __import__('renderer').now()


def fmt_news_time(value,current,time_format='24'):
    # 列表右列时间：当天显示时分，跨天显示月/日
    import renderer as ui
    try: stamp=int(value)
    except (TypeError,ValueError): return ''
    if stamp<=0: return ''   # 0 表示没有发布时间（如榜单），不显示假时间
    moment=datetime.fromtimestamp(stamp,ui.TZ)
    if moment.date()==current.date(): return ui.clock_text(moment,time_format)
    return moment.strftime('%m/%d')


def fmt_news_full(value,time_format='24'):
    # 详情页完整时间：月-日 时分；0 表示没有发布时间，不显示假时间
    import renderer as ui
    try: stamp=int(value)
    except (TypeError,ValueError): return ''
    if stamp<=0: return ''
    moment=datetime.fromtimestamp(stamp,ui.TZ)
    return moment.strftime('%m-%d')+' '+ui.clock_text(moment,time_format)


def render_news_detail(item,page,pages,current=None,time_format='24'):
    # 资讯详情页：标题栏 + 正文分页 + 底部按钮；微博热搜用「相关新闻摘要」替代标题
    import renderer as ui
    current=current or _now()
    image=ui.Image.new('L',(600,800),255)
    d=ui.ImageDraw.Draw(image)
    weibo=item.get('source')=='微博热搜'
    d.text((30,25),'微博热搜' if weibo else 'AI 金融资讯',font=ui.font(20,True),fill=0,anchor='lt')
    when=fmt_news_full(item.get('time'),time_format)
    meta=('加载中' if item.get('detail_loading') else '相关新闻摘要') if weibo else (item.get('source') or '')+((' · '+when) if when else '')
    d.text((502 if weibo else 570,28),ui.fit_text(d,meta,14,300 if weibo else 360),font=ui.font(14),fill=80,anchor='rt')
    if weibo: ui.action_icon(d,'refresh',551,36,26,160 if item.get('detail_loading') else 0)
    d.line((30,58,570,58),fill=0,width=2)
    total=max(1,len(pages))
    page=max(0,min(page,total-1))
    yy=84
    for line in pages[page]:
        d.text((30,yy),line,font=ui.font(24),fill=0,anchor='lt'); yy+=38
    if total>1:
        d.text((570,700),f'第 {page+1} / {total} 页',font=ui.font(14),fill=110,anchor='rt')
    ui._draw_buttons(d,('返回','上一页' if page>0 else '','下一页' if page<total-1 else ''))
    return image


def news_brief(item):
    # 列表里那句「这条到底是干什么的」的说明：和标题重复就不显示，省一行给别的条目
    content=' '.join(str(item.get('content') or '').split())
    title=' '.join(str(item.get('name') or '').split())
    if not content or content==title: return ''
    if title and content.startswith(title[:10]): return ''
    return content


def render_news_history(items,page=0,refreshing=False,time_format='24',title='AI 金融资讯',history=True):
    # 资讯历史/榜单列表页：每条显示时间、来源、标题和一句简介，底部分页
    import renderer as ui
    selected,page,total=ui.page_slice(items,page)
    subtitle='正在更新资讯…' if refreshing else ('最近 48 小时' if history else '当前榜单')+f' · 共 {len(items)} 条 · 点条目查看'
    image,d=ui.section_frame(title+(' · 历史' if history else ' · 全部'),subtitle)
    if not selected: d.text((30,155),'最近 48 小时暂无已缓存资讯。',font=ui.font(22),fill=0,anchor='lt')
    for i,item in enumerate(selected):
        y=125+i*85
        meta=fmt_news_full(item.get('time'),time_format) or '获取于 '+fmt_news_full(item.get('seen_at'),time_format)
        d.text((30,y),ui.fit_text(d,(meta+' · ' if meta else '')+item.get('source',''),16,540),font=ui.font(16),fill=75,anchor='lt')
        title_lines=ui.wrap_lines(' '.join(item['name'].split()),20,540)
        brief=news_brief(item)
        if brief:
            # 有简介时标题只占一行，第二行放简介，这样一眼就能看出这条讲什么
            title_lines=title_lines[:1]
            d.text((30,y+48),ui.fit_text(d,brief,16,540),font=ui.font(16),fill=90,anchor='lt')
        for j,line in enumerate(title_lines[:2]):
            d.text((30,y+25+j*24),line,font=ui.font(20),fill=0,anchor='lt')
        d.line((30,y+80,570,y+80),fill=205,width=1)
    ui.pager(d,page,total)
    ui._draw_buttons(d,('返回','',''))
    return image


def render_source_picker(config):
    # 各新闻源逐个开关：关掉的源既不抓取也不上首页，剩下的自动重新排
    import renderer as ui
    settings=config.get('settings') or {}
    image,d=ui.section_frame('资讯来源','轻触开启或关闭 · 全部关闭则只看缓存')
    for index,(key,label) in enumerate(NEWS_LABELS):
        box=SOURCE_ROWS[index]; x0,y0,x1,y1=box; middle=(y0+y1)//2
        on=bool(settings.get(key,True))
        d.rounded_rectangle(box,radius=6,outline=0 if on else 140,width=2 if on else 1)
        d.text((48,middle),label,font=ui.font(21,True),fill=0 if on else 110,anchor='lm')
        d.text((500,middle),'开启' if on else '关闭',font=ui.font(17),fill=70 if on else 120,anchor='rm')
        ui.checkbox(d,520,middle-14,28,on)
    # 提示文字自动落在最后一行下面，行数多的时候不挤
    tip_y=_SOURCE_TOP+len(NEWS_LABELS)*_SOURCE_ROW+6
    if tip_y<716: d.text((300,tip_y),'改动会在下一次抓取时生效',font=ui.font(15),fill=90,anchor='mt')
    ui.icon_button(d,(30,728,202,777),'back')
    ui.icon_button(d,(214,728,386,777),'phone')
    return image
