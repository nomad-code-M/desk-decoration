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
# 榜单型源没有发布时间，靠时间排会沉底；想让某个榜单不参与穿插（沉到列表最后），删掉名字即可
BOARD_SOURCES=('微博热搜','GitHub中文')  
