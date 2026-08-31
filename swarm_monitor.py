#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PokeMMO Alphapedia Swarm 监控推送脚本
=====================================
监控 https://alpha.pokemmotools.org/ 首页上公布的 Swarm（群聚宝可梦），
发现「新出现的 swarm」时，立刻推送到手机。

零依赖：只用 Python 标准库，Windows / Linux / macOS 都能跑。

━━━━ 推送通道（通过环境变量配置，可同时启用多个）━━━━
  NTFY_TOPIC           ntfy.sh 主题名（安卓推荐：手机装 ntfy App，订阅同名主题）
  NTFY_TOKEN           可选：ntfy 访问令牌（公共主题可不填）
  PUSHPLUS_TOKEN       PushPlus 令牌（微信推送，国内稳定）
  SERVERCHAN_SENDKEY   Server酱 SendKey（微信推送）
  TELEGRAM_BOT_TOKEN   Telegram Bot Token（配合 TELEGRAM_CHAT_ID）
  TELEGRAM_CHAT_ID     Telegram 接收通知的 chat id
  BARK_URL             Bark 完整地址，如 https://api.day.app/你的Key （iPhone）

━━━━ 可选过滤 ━━━━
  FILTER_REGION        只提醒这些地区，逗号分隔，如 "Kanto,Johto"
  FILTER_POKEMON       只提醒这些宝可梦，逗号分隔，如 "Gible,Dratini"
  NOTIFY_AGE_MAX       报告后多少秒内算「新 swarm」，默认 600（10 分钟）

━━━━ 用法 ━━━━
  python swarm_monitor.py --once            # 只检查一次（GitHub Actions 定时任务用）
  python swarm_monitor.py --loop            # 每 60 秒循环检查（自己电脑常开用）
  TEST_NOTIFY=1 python swarm_monitor.py --once   # 发一条测试通知，验证通道
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

SITE_URL = "https://alpha.pokemmotools.org/"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
USER_AGENT = "Mozilla/5.0 (compatible; SwarmMonitor/1.0; +https://github.com/)"
DEFAULT_AGE_MAX = 600          # 报告后 10 分钟内算新
SWARM_LIFETIME = 25 * 60       # swarm 一般持续约 25 分钟
STATE_MAX_ENTRIES = 1000       # 去重记录最多保留条数（防 state.json 无限膨胀）


# ════════════════ 抓取与解析 ════════════════

def http_get(url, timeout=20, retries=3):
    """带重试的 GET，返回文本。"""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                return data.decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    print(f"[错误] 抓取失败 {url}: {last_err}")
    return None


def parse_swarms(html):
    """从首页 HTML 中解析所有 swarm 卡片。

    卡片结构（服务端渲染，字段稳定）：
      <article class="swarm-region-card">
        <p class="swarm-card-region" data-region="Kanto">Kanto</p>
        <a href="/pokedex/479"><span data-pokemon="Rotom">Rotom</span></a>
        <a href="/route/kanto/power-plant"><span data-location="Power Plant">Power Plant</span></a>
        <p class="swarm-card-age" data-timedelta="9808">2 hours 43 minutes ago</p>
      </article>
    """
    swarms = []
    cards = re.findall(r'<article class="swarm-region-card">(.*?)</article>', html, re.S)
    for card in cards:
        region = re.search(r'data-region="([^"]*)"', card)
        pokemon = re.search(r'data-pokemon="([^"]*)"', card)
        location = re.search(r'data-location="([^"]*)"', card)
        timedelta = re.search(r'data-timedelta="(\d+)"', card)
        if not (region and pokemon and location and timedelta):
            continue
        swarms.append({
            "region": region.group(1).strip(),
            "pokemon": pokemon.group(1).strip(),
            "location": location.group(1).strip(),
            "age_s": int(timedelta.group(1)),
        })
    return swarms


# ════════════════ 去重状态 ════════════════

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("notified"), dict):
                return data
    except Exception:  # noqa: BLE001
        pass
    return {"notified": {}}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        print(f"[警告] 无法保存 state.json: {e}")


