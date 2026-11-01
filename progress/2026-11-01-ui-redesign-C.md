# 阶段 C：其余页面迁移

## What was done

- 数据组、流程组、系统组和登录页统一接入 `PageScaffold`；有筛选或操作区的页面接入 `DataToolbar`。
- 用 `StatusTag`、`TimeText`、`BytesText` 和 CSS 变量替换页面状态、时间、容量和硬编码颜色展示。
- 扩展 `statusText.ts` 的导入、关键词、流程、授权、审核状态映射，并补齐对应单元测试。
- 新增数据组、流程组、系统组冒烟渲染测试；清理登录旧胶囊样式和页面紫色残留。

## Testing

- `npx tsc -p tsconfig.app.json --noEmit --incremental false`：通过。
- 改动页面和状态工具的 ESLint：通过；Emby 页面保留仓库已知的 effect lint 错误。
- 页面颜色残留扫描和旧紫色扫描：无输出。

## Notes

### Changed files

- `frontend/src/pages/` 下数据、流程、系统页面及三组冒烟测试。
- `frontend/src/utils/statusText.ts`、对应测试和 `frontend/src/index.css`。

### Rollback

- 回退本轮页面、状态映射、样式和测试文件即可；未执行 Git 操作。
