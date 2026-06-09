# 前端视觉系统重做设计

日期：2026-06-09

## 背景

当前前端是 React + Vite + Ant Design，页面已经覆盖导入批次、目录内容、关键词、整理计划、文件去重、授权中心等后台工作流。现有视觉主要由 `frontend/src/App.tsx` 的内联布局样式和 `frontend/src/index.css` 中的 `soft-card`、暖浅色背景、较大圆角、阴影、渐变组成。

用户希望进行一轮前端视觉优化，方向是深色模式优先、大量留白、极简图标、少毛玻璃、几乎不用渐变、细边框替代阴影、紫色作为品牌色、信息密度高但不拥挤、动效快且克制、页面切换丝滑、Hover 有反馈、键盘操作优先。同时用户不喜欢大片深色，长时间看会不舒服。

经过视觉方向对比，最终选择 C 方案：不是简单换肤，而是重做统一应用壳和基础界面层。默认主题采用“深色框架 + 护眼工作区”，可切换到“墨灰工作区”。

## 目标

1. 建立统一的应用壳，替代分散在 `App.tsx` 中的内联布局样式。
2. 新增可切换主题系统：默认“护眼”，可切换“墨灰”，选择写入本地持久化。
3. 用 Ant Design token 与 CSS 变量共同管理颜色、边框、间距、圆角、动效和焦点。
4. 用细边框、层级色和状态色替代大面积阴影、渐变和毛玻璃。
5. 让高密度页面保持可扫描：稳定页面头部、工具条、面板、表格、审批侧栏布局。
6. 增强键盘可用性：清晰 `focus-visible`、可操作主题切换、导航和按钮焦点反馈。
7. 统一 150-250ms 微动效，包括导航、按钮、表格行、面板 hover 和页面切换。
8. 保持现有路由、API、业务行为不变。

## 非目标

1. 不重写业务数据流、接口或后端。
2. 不一次性重构所有页面内部业务逻辑。
3. 不引入新的大型 UI 框架替代 Ant Design。
4. 不做营销型 landing page 或装饰性大图。
5. 不把“墨灰”作为唯一默认主题；默认必须照顾长时间使用的眼睛舒适度。
6. 本设计不依赖 Figma 写入工具可用性。若后续 Figma MCP 可用，可按本设计补建 Figma 页面和组件库。

## 设计方向

### 视觉性格

整体应像一个长期使用的专业工作台，而不是展示页。默认界面保留深色模式的产品识别：深色侧栏、紫色品牌、克制的顶部状态区；主工作区使用偏冷的浅灰紫底色，让表格和表单长时间阅读更舒服。

墨灰主题用于夜间或偏深色偏好：主工作区改为低对比石墨灰，而不是纯黑。墨灰主题仍需保持足够文本对比，不应出现大面积炫光紫色或深蓝黑。

### 色彩

紫色是唯一品牌主色，建议使用接近 `#8b5cf6` 的中性紫。紫色只用于：

- 主按钮。
- 当前导航项。
- 焦点环。
- 小面积状态强调。
- 主题切换选中态。

默认护眼主题建议基调：

- 外框与侧栏：`#15131c`、`#1b1823`。
- 主背景：冷灰浅紫，例如 `#ece8f2`。
- 面板：接近白但不刺眼，例如 `#f8f6fb`。
- 输入与表格 hover：略深冷灰，例如 `#f0edf6`。
- 边框：半透明冷灰紫。

墨灰主题建议基调：

- 外框与侧栏：`#14131a`。
- 主背景：`#202027`。
- 面板：`#2a2a33`。
- 输入与工具条：`#24242d`。
- 文本：暖白偏灰，避免纯白眩光。

### 空间与密度

页面不做大 hero 或大卡片堆叠。默认布局应使用稳定的后台工作台结构：

- 固定侧栏。
- 粘性顶部栏。
- 页面标题区。
- 可选 KPI 区。
- 主内容区。
- 工具条。
- 数据表格或审批面板。

“大量留白”体现在区块之间有清晰呼吸，而不是降低信息密度。表格行高、工具条高度、卡片 padding 需要保持紧凑但不拥挤。

## 信息架构

### 应用壳

新增 `AppShell`，负责：

- 侧栏导航和分组。
- 顶部栏。
- 主题切换控件。
- 登录用户和退出操作。
- 主内容容器。
- 页面切换动画容器。

侧栏导航按功能分组，而不是简单纵向堆满：

- Data：导入批次、目录内容、关键词提取、关键词、重复词扫描、命中重建。
- Workflow：整理任务、整理计划、执行日志、白名单批处理、文件去重、磁力下载。
- System：授权中心、系统状态。

### 页面脚手架

新增 `PageScaffold`，统一页面顶部结构：

- `title`
- `description`
- `actions`
- `stats`
- `children`

页面内部可以继续使用 Ant Design 的 `Row`、`Col`、`Space`、`Table`、`Card`，但页面标题、说明、关键动作和统计信息不再每个页面单独拼。

### 基础面板

新增轻量基础组件或约定类名：

- `SurfacePanel`：替代 `soft-card`，默认细边框、无大阴影、8-14px 圆角。
- `DataToolbar`：表格筛选和刷新区域。
- `ActionCluster`：页头/面板操作区。
- `MetricStrip`：轻量统计区。

这些组件只包视觉结构，不改业务语义。

## 主题架构

### 状态流

新增主题状态：

- `comfort`：默认护眼主题。
- `graphite`：墨灰主题。