def make_signature(swarm):
    """同一地点同一宝可梦，在同一小时内只提醒一次（去重）。

    用「报告时刻所在小时」做签名：报告时间 = 当前时间 - 已出现秒数。
    """
    report_epoch_hour = int((time.time() - swarm["age_s"]) // 3600)
    return f'{swarm["region"]}|{swarm["pokemon"]}|{swarm["location"]}|{report_epoch_hour}'


# ════════════════ 中英文翻译表 ════════════════
# 通知消息默认显示「中文名（英文名）」。以下字典覆盖了 PokeMMO
# 当前全部 5 个世代的宝可梦（649 只）、所有地区与常见地点。
# 想补充自定义译名，直接往对应字典里加一行即可。

REGION_ZH = {
    "Kanto": "关都", "Johto": "城都", "Hoenn": "丰缘", "Sinnoh": "神奥",
    "Unova": "合众", "Kalos": "卡洛斯", "Alola": "阿罗拉", "Galar": "伽勒尔",
    "Paldea": "帕底亚", "Hisui": "洗翠", "Kitakami": "北上乡", "Blueberry": "蓝莓学园",
    "Fiore": "菲蕾", "Orre": "欧雷", "Ransei": "乱世", "Ferrum": "菲鲁姆",
    "Lental": "兰塔尔", "Crown Tundra": "王冠雪原", "Isle of Armor": "铠岛",
}

LOCATION_ZH = {
    # 关都
    "Pallet Town": "真新镇", "Viridian City": "常青市", "Pewter City": "深灰市",
    "Cerulean City": "华蓝市", "Vermilion City": "枯叶市", "Lavender Town": "紫苑镇",
    "Celadon City": "彩虹市", "Fuchsia City": "浅红市", "Saffron City": "金黄市",
    "Cinnabar Island": "红莲岛", "Route 1": "一号道路", "Route 2": "二号道路",
    "Route 3": "三号道路", "Route 4": "四号道路", "Route 5": "五号道路",
    "Route 6": "六号道路", "Route 7": "七号道路", "Route 8": "八号道路",
    "Route 9": "九号道路", "Route 10": "十号道路", "Route 11": "十一号道路",
    "Route 12": "十二号道路", "Route 13": "十三号道路", "Route 14": "十四号道路",
    "Route 15": "十五号道路", "Route 16": "十六号道路", "Route 17": "十七号道路",
    "Route 18": "十八号道路", "Route 19": "十九号道路", "Route 20": "二十号道路",
    "Route 21": "二十一号道路", "Route 22": "二十二号道路", "Route 23": "二十三号道路",
    "Route 24": "二十四号道路", "Route 25": "二十五号道路", "Viridian Forest": "常青森林",
    "Mt. Moon": "月见山", "Rock Tunnel": "岩山隧道", "Power Plant": "发电厂",
    "Pokémon Tower": "宝可梦塔", "Silph Co.": "西尔佛公司", "Safari Zone": "狩猎地带",
    "Seafoam Islands": "双叶岛", "Victory Road": "冠军之路", "Cerulean Cave": "华蓝洞窟",
    "Indigo Plateau": "石英高原", "Pokémon Mansion": "宝可梦公馆", "Diglett's Cave": "地鼠洞",
    # 城都
    "New Bark Town": "若叶镇", "Cherrygrove City": "吉花市", "Violet City": "桔梗市",
    "Azalea Town": "桧皮镇", "Goldenrod City": "满金市", "Ecruteak City": "圆朱市",
    "Olivine City": "浅葱市", "Cianwood City": "湛蓝市", "Mahogany Town": "卡吉镇",
    "Blackthorn City": "烟墨市", "Mt. Mortar": "擂钵山", "Union Cave": "连接洞穴",
    "Ilex Forest": "桐树林", "Slowpoke Well": "呆呆兽之井", "Burned Tower": "烧焦塔",
    "Whirl Islands": "漩涡列岛", "Lake of Rage": "愤怒之湖", "Ice Path": "冰之道",
    "Dragon's Den": "龙之洞穴", "Dark Cave": "黑暗洞窟", "Ruins of Alph": "阿尔宙斯遗迹",
    "National Park": "自然公园", "Radio Tower": "广播塔", "Tin Tower": "铃铛塔",
    # 丰缘
    "Littleroot Town": "未白镇", "Oldale Town": "古辰镇", "Petalburg City": "橙华市",
    "Rustboro City": "卡那兹市", "Dewford Town": "武斗镇", "Slateport City": "凯那市",
    "Mauville City": "紫堇市", "Verdanturf Town": "绿荫镇", "Fallarbor Town": "秋叶镇",
    "Lavaridge Town": "釜炎镇", "Fortree City": "茵郁市", "Lilycove City": "水静市",
    "Mossdeep City": "绿岭市", "Sootopolis City": "琉璃市", "Pacifidlog Town": "暮水镇",
    "Ever Grande City": "彩幽市", "Rusturf Tunnel": "卡绿隧道", "Granite Cave": "石之洞窟",
    "Meteor Falls": "流星瀑布", "Mt. Chimney": "烟囱山", "Fiery Path": "火焰小径",
    "Jagged Pass": "凹凸山道", "New Mauville": "新紫堇", "Mt. Pyre": "送神山",
    "Shoal Cave": "浅滩洞穴", "Cave of Origin": "起源洞穴", "Sky Pillar": "天空之柱",
    "Seafloor Cavern": "海底洞窟", "Battle Frontier": "对战开拓区",
    # 神奥
    "Twinleaf Town": "双叶镇", "Sandgem Town": "真砂镇", "Jubilife City": "祝庆市",
    "Oreburgh City": "黑金市", "Floaroma Town": "花蕊镇", "Eterna City": "百代市",
    "Hearthome City": "缘之市", "Solaceon Town": "索诺镇", "Veilstone City": "帷幕市",
    "Pastoria City": "湿原市", "Celestic Town": "神和镇", "Canalave City": "水脉市",
    "Snowpoint City": "切锋市", "Sunyshore City": "滨海市", "Spear Pillar": "枪之柱",
    "Mt. Coronet": "天冠山", "Oreburgh Mine": "黑金矿场", "Eterna Forest": "百代森林",
    "Great Marsh": "大湿地", "Lost Tower": "迷失塔", "Iron Island": "钢铁岛",
    "Lake Verity": "立志湖", "Lake Valor": "睿智湖", "Lake Acuity": "心齐湖",
    "Distortion World": "毁坏的世界", "Old Chateau": "老宅邸", "Fuego Ironworks": "弗埃罗铁工厂",
    # 合众
    "Nuvema Town": "鹿子镇", "Accumula Town": "唐草镇", "Striaton City": "三曜市",
    "Nacrene City": "七宝市", "Castelia City": "飞云市", "Nimbasa City": "雷文市",
    "Driftveil City": "帆巴市", "Mistralton City": "吹寄市", "Icirrus City": "雪花市",
    "Opelucid City": "双龙市", "Lacunosa Town": "雪华市", "Undella Town": "小波镇",
    "Anville Town": "铁轮镇", "Aspertia City": "桧扇市", "Floccesy Town": "算木镇",
    "Virbank City": "立涌市", "Lentimas Town": "山路镇", "Humilau City": "青海波市",
    "Twist Mountain": "螺旋山", "Dragonspiral Tower": "龙螺旋之塔", "Chargestone Cave": "电石洞穴",
    "Relic Castle": "古代城堡", "Desert Resort": "荒野名胜区", "Pinwheel Forest": "风车森林",
    "Giant Chasm": "巨人洞窟", "Celestial Tower": "天堂之塔", "N's Castle": "N 的城堡",
    "Mistralton Cave": "吹寄洞穴", "Wellspring Cave": "地下水脉之穴", "Victory Road (Unova)": "冠军之路",
    "Reversal Mountain": "反转山", "Pledge Grove": "誓约之森", "Abundant Shrine": "丰饶之祠",
}

POKEMON_ZH = {
    # ── 关都（Gen 1，001-151）──
    "Bulbasaur": "妙蛙种子", "Ivysaur": "妙蛙草", "Venusaur": "妙蛙花",
    "Charmander": "小火龙", "Charmeleon": "火恐龙", "Charizard": "喷火龙",
    "Squirtle": "杰尼龟", "Wartortle": "卡咪龟", "Blastoise": "水箭龟",
    "Caterpie": "绿毛虫", "Metapod": "铁甲蛹", "Butterfree": "巴大蝶",
    "Weedle": "独角虫", "Kakuna": "铁壳蛹", "Beedrill": "大针蜂",
    "Pidgey": "波波", "Pidgeotto": "比比鸟", "Pidgeot": "大比鸟",
    "Rattata": "小拉达", "Raticate": "拉达", "Spearow": "烈雀",
    "Fearow": "大嘴雀", "Ekans": "阿柏蛇", "Arbok": "阿柏怪",
    "Pikachu": "皮卡丘", "Raichu": "雷丘", "Sandshrew": "穿山鼠",
    "Sandslash": "穿山王", "Nidoran♀": "尼多兰", "Nidorina": "尼多娜",
    "Nidoqueen": "尼多后", "Nidoran♂": "尼多朗", "Nidorino": "尼多力诺",
    "Nidoking": "尼多王", "Clefairy": "皮皮", "Clefable": "皮可西",
    "Vulpix": "六尾", "Ninetales": "九尾", "Jigglypuff": "胖丁",
    "Wigglytuff": "胖可丁", "Zubat": "超音蝠", "Golbat": "大嘴蝠",
    "Oddish": "走路草", "Gloom": "臭臭花", "Vileplume": "霸王花",
    "Paras": "派拉斯", "Parasect": "派拉斯特", "Venonat": "毛球",
    "Venomoth": "摩鲁蛾", "Diglett": "地鼠", "Dugtrio": "三地鼠",
    "Meowth": "喵喵", "Persian": "猫老大", "Psyduck": "可达鸭",
    "Golduck": "哥达鸭", "Mankey": "猴怪", "Primeape": "火爆猴",
    "Growlithe": "卡蒂狗", "Arcanine": "风速狗", "Poliwag": "蚊香蝌蚪",
    "Poliwhirl": "蚊香君", "Poliwrath": "蚊香泳士", "Abra": "凯西",
    "Kadabra": "勇基拉", "Alakazam": "胡地", "Machop": "腕力",
    "Machoke": "豪力", "Machamp": "怪力", "Bellsprout": "喇叭芽",
    "Weepinbell": "口呆花", "Victreebel": "大食花", "Tentacool": "玛瑙水母",
    "Tentacruel": "毒刺水母", "Geodude": "小拳石", "Graveler": "隆隆石",
    "Golem": "隆隆岩", "Ponyta": "小火马", "Rapidash": "烈焰马",
    "Slowpoke": "呆呆兽", "Slowbro": "呆壳兽", "Magnemite": "小磁怪",
    "Magneton": "三合一磁怪", "Farfetch'd": "大葱鸭", "Doduo": "嘟嘟",
    "Dodrio": "嘟嘟利", "Seel": "小海狮", "Dewgong": "白海狮",
    "Grimer": "臭泥", "Muk": "臭臭泥", "Shellder": "大舌贝",
    "Cloyster": "刺甲贝", "Gastly": "鬼斯", "Haunter": "鬼斯通",
    "Gengar": "耿鬼", "Onix": "大岩蛇", "Drowzee": "催眠貘",
    "Hypno": "引梦貘人", "Krabby": "大钳蟹", "Kingler": "巨钳蟹",
    "Voltorb": "霹雳电球", "Electrode": "顽皮雷弹", "Exeggcute": "蛋蛋",
    "Exeggutor": "椰蛋树", "Cubone": "卡拉卡拉", "Marowak": "嘎啦嘎啦",
    "Hitmonlee": "飞腿郎", "Hitmonchan": "快拳郎", "Lickitung": "大舌头",
    "Koffing": "瓦斯弹", "Weezing": "双弹瓦斯", "Rhyhorn": "独角犀牛",
    "Rhydon": "钻角犀兽", "Chansey": "吉利蛋", "Tangela": "蔓藤怪",
    "Kangaskhan": "袋兽", "Horsea": "墨海马", "Seadra": "海刺龙",
    "Goldeen": "角金鱼", "Seaking": "金鱼王", "Staryu": "海星星",
    "Starmie": "宝石海星", "Mr. Mime": "魔墙人偶", "Scyther": "飞天螳螂",
    "Jynx": "迷唇姐", "Electabuzz": "电击兽", "Magmar": "鸭嘴火兽",
    "Pinsir": "凯罗斯", "Tauros": "肯泰罗", "Magikarp": "鲤鱼王",
    "Gyarados": "暴鲤龙", "Lapras": "拉普拉斯", "Ditto": "百变怪",
    "Eevee": "伊布", "Vaporeon": "水伊布", "Jolteon": "雷伊布",
    "Flareon": "火伊布", "Porygon": "多边兽", "Omanyte": "菊石兽",
    "Omastar": "多刺菊石兽", "Kabuto": "化石盔", "Kabutops": "镰刀盔",
    "Aerodactyl": "化石翼龙", "Snorlax": "卡比兽", "Articuno": "急冻鸟",
    "Zapdos": "闪电鸟", "Moltres": "火焰鸟", "Dratini": "迷你龙",
    "Dragonair": "哈克龙", "Dragonite": "快龙", "Mewtwo": "超梦",
    "Mew": "梦幻",
    # ── 城都（Gen 2，152-251）──
    "Chikorita": "菊草叶", "Bayleef": "月桂叶", "Meganium": "大竺葵",
    "Cyndaquil": "火球鼠", "Quilava": "火岩鼠", "Typhlosion": "火爆兽",
    "Totodile": "小锯鳄", "Croconaw": "蓝鳄", "Feraligatr": "大力鳄",
    "Sentret": "尾立", "Furret": "大尾立", "Hoothoot": "咕咕",
    "Noctowl": "猫头夜鹰", "Ledyba": "芭瓢虫", "Ledian": "安瓢虫",
    "Spinarak": "圆丝蛛", "Ariados": "阿利多斯", "Crobat": "叉字蝠",
    "Chinchou": "灯笼鱼", "Lanturn": "电灯怪", "Pichu": "皮丘",
    "Cleffa": "皮宝宝", "Igglybuff": "宝宝丁", "Togepi": "波克比",
    "Togetic": "波克基古", "Natu": "天然雀", "Xatu": "天然鸟",
    "Mareep": "咩利羊", "Flaaffy": "茸茸羊", "Ampharos": "电龙",
    "Bellossom": "美丽花", "Marill": "玛力露", "Azumarill": "玛力露丽",
    "Sudowoodo": "树才怪", "Politoed": "蚊香蛙皇", "Hoppip": "毽子草",
    "Skiploom": "毽子花", "Jumpluff": "毽子棉", "Aipom": "长尾怪手",
    "Sunkern": "向日种子", "Sunflora": "向日花怪", "Yanma": "蜻蜻蜓",
    "Wooper": "乌波", "Quagsire": "沼王", "Espeon": "太阳伊布",
    "Umbreon": "月亮伊布", "Murkrow": "黑暗鸦", "Slowking": "呆呆王",
    "Misdreavus": "梦妖", "Unown": "未知图腾", "Wobbuffet": "果然翁",
    "Girafarig": "麒麟奇", "Pineco": "榛果球", "Forretress": "佛烈托斯",
    "Dunsparce": "土龙弟弟", "Gligar": "天蝎", "Steelix": "大钢蛇",
    "Snubbull": "布鲁", "Granbull": "布鲁皇", "Qwilfish": "千针鱼",
    "Scizor": "巨钳螳螂", "Shuckle": "壶壶", "Heracross": "赫拉克罗斯",
    "Sneasel": "狃拉", "Teddiursa": "熊宝宝", "Ursaring": "圈圈熊",
    "Slugma": "熔岩虫", "Magcargo": "熔岩蜗牛", "Swinub": "小山猪",
    "Piloswine": "长毛猪", "Corsola": "太阳珊瑚", "Remoraid": "铁炮鱼",
    "Octillery": "章鱼桶", "Delibird": "信使鸟", "Mantine": "巨翅飞鱼",
    "Skarmory": "盔甲鸟", "Houndour": "戴鲁比", "Houndoom": "黑鲁加",
    "Kingdra": "刺龙王", "Phanpy": "小小象", "Donphan": "顿甲",
    "Porygon2": "多边兽Ⅱ", "Stantler": "惊角鹿", "Smeargle": "图图犬",
    "Tyrogue": "无畏小子", "Hitmontop": "战舞郎", "Smoochum": "迷唇娃",
    "Elekid": "电击怪", "Magby": "鸭嘴宝宝", "Miltank": "大奶罐",
    "Blissey": "幸福蛋", "Raikou": "雷公", "Entei": "炎帝",
    "Suicune": "水君", "Larvitar": "幼基拉斯", "Pupitar": "沙基拉斯",
    "Tyranitar": "班基拉斯", "Lugia": "洛奇亚", "Ho-Oh": "凤王",
    "Celebi": "时拉比",
    # ── 丰缘（Gen 3，252-386）──
    "Treecko": "木守宫", "Grovyle": "森林蜥蜴", "Sceptile": "蜥蜴王",
    "Torchic": "火稚鸡", "Combusken": "力壮鸡", "Blaziken": "火焰鸡",
    "Mudkip": "水跃鱼", "Marshtomp": "沼跃鱼", "Swampert": "巨沼怪",
    "Poochyena": "土狼犬", "Mightyena": "大狼犬", "Zigzagoon": "蛇纹熊",
    "Linoone": "直冲熊", "Wurmple": "刺尾虫", "Silcoon": "甲壳茧",
    "Beautifly": "狩猎凤蝶", "Cascoon": "盾甲茧", "Dustox": "毒粉蛾",
    "Lotad": "莲叶童子", "Lombre": "莲帽小童", "Ludicolo": "乐天河童",
    "Seedot": "橡实果", "Nuzleaf": "长鼻叶", "Shiftry": "狡猾天狗",
    "Taillow": "傲骨燕", "Swellow": "大王燕", "Wingull": "长翅鸥",
    "Pelipper": "大嘴鸥", "Ralts": "拉鲁拉丝", "Kirlia": "奇鲁莉安",
    "Gardevoir": "沙奈朵", "Surskit": "溜溜糖球", "Masquerain": "雨翅蛾",
    "Shroomish": "蘑蘑菇", "Breloom": "斗笠菇", "Slakoth": "懒人獭",
    "Vigoroth": "过动猿", "Slaking": "请假王", "Nincada": "土居忍士",
    "Ninjask": "铁面忍者", "Shedinja": "脱壳忍者", "Whismur": "咕妞妞",
    "Loudred": "吼爆弹", "Exploud": "爆音怪", "Makuhita": "幕下力士",
    "Hariyama": "铁掌力士", "Azurill": "露力丽", "Nosepass": "朝北鼻",
    "Skitty": "向尾喵", "Delcatty": "优雅猫", "Sableye": "勾魂眼",
    "Mawile": "大嘴娃", "Aron": "可可多拉", "Lairon": "可多拉",
    "Aggron": "波士可多拉", "Meditite": "玛沙那", "Medicham": "恰雷姆",
    "Electrike": "落雷兽", "Manectric": "雷电兽", "Plusle": "正电拍拍",
    "Minun": "负电拍拍", "Illumise": "电萤虫", "Volbeat": "甜甜萤",
    "Roselia": "毒蔷薇", "Gulpin": "溶食兽", "Swalot": "吞食兽",
    "Carvanha": "利牙鱼", "Sharpedo": "巨牙鲨", "Wailmer": "吼吼鲸",
    "Wailord": "吼鲸王", "Numel": "呆火驼", "Camerupt": "喷火驼",
    "Torkoal": "煤炭龟", "Spoink": "跳跳猪", "Grumpig": "噗噗猪",
    "Spinda": "晃晃斑", "Trapinch": "大颚蚁", "Vibrava": "超音波幼虫",
    "Flygon": "沙漠蜻蜓", "Cacnea": "刺球仙人掌", "Cacturne": "梦歌仙人掌",
    "Swablu": "青绵鸟", "Altaria": "七夕青鸟", "Zangoose": "猫鼬斩",
    "Seviper": "饭匙蛇", "Lunatone": "月石", "Solrock": "太阳岩",
    "Barboach": "泥泥鳅", "Whiscash": "鲶鱼王", "Corphish": "龙虾小兵",
    "Crawdaunt": "铁螯龙虾", "Baltoy": "天秤偶", "Claydol": "念力土偶",
    "Lileep": "触手百合", "Cradily": "摇篮百合", "Anorith": "太古羽虫",
    "Armaldo": "太古盔甲", "Feebas": "丑丑鱼", "Milotic": "美纳斯",
    "Castform": "飘浮泡泡", "Kecleon": "变隐龙", "Shuppet": "怨影娃娃",
    "Banette": "诅咒娃娃", "Duskull": "夜巡灵", "Dusclops": "彷徨夜灵",
    "Tropius": "热带龙", "Chimecho": "风铃铃", "Absol": "阿勃梭鲁",
    "Wynaut": "小果然", "Snorunt": "雪童子", "Glalie": "冰鬼护",
    "Spheal": "海豹球", "Sealeo": "海魔狮", "Walrein": "帝牙海狮",
    "Clamperl": "珍珠贝", "Huntail": "猎斑鱼", "Gorebyss": "樱花鱼",
    "Relicanth": "古空棘鱼", "Luvdisc": "爱心鱼", "Bagon": "宝贝龙",
    "Shelgon": "甲壳龙", "Salamence": "暴飞龙", "Beldum": "铁哑铃",
    "Metang": "金属怪", "Metagross": "巨金怪", "Regirock": "雷吉洛克",
    "Regice": "雷吉艾斯", "Registeel": "雷吉斯奇鲁", "Latias": "拉帝亚斯",
    "Latios": "拉帝欧斯", "Kyogre": "盖欧卡", "Groudon": "固拉多",
    "Rayquaza": "烈空坐", "Jirachi": "基拉祈", "Deoxys": "代欧奇希斯",
    # ── 神奥（Gen 4，387-493）──
    "Turtwig": "草苗龟", "Grotle": "树林龟", "Torterra": "土台龟",
    "Chimchar": "小火焰猴", "Monferno": "猛火猴", "Infernape": "烈焰猴",
    "Piplup": "波加曼", "Prinplup": "波皇子", "Empoleon": "帝王拿波",
    "Starly": "姆克儿", "Staravia": "姆克鸟", "Staraptor": "姆克鹰",
    "Bidoof": "大牙狸", "Bibarel": "大尾狸", "Kricketot": "圆法师",
    "Kricketune": "音箱蟀", "Shinx": "小猫怪", "Luxio": "勒克猫",
    "Luxray": "伦琴猫", "Budew": "含羞苞", "Roserade": "罗丝雷朵",
    "Cranidos": "头盖龙", "Rampardos": "战槌龙", "Shieldon": "盾甲龙",
    "Bastiodon": "护城龙", "Burmy": "结草儿", "Wormadam": "结草贵妇",
    "Mothim": "绅士蛾", "Combee": "三蜜蜂", "Vespiquen": "蜂女王",
    "Pachirisu": "帕奇利兹", "Buizel": "泳圈鼬", "Floatzel": "浮潜鼬",
    "Cherubi": "樱花宝", "Cherrim": "樱花儿", "Shellos": "无壳海兔",
    "Gastrodon": "海兔兽", "Ambipom": "双尾怪手", "Drifloon": "飘飘球",
    "Drifblim": "随风球", "Buneary": "卷卷耳", "Lopunny": "长耳兔",
    "Mismagius": "梦妖魔", "Honchkrow": "乌鸦头头", "Glameow": "魅力喵",
    "Purugly": "东施喵", "Chingling": "铃铛响", "Stunky": "臭鼬噗",
    "Skuntank": "坦克臭鼬", "Bronzor": "铜镜怪", "Bronzong": "青铜钟",
    "Bonsly": "盆才怪", "Mime Jr.": "魔尼尼", "Happiny": "小福蛋",
    "Chatot": "聒噪鸟", "Spiritomb": "花岩怪", "Gible": "圆陆鲨",
    "Gabite": "尖牙陆鲨", "Garchomp": "烈咬陆鲨", "Munchlax": "小卡比兽",
    "Riolu": "利欧路", "Lucario": "路卡利欧", "Hippopotas": "沙河马",
    "Hippowdon": "河马兽", "Skorupi": "钳尾蝎", "Drapion": "龙王蝎",
    "Croagunk": "不良蛙", "Toxicroak": "毒骷蛙", "Carnivine": "尖牙笼",
    "Finneon": "荧光鱼", "Lumineon": "霓虹鱼", "Mantyke": "小球飞鱼",
    "Snover": "雪笠怪", "Abomasnow": "暴雪王", "Weavile": "玛狃拉",
    "Magnezone": "自爆磁怪", "Lickilicky": "大舌舔", "Rhyperior": "超甲狂犀",
    "Tangrowth": "巨蔓藤", "Electivire": "电击魔兽", "Magmortar": "鸭嘴炎兽",
    "Togekiss": "波克基斯", "Yanmega": "远古巨蜓", "Leafeon": "叶伊布",
    "Glaceon": "冰伊布", "Gliscor": "天蝎王", "Mamoswine": "象牙猪",
    "Porygon-Z": "多边兽Z", "Gallade": "艾路雷朵", "Probopass": "大朝北鼻",
    "Dusknoir": "黑夜魔灵", "Froslass": "雪妖女", "Rotom": "洛托姆",
    "Uxie": "由克希", "Mesprit": "艾姆利多", "Azelf": "亚克诺姆",
    "Dialga": "帝牙卢卡", "Palkia": "帕路奇亚", "Heatran": "席多蓝恩",
    "Regigigas": "雷吉奇卡斯", "Giratina": "骑拉帝纳", "Cresselia": "克雷色利亚",
    "Phione": "霏欧纳", "Manaphy": "玛纳霏", "Darkrai": "达克莱伊",
    "Shaymin": "谢米", "Arceus": "阿尔宙斯",
    # ── 合众（Gen 5，494-649）──
    "Victini": "比克提尼", "Snivy": "藤藤蛇", "Servine": "青藤蛇",
    "Serperior": "君主蛇", "Tepig": "暖暖猪", "Pignite": "炒炒猪",
    "Emboar": "炎武王", "Oshawott": "水水獭", "Dewott": "双刃丸",
    "Samurott": "大剑鬼", "Patrat": "探探鼠", "Watchog": "步哨鼠",
    "Lillipup": "小约克", "Herdier": "哈约克", "Stoutland": "长毛狗",
    "Purrloin": "扒手猫", "Liepard": "酷豹", "Pansage": "花椰猴",
    "Simisage": "花椰猿", "Pansear": "爆香猴", "Simisear": "爆香猿",
    "Panpour": "冷水猴", "Simipour": "冷水猿", "Munna": "食梦梦",
    "Musharna": "梦梦蚀", "Pidove": "豆豆鸽", "Tranquill": "咕咕鸽",
    "Unfezant": "高傲雉鸡", "Blitzle": "斑斑马", "Zebstrika": "雷电斑马",
    "Roggenrola": "石丸子", "Boldore": "地幔岩", "Gigalith": "庞岩怪",
    "Woobat": "滚滚蝙蝠", "Swoobat": "心蝙蝠", "Drilbur": "螺钉地鼠",
    "Excadrill": "龙头地鼠", "Audino": "差不多娃娃", "Timburr": "搬运小匠",
    "Gurdurr": "铁骨土人", "Conkeldurr": "修建老匠", "Tympole": "圆蝌蚪",
    "Palpitoad": "蓝蟾蜍", "Seismitoad": "蟾蜍王", "Throh": "投摔鬼",
    "Sawk": "打击鬼", "Sewaddle": "虫宝包", "Swadloon": "宝包茧",
    "Leavanny": "保姆虫", "Venipede": "百足蜈蚣", "Whirlipede": "车轮毬",
    "Scolipede": "蜈蚣王", "Cottonee": "木棉球", "Whimsicott": "风妖精",
    "Petilil": "百合根娃娃", "Lilligant": "裙儿小姐", "Basculin": "野蛮鲈鱼",
    "Sandile": "黑眼鳄", "Krokorok": "混混鳄", "Krookodile": "流氓鳄",
    "Darumaka": "火红不倒翁", "Darmanitan": "达摩狒狒", "Maractus": "沙铃仙人掌",
    "Dwebble": "石居蟹", "Crustle": "巨石蟹", "Scraggy": "滑滑小子",
    "Scrafty": "头巾混混", "Sigilyph": "象征鸟", "Yamask": "哭哭面具",
    "Cofagrigus": "死神棺", "Tirtouga": "原盖海龟", "Carracosta": "肋骨海龟",
    "Archen": "始祖小鸟", "Archeops": "始祖大鸟", "Trubbish": "破破袋",
    "Garbodor": "灰尘山", "Zorua": "索罗亚", "Zoroark": "索罗亚克",
    "Minccino": "泡沫栗鼠", "Cinccino": "奇诺栗鼠", "Gothita": "哥德宝宝",
    "Gothorita": "哥德小童", "Gothitelle": "哥德小姐", "Solosis": "单卵细胞球",
    "Duosion": "双卵细胞球", "Reuniclus": "人造细胞卵", "Ducklett": "鸭宝宝",
    "Swanna": "舞天鹅", "Vanillite": "迷你冰", "Vanillish": "多多冰",
    "Vanilluxe": "双倍多多冰", "Deerling": "四季鹿", "Sawsbuck": "萌芽鹿",
    "Emolga": "电飞鼠", "Karrablast": "盖盖虫", "Escavalier": "骑士蜗牛",
    "Foongus": "哎呀球菇", "Amoonguss": "败露球菇", "Frillish": "轻飘飘",
    "Jellicent": "胖嘟嘟", "Alomomola": "保姆曼波", "Joltik": "电电虫",
    "Galvantula": "电蜘蛛", "Ferroseed": "种子铁球", "Ferrothorn": "坚果哑铃",
    "Klink": "齿轮儿", "Klang": "齿轮组", "Klinklang": "齿轮怪",
    "Tynamo": "麻麻小鱼", "Eelektrik": "麻麻鳗", "Eelektross": "麻麻鳗鱼王",
    "Elgyem": "小灰怪", "Beheeyem": "大宇怪", "Litwick": "烛光灵",
    "Lampent": "灯火幽灵", "Chandelure": "水晶灯火灵", "Axew": "牙牙",
    "Fraxure": "斧牙龙", "Haxorus": "双斧战龙", "Cubchoo": "喷嚏熊",
    "Beartic": "冻原熊", "Cryogonal": "几何雪花", "Shelmet": "小嘴蜗",
    "Accelgor": "敏捷虫", "Stunfisk": "泥巴鱼", "Mienfoo": "功夫鼬",
    "Mienshao": "师父鼬", "Druddigon": "赤面龙", "Golett": "泥偶小人",
    "Golurk": "泥偶巨人", "Pawniard": "驹刀小兵", "Bisharp": "劈斩司令",
    "Bouffalant": "爆炸头水牛", "Rufflet": "毛头小鹰", "Braviary": "勇士雄鹰",
    "Vullaby": "秃鹰丫头", "Mandibuzz": "秃鹰娜", "Heatmor": "熔蚁兽",
    "Durant": "铁蚁", "Deino": "单首龙", "Zweilous": "双首暴龙",
    "Hydreigon": "三首恶龙", "Larvesta": "燃烧虫", "Volcarona": "火神蛾",
    "Cobalion": "勾帕路翁", "Terrakion": "代拉基翁", "Virizion": "毕力吉翁",
    "Tornadus": "龙卷云", "Thundurus": "雷电云", "Reshiram": "莱希拉姆",
    "Zekrom": "捷克罗姆", "Landorus": "土地云", "Kyurem": "酋雷姆",
    "Keldeo": "凯路迪欧", "Meloetta": "美洛耶塔", "Genesect": "盖诺赛克特",
}


def display_name(name, table):
    """返回「中文名(英文名)」，翻译表未收录时直接返回英文原名。"""
    zh = table.get(name)
    if zh:
        return f"{zh}({name})"
    # 通用规则：Route N → 第 N 号道路（任何地区的路线都适用）
    m = re.fullmatch(r"Route\s*(\d+)", name, flags=re.IGNORECASE)
    if m:
        return f"第 {m.group(1)} 号道路({name})"
    return name


def expand_filters(values, table):
    """把过滤条件的用户输入（支持中文或英文）展开成英文小写集合。

    例如 FILTER_POKEMON=洛托姆 会自动对应 Rotom；写 Rotom 也可以。
    """
    result = set()
    for v in values:
        v = v.strip()
        if not v:
            continue
        vl = v.lower()
        result.add(vl)
        for en, zh in table.items():
            if zh.lower() == vl:
                result.add(en.lower())
                break
    return result


# ════════════════ 文案 ════════════════

def fmt_duration(seconds):
    seconds = max(0, int(seconds))
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h} 小时 {m} 分钟"
    return f"{m} 分钟"


