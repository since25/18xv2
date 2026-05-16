# 解析BT种子

## 基本信息

- Path：`POST 域名 + /open/offline/torrent`
- Method：`POST`
- 接口描述：解析 BT 种子。

## 请求参数

**Headers**

| 参数名称 | 参数值 | 是否必须 | 示例 |
| --- | --- | --- | --- |
| `Authorization` | `Bearer access_token` | 是 | `Bearer abcdefghijklmnopqrstuvwxyz` |

**Body(form-data)**

| 参数名称 | 参数类型 | 是否必须 | 备注 |
| --- | --- | --- | --- |
| `torrent_sha1` | string | 是 | BT 种子文件 SHA1，通常需先上传到“云下载/种子文件”文件夹下（非硬性要求） |
| `pick_code` | string | 是 | BT 种子文件提取码 |

## 返回数据

| 字段 | 类型 | 备注 | 其他信息 |
| --- | --- | --- | --- |
| `state` | boolean |  |  |
| `message` | string |  |  |
| `code` | number |  |  |
| `data` | array |  |  |
| `data.file_size` | int | 任务大小 |  |
| `data.torrent_name` | string | 任务名 |  |
| `data.file_count` | int | 文件数 |  |
| `data.info_hash` | string | 任务 SHA1 |  |
| `data.torrent_filelist` | array | 文件列表 |  |
| `data.torrent_filelist[].size` | int | 文件大小 |  |
| `data.torrent_filelist[].path` | string | 文件路径 |  |
| `data.torrent_filelist[].wanted` | int | 文件是否默认选中 |  |

> 更新：2025-06-06 17:54:44
> 原文：[语雀链接](https://www.yuque.com/115yun/open/evez3u50cemoict1)
