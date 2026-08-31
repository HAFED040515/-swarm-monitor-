# PokeMMO Swarm 手机提醒（Alphapedia 监控）

> 让 **alpha.pokemmotools.org** 网站上的新 Swarm（群聚宝可梦）第一时间推送到你的安卓手机。

网站本身**没有**「推送通知」功能，所以这套方案用 **GitHub Actions 免费云** 每 5 分钟自动帮你看一眼网站，发现**新出现的 swarm** 就通过 **ntfy**（手机 App）弹通知给你。全程免费、24 小时在线、不用自己开机。

---

## 原理（一句话版）

```
GitHub 云端每 5 分钟 → 自动打开 Alphapedia 首页 → 发现有新 swarm（10 分钟内报告的）
→ 推一条通知到你的手机 ntfy App → 你看到消息马上去游戏里抓！
```

---

## 需要准备的东西

| 东西 | 说明 |
|---|---|
| 安卓手机 | 装一个 ntfy App（免费） |
| GitHub 账号 | 免费注册，用来放监控脚本（**建仓库时选 Public**，这样 Actions 免费不限量） |

---

## 第一步：手机装 ntfy 并订阅主题

1. 安卓手机装 **ntfy** 这个 App：
   - 有 Google Play：直接在 Play 商店搜 "ntfy" 安装
   - 没有 Play：去官网 `ntfy.sh` 点 **Download** 下载 APK，或用 F-Droid 安装
2. 打开 App → 点 **＋（新建订阅）** → 在 **Topic** 栏填一个**你自己起的主题名**，例如：
   ```
   pokemmo-swarm-你的昵称-8899
   ```
   ⚠️ 主题名要**难猜一点**（别用 `pokemmo` 这种常见的），否则别人也能往里面发消息。
3. 订阅成功后，手机停留在 App 首页即可（不用打开监控网站）。

> 这个主题名请**记下来**，第二步第 4 步要填同一个名字。

---

## 第二步：在 GitHub 上建仓库并上传文件

1. 打开 `github.com` → 登录或注册（免费）。
2. 点右上角 **＋** → **New repository**：
   - Repository name 随便填，比如 `swarm-monitor`
   - **Public 一定要选 Public**（选 Private 的话免费额度 7 天就用完了）
   - 直接点 **Create repository**
3. 在新页面点 **uploading an existing file**（添加文件 → 上传文件）。
4. 把我给你的 **3 样东西**拖进上传框：
   - `swarm_monitor.py`
   - `.github` 文件夹（里面是 `workflows/swarm-monitor.yml`）
   - （没有 state.json 没关系，第一次运行会自动创建）
   ⚠️ 上传时注意保持 `.github/workflows/swarm-monitor.yml` 这个**目录结构**不能变。
5. 点 **Commit changes**（提交）。

---

## 第三步：把主题名告诉 GitHub（配置 Secret）

1. 进入你的仓库 → 点 **Settings（设置）** → 左侧菜单 **Secrets and variables（密钥和变量）** → **Actions**。
2. 点 **New repository secret（新建仓库密钥）**：
   - Name（名称）：`NTFY_TOPIC`
   - Secret（值）：填你第一步里起的**主题名**，例如 `pokemmo-swarm-你的昵称-8899`
   - 点 **Add secret**（添加）
3. 完成。

---

## 第四步：测试一下（很重要）

1. 进入仓库 → 点顶部 **Actions** 标签 → 左侧点 **PokeMMO Swarm Monitor**。
2. 右侧点 **Run workflow（运行工作流）** → 在输入框里填 `true` → 再点绿色的 **Run workflow**。
3. 等 1 分钟左右，刷新页面，看到 **绿色对勾** 就说明跑成功了。
4. 此时你的**手机应该收到一条「✅ Swarm 监控已启动」的测试通知**。

收到 = 大功告成！接下来每 5 分钟自动检查，有新 swarm 就会弹通知。

没收到？看文末「常见问题」。

---

## 日常使用说明

