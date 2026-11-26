# 女优头像：18x 从 Gfriends 拉取并上传到 Jellyfin 人物主图

状态：已实施（待上线）
日期：2026-11-26
相关：`docs/actresses.md`、`docs/superpowers/specs/2026-11-25-actress-archive-design.md`

## 1. 为什么做

女优档案上线后（2026-11-26，1570 人），「女优」页的头像全部是占位图；Jellyfin 115 番号库的 2081 个人物也都没有头像。原因是 MDC 刮削的 NFO 里没有演员头像地址，而 Jellyfin 按约定只读本地、不在线刮削。

曾尝试复用 MDC-NG 自带的女优模块（它就是从 Gfriends 取头像，再推送给 Emby），但这个模块按 Emby 的写法列人物，在 Jellyfin 上只能拿回 10 个人，按名字搜索也不起作用，所以不能用。

用户选定由 18x 自己拉头像：按档案名到 Gfriends 头像库找图，下载后上传为 Jellyfin 人物的主图。这样 Jellyfin 和 18x「女优」页都有头像，因为女优页本来就从 Jellyfin 转发人物图，这部分不用改。

## 2. 目标、不做什么、不能出现什么

目标：

- 尽量让档案里每位女优在 Jellyfin 里的人物有主图，「女优」页随之显示头像。
- 跟着每天的任务自动给新建档的人补头像；已经有图的不重复下载、不重复上传。
- 找不到头像的人可以看到原因，过一段时间再自动重找一次（Gfriends 持续更新）。

不做：

- 影片海报：MDC 已经负责，生产 5534 部片里有 5464 部有海报。
- 演员资料（生日、身高等）。
- 网页上手动为某人指定头像（以后再说）。
- 删除或替换 Jellyfin 里已有的人物图。

不能出现：

- **覆盖已有头像**：Jellyfin 里某个人物已经有主图（不管是谁设的），就不动它。
- **让 Jellyfin 在线刮削**：只能由 18x 下载后上传；不改 Jellyfin 的库设置，也不触发全量刷新。
- **拖垮服务器**：首次要下载约 1300 张图，必须逐个、限速地做，不能并发猛拉。
- **把错人的图贴上去**：名字对不上就宁可不贴，不做模糊匹配。

## 3. 现状（2026-11-26 只读核实）

- **Gfriends 官方索引**：`https://raw.githubusercontent.com/gfriends/gfriends/master/Filetree.json`，约 6.5MB，结构如下：
  - `Content` 下有 51 个来源目录，比如 `z-DMM(步)`、`9-Javrave`，共约 10.8 万个文件；
  - 每个文件是 `「日文名.jpg」→「实际文件名?t=时间戳」`，实际文件名可能带 `AI-Fix-` 前缀；
  - 图片地址是 `https://raw.githubusercontent.com/gfriends/gfriends/master/Content/<来源目录>/<实际文件名>`；
  - 文件名的写法有 `名字.jpg`、`名字-834.jpg`（同名区分编号）、`艺名（另一个名字）.jpg` 几种。
- 18x 容器能直接访问 raw.githubusercontent.com，HEAD 请求 0.7 秒返回 200，不需要代理。
- **名字对照**：档案名大多是 MDC 输出的中文译名，Gfriends 用的是日文名。MDC 的演员对照表 `mapping_actor.xml`（在生产 `/mnt/user/docker1/mdc_ng/data/`，约 1.1MB）把 `keyword`、`zh_cn`、`zh_tw` 里的名字对应到 `jp`。
- 按 1570 人抽样统计匹配率（统计脚本按上面三种写法做了归一化）：
  - 直接匹配 744 人；
  - 经对照表匹配 591 人；
  - 经 MDC `Actress.db` 别名匹配 11 人；
  - 没找到 224 人。

  合计 1346 人（86%）能匹配；按片数加权覆盖 95%；片数最多的 100 人里命中 98 人。