主题状态在应用启动时从 `localStorage` 读取，默认 `comfort`。用户切换后写回 `localStorage`，并给根节点设置 `data-theme`。

推荐结构：

1. `ThemeProvider` 管理主题状态和 Ant Design `ConfigProvider` token。
2. `AppShell` 读取主题并渲染切换控件。
3. `index.css` 根据 `:root` 和 `[data-theme='graphite']` 暴露 CSS 变量。
4. 业务页面通过组件、AntD token 和通用类名继承主题，不直接判断主题。

### Ant Design token

`ConfigProvider` 应集中设置：

- `colorPrimary`
- `colorBgLayout`
- `colorBgContainer`
- `colorText`
- `colorTextSecondary`
- `colorBorder`
- `borderRadius`
- `boxShadow`
- `controlHeight`
- `motionDurationFast`
- `motionDurationMid`

护眼主题可以使用默认算法加自定义 token；墨灰主题使用 dark algorithm 或等效暗色 token，但需要覆盖过黑的背景和过亮文本。

### CSS 变量

CSS 变量负责应用壳和自定义结构：

- `--app-bg`
- `--app-sidebar-bg`
- `--app-header-bg`
- `--app-surface`
- `--app-surface-muted`
- `--app-border`
- `--app-text`
- `--app-text-muted`
- `--app-brand`
- `--app-focus`
- `--motion-fast`
- `--motion-base`

## 交互与动效

所有动画保持 150-250ms：

- Hover：150-180ms。
- 导航选中和按钮状态：180ms。
- 页面内容切换：180-220ms 淡入加 2-4px 轻微位移。
- 主题切换：200-250ms 背景、边框、文本过渡。

不使用夸张弹跳、长延迟或大幅位移动画。`prefers-reduced-motion: reduce` 下禁用非必要位移和过渡。

## 键盘与可访问性

1. 主题切换使用 Ant Design `Segmented` 或等价可键盘操作控件。
2. 导航链接、按钮、输入框和表格可点击行必须有清晰 `focus-visible`。
3. 焦点环使用紫色，但不遮挡文字。
4. 表格行 hover 和 keyboard focus 使用同一套背景反馈。
5. 所有 icon-only 按钮必须有 `aria-label` 或可见文本。
6. 颜色状态不能只靠颜色表达，仍需保留 Tag 文案。

## 页面迁移策略

第一阶段建立系统层：

- 提取 `AppShell`。
- 建立 `ThemeProvider`。
- 替换全局 `index.css` 主题变量。
- 顶部栏新增主题切换。
- 侧栏改为分组导航。

第二阶段迁移公共页面结构：

- 引入 `PageScaffold`。
- 替换常见 `page-header` 和零散标题区。
- 把 `soft-card` 视觉迁移为 `SurfacePanel` 或等价类名。

第三阶段重点优化高密度页面：

- `FileDedupePage`：三栏工作台、候选表、详情审批区。
- `KeywordsPage`：左侧操作/合并/相似提示，右侧关键词列表和日志。
- `ImportsPage`、`NodesPage`：表格筛选和数据区。
- `PlansPage`、`ExecutorPage`：计划列表、批量操作和执行日志。

迁移时保留页面行为和 API 调用。若某页内联样式影响主题，应优先改为 CSS 类或 token。

## 错误处理与边界

1. 如果 `localStorage` 读取失败，回退到 `comfort`。
2. 如果主题值未知，回退到 `comfort`。
3. 如果某些 AntD 子组件在墨灰主题下对比不足，优先通过 token 修正，不在页面内写死颜色。
4. 主题切换不能影响登录状态、路由或表格筛选状态。

## Figma 交付说明

用户原始诉求提到用 Figma 辅助前端优化。本轮会话中未暴露可写入 Figma 的 MCP 工具，因此先通过浏览器视觉方向板确认设计。若后续 Figma 工具可用，建议按以下顺序补充 Figma 文件：

1. 建立 `18x Frontend Visual System` 页面。
2. 创建护眼与墨灰两套变量。
3. 创建 AppShell、Sidebar、Topbar、PageScaffold、SurfacePanel、DataToolbar、MetricStrip 组件。
4. 创建 `FileDedupePage` 高保真页面作为迁移样板。

Figma 只作为设计资产和协作视图，代码实现仍以本 spec 和本地浏览器验证为准。

## 测试与验证

### 自动验证

- `npm run lint`
- `npm run build`

### 浏览器验证

使用本地 Vite 预览或开发服务器检查：

- 默认主题是否为护眼主题。
- 切换墨灰主题后刷新页面是否保持选择。
- 侧栏、顶部栏、页面标题、表格、Card、Form、Button、Tag 在两套主题下对比正常。
- `FileDedupePage`、`KeywordsPage`、`ImportsPage`、`PlansPage` 至少四个页面无明显文字溢出、重叠或不可读。
- Hover、focus、页面切换动效符合 150-250ms 的克制感。

### 手动键盘检查

- `Tab` 可以进入主题切换、导航、页面主要按钮。
- `Enter` / `Space` 可以操作主题切换和按钮。
- 当前焦点在护眼和墨灰主题下都清晰可见。

## 成功标准

1. 默认界面不再是暖米色/大阴影风格，而是冷灰护眼工作台。
2. 墨灰主题可切换且持久化。
3. 紫色品牌色统一、克制、可识别。
4. 页面壳层和常用面板样式集中管理，后续页面不需要继续复制内联视觉样式。
5. 高密度页面比现状更有结构，但信息量不下降。
6. 本地 lint/build 通过，并完成浏览器可见验证。