- 以后什么都不用管，GitHub 每 5 分钟自动检查一次，24 小时不间断。
- 收到通知长这样（**自动翻译成中文**，括号里附英文原名方便对照游戏）：
  > **🔥 新 Swarm：洛托姆（Rotom）**
  > 地区：关都（Kanto）　地点：发电厂（Power Plant）
  > 已出现：3 分钟　预计还剩：约 22 分钟
- 点通知会直接打开 Alphapedia 首页看详情。
- 同一只宝可梦在同一地点、同一小时内**只提醒一次**，不会刷屏。
- 内置翻译表覆盖了 **649 只宝可梦 + 所有地区 + 常见地点**，路线自动翻译成「第 N 号道路」。个别没收录的地点会显示英文原名（见下面「自定义翻译」）。

---

## 可选功能

### 1. 只想提醒特定地区 / 特定宝可梦（比如只想要龙系）

仓库 **Settings → Secrets and variables → Actions → Variables（变量）** 里添加：

| 变量名 | 填什么 | 例子 |
|---|---|---|
| `FILTER_REGION` | 只要这些地区的 swarm | `Kanto,关都` |
| `FILTER_POKEMON` | 只要这些宝可梦 | `Gible,圆陆鲨,Bagon` |

多个用英文逗号分隔，**中英文都可以填**（比如填 `洛托姆` 或 `Rotom` 效果一样）。留空 = 全部提醒。

### 2. 想要微信推送（手机不方便装 ntfy 时）

用 **PushPlus**：手机微信扫码登录 `www.pushplus.plus` → 拿 token → 在仓库里加一个 secret：`PUSHPLUS_TOKEN` = 你的 token。之后微信也能收到，和 ntfy 不冲突，两条都发。

### 3. 想补充自定义译名（个别地点没翻译时）

打开 `swarm_monitor.py`，找到 `LOCATION_ZH = {` 这段（宝可梦是 `POKEMON_ZH`），按同样格式加一行即可：
```python
"New Moon Island": "新月岛",
```
然后重新上传覆盖这个文件，GitHub 会继续自动运行，下次就会用新译名。

### 4. 不用 GitHub，在自己电脑上跑（电脑常开机时）

```bash
# Windows / Mac / Linux 都行，需要装 Python 3
set NTFY_TOPIC=你的主题名        # Windows CMD
# 或
export NTFY_TOPIC=你的主题名      # Mac / Linux

python swarm_monitor.py --loop    # 每 60 秒检查一次，挂着别关
```

---

## 常见问题

**Q：手动测试没收到通知？**
- 检查 GitHub Actions 运行日志：点那次运行的记录 → 展开「检查 Swarm 并推送手机通知」→ 看有没有 `[ntfy] 已推送` 或报错。
- 手机 App 里订阅的主题名，和 secret 里 `NTFY_TOPIC` 的值**必须一字不差**（注意大小写和空格）。
- 手机要保持联网；ntfy App 如果被系统杀后台，去手机设置里允许它后台运行/通知权限。

**Q：为什么一开始测试，没有新 swarm 通知？**
当前没有 10 分钟内的新 swarm 时不会推送，这是正常的。可以随时用「Run workflow + true」再测一次。

**Q：Private 仓库会怎样？**
免费额度只有 2000 分钟/月，每 5 分钟跑一次大约 7 天就耗尽，之后当月不再运行。**所以务必建 Public 仓库**（Public 的 Actions 免费不限量，脚本里没有你的任何隐私信息）。

**Q：state.json 是什么？**
自动生成的「去重小账本」，记录提醒过哪些 swarm，避免重复刷屏。每次有新提醒时自动提交回仓库，不用管它。

**Q：我想换推送 App / 加微信推送？**
脚本已支持 ntfy、PushPlus（微信）、Server酱（微信）、Telegram、Bark（iPhone）。想加哪个，就在仓库 Secrets 里加对应变量名，例如加个 `PUSHPLUS_TOKEN` 即可同时用微信接收。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `swarm_monitor.py` | 监控脚本：抓首页 → 解析 swarm → 去重 → 推送（零依赖，纯 Python 标准库） |
| `.github/workflows/swarm-monitor.yml` | GitHub Actions 定时任务：每 5 分钟跑一次脚本 |
| `state.json` | 自动生成，去重状态，不用管 |
