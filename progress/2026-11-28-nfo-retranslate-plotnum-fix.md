# 2026-11-28 NFO 重新翻译：简介开头去掉番号

背景见 `progress/2026-11-28-nfo-retranslate-full-apply.md`。全量运行里，有 77 部 FC2 片的简介译文开头带着 `FC2-PPV-编号`，其中 67 部的旧译文没有这段。这 77 部，加上标题丢了英文原题的 REBD-419，共 78 部在写回时被跳过。用户的指示是：「开始修」。

## What was done

- `scripts/nfo_retranslate.py`：
  - 简介送去翻译前，先用 `strip_num` 去掉开头的番号，能识别 `FC2-PPV-编号` 等写法。标题原来就这样处理，判断「要不要翻」时也已经这样做了。
  - 模型返回译文后，标题和简介开头的番号都会去掉。原来只处理了标题。
  - 「标题含换行就判失败」这条检查只对标题生效，不变。
- `docs/nfo-retranslate.md`：在「新简介」那条规则后面补了一句，说明简介也会去掉开头的番号。
- `tests/nfo_retranslate/test_cli.py`：新增 `test_plot_strips_leading_num`，构造一个原简介和模型译文开头都带 `FC2-PPV-4343195` 的 NFO，检查以下三点：
  - 记下的原文不再以它开头；
  - 发给模型的请求里没有这段编号；
  - 译文里的编号也被去掉了。

## Testing

- 新测试先在旧代码上跑，按预期失败（原文仍以 `FC2-PPV-4343195` 开头）；改完代码后通过。`tests/nfo_retranslate` 共 101 passed。
- 全量 `scripts/remote-test.sh backend`：**1137 passed, 18 warnings**（warning 数与基线相同）。日志在 Spark：`~/ci/18x_v2/nfo-retranslate/.remote-test-logs/20261128-155621-backend.log`。
- 用生产库只读统计：6276 个 NFO 中，原简介开头带番号的有 163 个，全部是 `FC2-PPV-编号` 这一种写法。这次修改只影响这些简介。

## Notes

- Changed files：`scripts/nfo_retranslate.py`、`docs/nfo-retranslate.md`、`tests/nfo_retranslate/test_cli.py`，以及本日志。
- 还没做：提交、合并、推送、部署；部署之后再开新一轮翻译，补翻跳过的 78 部和失败的字段。没写回的部分不在跨运行记录里，新一轮会自动选中。超过 60 字的 141 个标题怎么处理，等用户定。
- Rollback：`git revert` 这次提交，再重新部署。