def build_text(swarm):
    remain = SWARM_LIFETIME - swarm["age_s"]
    parts = [
        f"地区:{display_name(swarm['region'], REGION_ZH)}",
        f"地点:{display_name(swarm['location'], LOCATION_ZH)}",
        f"已出现:{fmt_duration(swarm['age_s'])}",
    ]
    if remain > 0:
        parts.append(f"预计还剩:约 {fmt_duration(remain)}")
    return "　".join(parts)


def build_title(swarm):
    return f"🔥 新 Swarm:{display_name(swarm['pokemon'], POKEMON_ZH)}"


# ════════════════ 推送通道 ════════════════

def http_post_json(url, payload, headers=None, timeout=15):
    data = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def send_ntfy(swarm):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return 0
    payload = {
        "topic": topic,
        "title": build_title(swarm),
        "message": build_text(swarm),
        "click": SITE_URL,
        "priority": 3,
        "tags": [swarm["pokemon"].lower()],
    }
    headers = {}
    token = os.environ.get("NTFY_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        status, _ = http_post_json(f"https://ntfy.sh/{urllib.parse.quote(topic)}", payload, headers)
        print(f"[ntfy] 已推送 {swarm['pokemon']} (HTTP {status})")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"[ntfy] 推送失败: {e}")
        return 0


