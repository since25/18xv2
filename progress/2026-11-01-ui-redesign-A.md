# 2026-11-01 UI redesign 阶段 A

## What was done

- 完成 A1 设计令牌与 antd 主题：浅色/深色切换到冷灰与蓝色主色，移除紫色令牌，统一圆角、阴影、语义色和 CSS 变量。
- 完成 A2 格式化工具、状态映射与基础组件：新增容量、时间、相对时间、时长格式化，以及状态徽标、容量、时间和空状态组件。
- 完成 A3 外壳与通用骨架：导航分组中文化、下载器改名、面包屑、浅色侧栏、文字用户下拉菜单、紧凑指标条和左右工具栏插槽。

## Testing

- A1/A2/A3 定向 Vitest：16 tests passed。
- 前端全量 Vitest（临时验证配置，`--testTimeout 15000`）：11 files / 31 tests passed。
- TypeScript：`tsc -p tsconfig.app.json --noEmit` 与 `tsc -p tsconfig.node.json --noEmit` 均通过（将 tsbuildinfo 写入 `/private/tmp`）。
- A1–A3 改动范围 ESLint：通过。
- Vite 生产构建（临时验证配置）：通过。
- 主题/布局紫色检查：`grep -rnE "8b5cf6|139, ?92, ?246" frontend/src/theme frontend/src/layout` 无输出。

## Notes

- Changed files: `frontend/src/theme/`、`frontend/src/utils/format.ts`、`frontend/src/utils/statusText.ts`、`frontend/src/components/{StatusTag,BytesText,TimeText,EmptyState}.tsx` 及测试、`frontend/src/layout/`、`frontend/src/index.css`。
- Rollback: 回退本条所列前端文件即可；未执行 Git 操作、安装依赖、部署或外部服务调用。
- 标准 `npm run test`/`npm run build` 在当前沙箱因软链 `frontend/node_modules` 位于工作区外且 `.vite-temp`/`.tmp` 不可写而退出 1；标准 `npm run lint` 仍有既有 `EmbyMediaActionsPage.tsx` 与 `ReviewIntakePage.tsx` 的 2 个错误，均不在本轮范围。