- 18x 已有：`JellyfinClient`（含 `get_person_image`）、女优档案和别名表、头像接口 `GET /api/actresses/{id}/image`（转发 Jellyfin 人物主图，目前只按规范名取），以及每日任务链：扫描 → 女优刷新 → 合集同步 → 显示名同步。

## 4. 做法比较

| 做法 | 内容 | 取舍 |
|---|---|---|
| **一：18x 下载后上传到 Jellyfin（用户选定）** | 按档案名查 Gfriends 索引，下载图片，用 Jellyfin 接口设为人物主图 | Jellyfin 和 18x 两边都有头像，18x 头像接口不用改。代价是 18x 要往 Jellyfin 写人物图片。用户认可这不算 Jellyfin 在线刮削，因为图片来源由 18x 统一管 |
| 二：只存在 18x 本地 | 下载到 18x 数据目录，只供女优页显示 | 完全不碰 Jellyfin，但 Jellyfin 里的人物仍然没图 |
| 三：复用 MDC-NG 女优模块 | 打开 MDC 的女优刮削 | 已试过：在 Jellyfin 上只列出 10 个人物，搜索无效，不可用 |

## 5. 设计

### 5.1 找图：名字 → Gfriends 文件

1. **索引**：下载 `Filetree.json`，缓存到 18x 数据目录（比如 `data/actress-avatars/Filetree.json`）。超过 7 天才重新下载；下载失败时沿用旧缓存，没有缓存时本次任务失败。
2. **建查找表**：把每个文件的「显示名」（去掉 `.jpg`）按以下写法各登记一次：原名、去掉末尾 `-数字` 后的名字、括号里外两个名字。归一化规则是去掉空格、`・･·`、各种括号，再统一大小写。
   - 同一个归一化名在多个来源目录里都有时，按来源目录名排序取第一个，保证每次结果一样。builder 可以改成更优的规则，比如优先取 `AI-Fix-` 版本，但必须是确定性的，并写进文档。
3. **对一位女优找图**：把她的规范名和全部别名逐个拿去查，命中就停。每个名字依次试：
   1. 直接查 Gfriends 查找表；
   2. 经 MDC 对照表换成日文名再查。
4. **对照表来源**：新配置 `ACTRESS_AVATAR_NAME_MAP`，填 `mapping_actor.xml` 的路径。生产上把 `/mnt/user/docker1/mdc_ng/data/mapping_actor.xml` 只读挂进 18x 容器，这需要改 `docker/docker-compose.yml`，上线时用户批准。没配或读不了时只做直接匹配，并在任务摘要里写明。
5. 不用 `Actress.db` 别名（只多 11 人，还要引入 SQLite 文件依赖），列为以后可加。

### 5.2 贴图：上传到 Jellyfin 人物

1. 对一位找到图的女优，取她的规范名和全部别名里**在 Jellyfin 中存在的人物**（`GET /Persons/{名字}` 能拿到 Id）。
2. 某个人物**已经有主图**时跳过它，看人物的 `ImageTags.Primary`。
3. 下载图片（超时 30 秒，只接受图片类型，大小设上限，比如 5MB），再用 `POST /Items/{人物 Id}/Images/Primary` 上传。Jellyfin 要求请求体是图片的 base64、`Content-Type` 是图片类型。**实施时第一步先对 1 个人物验证这个接口**，不对就停下汇报。
4. 同一张图下载一次，传给这位女优所有还没有主图的对应人物。
5. 结果：至少给一个人物传成功，记 `uploaded`；对应人物本来都有图，记 `present`。（设计者的决定）

### 5.3 记录状态（加到女优档案上）

给 `actresses` 表加几列（需要迁移）：

- `avatar_state`：
  - `pending`：没处理过；
  - `uploaded`：已上传；
  - `present`：Jellyfin 里本来就有图；
  - `not_found`：Gfriends 里找不到；
  - `no_person`：Jellyfin 里没有对应人物；
  - `error`：失败。
- `avatar_source`：命中的 Gfriends 文件路径，用来追溯。
- `avatar_note`：失败原因或说明。
- `avatar_checked_at`：最近一次处理的时间。