def send_pushplus(swarm):
    token = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    if not token:
        return 0
    content = (
        f"**{build_title(swarm)}**\n\n"
        + build_text(swarm).replace("\n", "\n\n")
        + f"\n\n[打开 Alphapedia]({SITE_URL})"
    )
    try:
        status, body = http_post_json("https://www.pushplus.plus/send", {
            "token": token,
            "title": build_title(swarm),
            "content": content,
            "template": "markdown",
        })
        print(f"[PushPlus] 已推送 {swarm['pokemon']} (HTTP {status}, {body[:80]})")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"[PushPlus] 推送失败: {e}")
        return 0


def send_serverchan(swarm):
    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    if not sendkey:
        return 0
    data = urllib.parse.urlencode({
        "title": build_title(swarm),
        "desp": build_text(swarm) + f"\n\n[打开 Alphapedia]({SITE_URL})",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://sctapi.ftqq.com/{sendkey}.send", data=data,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        print(f"[Server酱] 已推送 {swarm['pokemon']} (HTTP {resp.status}, {body[:80]})")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"[Server酱] 推送失败: {e}")
        return 0


def send_telegram(swarm):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (token and chat_id):
        return 0
    text = f"{build_title(swarm)}\n{build_text(swarm)}\n{SITE_URL}"
    try:
        status, _ = http_post_json(f"https://api.telegram.org/bot{token}/sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        })
        print(f"[Telegram] 已推送 {swarm['pokemon']} (HTTP {status})")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"[Telegram] 推送失败: {e}")
        return 0


def send_bark(swarm):
    bark_url = os.environ.get("BARK_URL", "").strip().rstrip("/")
    if not bark_url:
        return 0
    try:
        status, _ = http_post_json(bark_url, {
            "title": build_title(swarm),
            "body": build_text(swarm),
            "url": SITE_URL,
        })
        print(f"[Bark] 已推送 {swarm['pokemon']} (HTTP {status})")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"[Bark] 推送失败: {e}")
        return 0


def send_test_notification():
    """发送一条测试通知，确认通道配置可用。"""
    sent = False
    try:
        if os.environ.get("NTFY_TOPIC", "").strip():
            topic = os.environ["NTFY_TOPIC"].strip()
            http_post_json(f"https://ntfy.sh/{urllib.parse.quote(topic)}", {
                "topic": topic,
                "title": "✅ Swarm 监控已启动",
                "message": "这是一条测试通知。接下来每次出现新的 Swarm，你都会在这里收到提醒。",
                "click": SITE_URL,
                "priority": 3,
                "tags": ["white_check_mark"],
            })
            print("[ntfy] 测试通知已发送")
            sent = True
        if os.environ.get("PUSHPLUS_TOKEN", "").strip():
            http_post_json("https://www.pushplus.plus/send", {
                "token": os.environ["PUSHPLUS_TOKEN"].strip(),
                "title": "✅ Swarm 监控已启动",
                "content": "这是一条测试通知。接下来每次出现新的 Swarm，你都会在这里收到提醒。",
                "template": "markdown",
            })
            print("[PushPlus] 测试通知已发送")
            sent = True
        if os.environ.get("SERVERCHAN_SENDKEY", "").strip():
            data = urllib.parse.urlencode({
                "title": "✅ Swarm 监控已启动",
                "desp": "这是一条测试通知。接下来每次出现新的 Swarm，你都会在这里收到提醒。",
            }).encode("utf-8")
            req = urllib.request.Request(
                f"https://sctapi.ftqq.com/{os.environ['SERVERCHAN_SENDKEY'].strip()}.send",
                data=data, headers={"User-Agent": USER_AGENT}, method="POST")
            urllib.request.urlopen(req, timeout=15)
            print("[Server酱] 测试通知已发送")
            sent = True
        if os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip():
            http_post_json(
                f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN'].strip()}/sendMessage",
                {"chat_id": os.environ["TELEGRAM_CHAT_ID"].strip(),
                 "text": "✅ Swarm 监控已启动\n这是一条测试通知。接下来每次出现新的 Swarm，你都会在这里收到提醒。"})
            print("[Telegram] 测试通知已发送")
            sent = True
        if os.environ.get("BARK_URL", "").strip():
            http_post_json(os.environ["BARK_URL"].strip().rstrip("/"), {
                "title": "✅ Swarm 监控已启动",
                "body": "这是一条测试通知。接下来每次出现新的 Swarm，你都会在这里收到提醒。",
                "url": SITE_URL,
            })
            print("[Bark] 测试通知已发送")
            sent = True
    except Exception as e:  # noqa: BLE001
        print(f"[错误] 测试通知发送失败: {e}")
    if not sent:
        print("[提示] 未配置任何推送通道，测试通知未发送。")
        print("       请先设置环境变量，例如 NTFY_TOPIC=你的主题名")
    return 0 if sent else 1


# ════════════════ 主流程 ════════════════

def check_once(verbose=True):
    html = http_get(SITE_URL)
    if html is None:
        print("[错误] 首页抓取失败，本次跳过。")
        return 1

    swarms = parse_swarms(html)
    print(f"[信息] 当前首页共 {len(swarms)} 个 swarm：")
    for s in swarms:
        print(f"       {display_name(s['region'], REGION_ZH):<12} "
              f"{display_name(s['pokemon'], POKEMON_ZH):<16} @ {display_name(s['location'], LOCATION_ZH):<26} "
              f"已出现 {fmt_duration(s['age_s'])}")

    # 过滤：地区 / 宝可梦（中英文都支持）
    filter_region = expand_filters(os.environ.get("FILTER_REGION", "").split(","), REGION_ZH)
    filter_pokemon = expand_filters(os.environ.get("FILTER_POKEMON", "").split(","), POKEMON_ZH)
    if filter_region:
        swarms = [s for s in swarms if s["region"].lower() in filter_region]
    if filter_pokemon:
        swarms = [s for s in swarms if s["pokemon"].lower() in filter_pokemon]

    # 只关心「新出现」的 swarm
    age_max = int(os.environ.get("NOTIFY_AGE_MAX", str(DEFAULT_AGE_MAX)))
    fresh = [s for s in swarms if s["age_s"] <= age_max]
    print(f"[信息] 其中 {len(fresh)} 个为近期新报告（{fmt_duration(age_max)} 内）。")

    if os.environ.get("TEST_NOTIFY", "").strip() in ("1", "true", "True", "yes"):
        return send_test_notification()

    if not fresh:
        print("[信息] 没有新的 swarm，结束。")
        return 0

    state = load_state()
    new_alerts = []
    for s in fresh:
        sig = make_signature(s)
        if sig in state["notified"]:
            continue
        new_alerts.append(s)
        state["notified"][sig] = int(time.time())

    if not new_alerts:
        print("[信息] 有新鲜 swarm，但都已提醒过，结束。")
        return 0

    print(f"[信息] 检测到 {len(new_alerts)} 个新 swarm，开始推送...")
    sent_any = False
    for s in new_alerts:
        print(f"  → {display_name(s['pokemon'], POKEMON_ZH)} @ {display_name(s['location'], LOCATION_ZH)} ({display_name(s['region'], REGION_ZH)})")
        sent_any |= bool(send_ntfy(s) or send_pushplus(s) or send_serverchan(s)
                         or send_telegram(s) or send_bark(s))

    # 清理过老记录，防止 state.json 无限变大
    notified = state["notified"]
    if len(notified) > STATE_MAX_ENTRIES:
        for k in list(notified.keys())[:len(notified) - STATE_MAX_ENTRIES]:
            del notified[k]
    save_state(state)

    if not sent_any:
        print("[警告] 没有配置任何推送通道！请设置 NTFY_TOPIC 等环境变量。")
        return 1
    return 0


def check_loop(interval_sec=60):
    print(f"[信息] 进入循环监控模式，每 {interval_sec} 秒检查一次，Ctrl+C 退出。")
    while True:
        try:
            check_once(verbose=False)
        except Exception as e:  # noqa: BLE001
            print(f"[错误] 本轮检查异常: {e}")
        time.sleep(interval_sec)


def main():
    parser = argparse.ArgumentParser(description="PokeMMO Alphapedia Swarm 监控推送")
    parser.add_argument("--once", action="store_true", help="只检查一次")
    parser.add_argument("--loop", action="store_true", help="循环监控（默认每 60 秒）")
    parser.add_argument("--interval", type=int, default=60, help="循环模式间隔秒数（默认 60）")
    args = parser.parse_args()

    if args.loop:
        check_loop(args.interval)
    else:
        sys.exit(check_once())


if __name__ == "__main__":
    main()
