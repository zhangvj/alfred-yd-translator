"""拼音组词检测：识别「输入法组词中间态」，避免对未上屏的拼音发起翻译。

背景：Alfred 不向 Script Filter 传递「IME 正在组词」状态，拼音打字过程中的
每个中间文本（裸拼音 `nihao`、已上屏+组词混合 `你好shijie`）都会被当成最终
查询触发一次真实 API 调用——这是中译英场景请求频率远高于英文输入、频繁触发
有道 411「访问频率受限」的主要根因。

判定思路（保守优先，宁可漏判也不误伤正常查询）：
  A. 混合态：含汉字，且最后一个汉字之后是一个「可完整切分为合法拼音音节」
     的小写拉丁串（长度 >=2）。如 `你好shijie`（shi+jie ✓）；
     `苹果iphone` 中 `iphone` 无法完整切分 → 放行不拦截。
  B. 纯拼音态：不含汉字的纯小写单词（无空格），可完整切分出 **>=2** 个合法
     拼音音节。如 `nihao`、`shijie`；`hello` 切分失败放行；`ma`/`shi` 单音节
     放行（避免误伤短查询）。
  其它一律放行：含大写字母/数字/标点（`你好OK`、`USER_NAME`、`iPhone`）、
  含空格的多词英文、假名/谚文等。

切分用动态规划（音节最长 6 字符，如 zhuang），需整串切分成功才算拼音。

v1.3.0 起判定分两级：
  is_composition     —— 硬判定（混合态 / 多音节纯拼音），命中即组词中间态；
  is_pinyin_suspect  —— 软判定（单音节、可延展前缀），命中只延迟 1s 重跑，
                        合法英文词（he/she/me/can 等）的误伤代价仅 +1s 延迟。
误伤时的强制出口：查询末尾加 `.`（由 yd.py 处理）；环境变量 `yd_pinyin_guard=0`
可整体关闭（见 config.py / README）。
"""
import re

from .detect import has_han

# 合法拼音音节表（含 IME 惯用的 nv/nve/lv/lve 写法，不含声调）
_SYLLABLE_TEXT = """
a o e ai ei ao ou an en ang eng er yo
yi ya ye yao you yan yin yang ying yong yu yue yuan yun
wu wa wo wai wei wan wen wang weng
ba bo bai bei bao ban ben bang beng bi bie biao bian bin bing bu
pa po pai pei pao pou pan pen pang peng pi pie piao pian pin ping pu
ma mo me mai mei mao mou man men mang meng mi mie miao miu mian min ming mu
fa fo fei fou fan fen fang feng fu
da de dai dei dao dou dan den dang deng dong di dia die diao diu dian ding du duo dui duan dun
ta te tai tao tou tan tang teng tong ti tie tiao tian ting tu tuo tui tuan tun
na ne nai nei nao nou nan nen nang neng nong ni nie niao niu nian nin niang ning nu nuo nuan nv nve
la le lai lei lao lou lan lang leng long li lia lie liao liu lian lin liang ling lu luo luan lun lv lve
ga ge gai gei gao gou gan gen gang geng gong gu gua guo guai gui guan gun guang
ka ke kai kou kan ken kang keng kong ku kua kuo kuai kui kuan kun kuang
ha he hai hei hao hou han hen hang heng hong hu hua huo huai hui huan hun huang
ji jia jie jiao jiu jian jin jiang jing jiong ju jue juan jun
qi qia qie qiao qiu qian qin qiang qing qiong qu que quan qun
xi xia xie xiao xiu xian xin xiang xing xiong xu xue xuan xun
zha zhe zhi zhai zhei zhao zhou zhan zhen zhang zheng zhong zhu zhua zhuo zhuai zhui zhuan zhun zhuang
cha che chi chai chao chou chan chen chang cheng chong chu chua chuo chuai chui chuan chun chuang
sha she shi shai shei shao shou shan shen shang sheng shu shua shuo shuai shui shuan shun shuang
re ri rao rou ran ren rang reng rong ru rua ruo rui ruan run
za ze zi zai zei zao zou zan zen zang zeng zong zu zuo zui zuan zun
ca ce ci cai cao cou can cen cang ceng cong cu cuo cui cuan cun
sa se si sai sao sou san sen sang seng song su suo sui suan sun
"""

SYLLABLES = frozenset(_SYLLABLE_TEXT.split())
_MAX_SYLLABLE_LEN = 6  # zhuang / chuang / shuang