哪些人会被处理：`pending` 和 `error` 的；`not_found` 和 `no_person` 满 7 天后重新查；`uploaded` 和 `present` 的不再处理，**也不回查 Jellyfin**。名字变化（合并、加别名）时把她的状态重置为 `pending`。

不回查（设计者的决定）的意思是：用户在 Jellyfin 里删掉一张贴错的图后，18x 不会再自动贴回去，除非她的名字后来有变化。这样尊重用户的手动删除，也省掉每天对 1000 多人的复查请求，所以不需要单独做「不要自动头像」的标记。

### 5.4 什么时候跑

- 新任务 `actress:avatars`，接在每日链「女优刷新」之后、「合集同步」之前，或者放到链尾，由 builder 定。这一步失败只记在自己的任务上，不挡后面的步骤。
- 新开关 `ACTRESS_AVATARS_ENABLED`，默认关闭；还要求 `ACTRESS_ENABLED` 打开、Jellyfin 地址和 API Key 都已配置。
- 节奏：逐个处理，每张图之间至少间隔 0.5 秒。每次最多处理 N 人（配置 `ACTRESS_AVATARS_PER_RUN`，默认 300），首次约 1300 人分几天补完，避免一次下载 300MB 以上。
- 手动触发：`POST /api/actresses/avatars/refresh`，同一时间只跑一个；「女优」页加一个按钮。（以下为设计者的决定）
  - 可选参数 `actress_ids`：只处理这几个人，而且不管她们当前是什么状态都重做一次，供上线验证和单人重试用。
  - 可选参数 `limit`：本次最多处理几人，不传时用 `ACTRESS_AVATARS_PER_RUN`。
  - 手动触发只要求 `ACTRESS_ENABLED` 打开、Jellyfin 已配置，**不受** `ACTRESS_AVATARS_ENABLED` 限制；这个开关只管每日自动跑。这样上线时可以在开关打开前先试 3 个人。
- 任务摘要：本次处理、上传、本来就有、找不到、没有人物、失败各多少人。

### 5.5 页面

- 女优页头像接口 `GET /api/actresses/{id}/image` 小改一处（设计者的决定）：先按规范名取，取不到再依次按别名取。否则 Jellyfin 里只有别名人物的女优，状态是 `uploaded`，页面上却还是占位图。浏览器可能缓存了占位图，刷新即可。
- 女优详情里显示头像状态和原因，比如「Gfriends 里找不到」「Jellyfin 里没有这个人物」，让用户知道为什么没图。
- 列表筛选「没有头像」：可选，由 builder 定。

## 6. 风险

- Jellyfin 上传接口的格式只看过资料，没实测，实施第一步就验证。
- Gfriends 的同名不同人：只按完整名字精确匹配，可能把同名的另一个人的图贴上来，这个风险能接受。用户在 Jellyfin 里删掉那张图就行，18x 不会再贴回去（见 5.3「不回查」）。
- 依赖 MDC 的对照表文件：MDC 升级时文件可能变动或换位置，读不了时退回只做直接匹配，覆盖率会掉到约 47%。
- 流量：首次下载约 1300 张图，分多天跑；之后每天只处理新人。

## 7. 上线步骤（每步都需要用户批准）

1. 部署代码（带迁移），开关保持关闭。
2. 改 compose 把 MDC 对照表只读挂进 18x 容器，配置 `ACTRESS_AVATAR_NAME_MAP`。
3. 用手动接口带 `actress_ids` 对 3 个人跑一次，核对 Jellyfin 和女优页的显示。这时 `ACTRESS_AVATARS_ENABLED` 还关着。
4. 打开 `ACTRESS_AVATARS_ENABLED`，让每日任务分批补完。

## 8. 留给 builder 的

- 同名文件在多个来源目录时的取图规则（必须确定性）。
- 任务在每日链里的具体位置、每次处理的上限。
- 女优页是否加「没有头像」筛选。
