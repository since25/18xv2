# 添加云下载BT任务

## 基本信息

- Path：`POST 域名 + /open/offline/add_task_bt`
- Method：`POST`
- 接口描述：添加云下载 BT 任务。

## 请求参数

**Headers**

| 参数名称 | 参数值 | 是否必须 | 示例 |
| --- | --- | --- | --- |
| `Authorization` | `Bearer access_token` | 是 | `Bearer abcdefghijklmnopqrstuvwxyz` |

**Body(form-data)**

| 参数名称 | 参数类型 | 是否必须 | 备注 |
| --- | --- | --- | --- |
| `info_hash` | string | 是 | BT 任务 hash |
| `wanted` | string | 是 | BT 任务选中下载文件索引，使用半角逗号分隔 |
| `save_path` | string | 是 | BT 任务文件保存路径 |
| `torrent_sha1` | string | 是 | BT 种子 SHA1 |
| `pick_code` | string | 是 | BT 种子的提取码 |
| `wp_path_id` | string | 否 | 保存目标文件夹 ID |

## 注意事项

- `wp_path_id` 不传时默认保存到根目录。
- `save_path` 表示 `wp_path_id` 所在文件夹下的相对路径。
- 如果 `wp_path_id` 不传，或传的是云下载文件夹 ID，且 `save_path` 传入 `A/B`，则最终下载路径为根目录下的 `A/B/`。

## 返回数据

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `state` | bool | 操作结果状态值，`true` 成功，`false` 失败 |
| `message` | string | 操作返回消息，成功时为空 |
| `code` | int | 操作返回号码，成功时返回 `0` |
| `data` | array | 数据 |

> 更新：2025-06-06 17:55:23
> 原文：[语雀链接](https://www.yuque.com/115yun/open/svfe4unlhayvluly)
