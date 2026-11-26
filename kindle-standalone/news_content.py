import math                          # 给 merge_news_history 里的 math.isfinite 用
from news_sources import NEWS_LABELS # 给 enabled_news 用；从 news_sources 取，不是 store

NEWS_LIMIT=300        # 资讯数量上限
NEWS_MAX_AGE=48*3600  # 资讯保留期限

def news_items(value):
    if not isinstance(value,list): return []
    return [item for item in value if isinstance(item,dict) and isinstance(item.get('name'),str) and item['name'].strip()][:NEWS_LIMIT]

def enabled_news(config,items):
    settings=config.get('settings') or {}
    # 每个源一个开关；source 不在表里的（比如以后新加的源还没登记）默认显示，不会被误藏
    sources={label:settings.get(key,True) for key,label in NEWS_LABELS}
    return [item for item in items if sources.get(item.get('source'),True)]

def merge_news_history(previous,incoming=(),current=None,fallback=None,now_fn=None):
    """Bound history by publication age; unknown dates expire from first seen."""
    if now_fn is None:
        from datetime import datetime,timezone,timedelta
        now_fn=lambda: datetime.now(timezone(timedelta(hours=8)))
    stamp=(current or now_fn()).timestamp()  
    def timestamp(value):
        try:
            number=float(value)
            return number if math.isfinite(number) and 0<number<=stamp+300 else None
        except (TypeError,ValueError,OverflowError): return None
    fallback=timestamp(fallback) or stamp
    unique={}
    for raw in news_items(previous)+news_items(list(incoming)):
        name=raw['name'][:2000]
        url=str(raw.get('url') or '')[:2048]
        source=str(raw.get('source') or '')[:60]
        key=url or (source,name)
        old=unique.get(key,{})
        seen=timestamp(old.get('seen_at')) or timestamp(raw.get('seen_at')) or fallback
        published=timestamp(raw.get('time'))
        retained=published or seen
        if retained<stamp-NEWS_MAX_AGE: continue
        item=dict(name=name,url=url,source=source,time=int(published or 0),seen_at=seen)
        content=str(raw.get('content') or old.get('content') or '')
        if content: item['content']=content[:12000]+('…（更多内容请用手机查看原文）' if len(content)>12000 else '')
        # GitHub 没有发布时间的内容，用换算好的具体日期（11/12、23年）当时间显示
        label=str(raw.get('date_label') or old.get('date_label') or '')
        if label: item['date_label']=label[:20]
        unique[key]=item
    return sorted(unique.values(),key=lambda v:v['time'] or v['seen_at'],reverse=True)[:NEWS_LIMIT]