# 仅 小写字母 / 空白 / 汉字 允许进入判定；其余（大写、数字、标点）放行
_ALLOWED_RE = re.compile(r"^[\sa-z\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]+$")
_HAN_TAIL_RE = re.compile(
    r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]([a-z]*)$"
)
_PURE_LOWER_RE = re.compile(r"^[a-z]+$")


def _parse_stats(text):
    """动态规划切分拼音。返回 (可否整串切分, 最少音节数)。

    用最少音节数而非最多：`zhuang`（装）、`xian`（先）是单音节，但可被
    过度切分为 zhu+ang / xi+an，按最多音节会误判成组词态。
    """
    n = len(text)
    if n == 0:
        return False, 0
    reachable = [False] * (n + 1)   # 前 i 个字符可被完整切分
    counts = [n + 1] * (n + 1)      # 对应的最少音节数
    reachable[0] = True
    counts[0] = 0
    for i in range(1, n + 1):
        for j in range(max(0, i - _MAX_SYLLABLE_LEN), i):
            if reachable[j] and text[j:i] in SYLLABLES:
                reachable[i] = True
                counts[i] = min(counts[i], counts[j] + 1)
    if not reachable[n]:
        return False, 0
    return True, counts[n]


def is_composition(query):
    """判断查询是否疑似「输入法组词中间态」（详见模块 docstring）。"""
    text = (query or "").strip()
    if not text or not _ALLOWED_RE.match(text):
        return False

    if has_han(text):
        # 混合态：最后一个汉字之后的尾巴必须全是小写字母、可完整切分为
        # 拼音、且长度 >=2（`你好shijie` ✓；`你好a` 太短放行）
        match = _HAN_TAIL_RE.search(text)
        tail = match.group(1) if match else ""
        if len(tail) < 2 or not _PURE_LOWER_RE.match(tail):
            return False
        ok, _ = _parse_stats(tail)
        return ok

    # 纯拼音态：无空格的纯小写单词，切出 >=2 个合法音节
    if not _PURE_LOWER_RE.match(text) or " " in text:
        return False
    ok, count = _parse_stats(text)
    return ok and count >= 2


_PREFIX_TABLE = None


def _syllable_prefixes():
    """所有合法音节的全部真前缀（惰性构建，用于「补全后可成拼音」判定）。"""
    global _PREFIX_TABLE
    if _PREFIX_TABLE is None:
        table = set()
        for syl in SYLLABLES:
            for i in range(1, len(syl)):
                table.add(syl[:i])
        _PREFIX_TABLE = table
    return _PREFIX_TABLE


def _extendable(text):
    """补全字母后能否成为合法拼音：若干完整音节 + 剩余是某音节的真前缀。

    `nih` = ni + h（h 是 hao/hei… 的前缀）✓；`shij` = shi + j ✓；
    `abc`（a + bc，bc 非任何音节前缀）✗；`xyz` ✗。
    """
    n = len(text)
    reachable = [False] * (n + 1)   # 前 i 个字符可被完整切分为音节
    reachable[0] = True
    for i in range(1, n + 1):
        for j in range(max(0, i - _MAX_SYLLABLE_LEN), i):
            if reachable[j] and text[j:i] in SYLLABLES:
                reachable[i] = True
                break
    prefixes = _syllable_prefixes()
    return any(reachable[i] and text[i:] in prefixes for i in range(n + 1))


def is_pinyin_suspect(query):
    """疑似拼音组词的**软判定**：命中后延后翻译（rerun），而非拒绝。

    硬拦截会让 `he` / `she` / `me` / `can` 等合法英文词无法翻译，改为
    「疑似 → 延迟 1s 重跑」——误伤代价仅 +1s 延迟，而组词中间态会被
    后续输入取代，零调用。

    规则：
    - 纯小写单词可完整切分 >=1 个音节且长度 >=2：`da` / `ni` / `nihao`；
    - 不可完整切分、但补全字母后可成为拼音且长度 >=3：`nih` / `shij`。
    含大写/数字/标点/空格/汉字 → False（汉字混合态由 is_composition 处理）。
    """
    text = (query or "").strip()
    if not text or not _PURE_LOWER_RE.match(text):
        return False
    ok, _ = _parse_stats(text)
    if ok:
        return len(text) >= 2
    return len(text) >= 3 and _extendable(text)
