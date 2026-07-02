## Imported Claude Cowork project instructions

## 项目背景
这是对 18x_rawdata 项目的重构版本（18x_v2）。
原项目路径：/Users/wangyichuan/Desktop/wangcodemac/18x_rawdata

## 开发环境
- 开发机：macOS（本地）
- 生产环境：Unraid Docker，服务器 root@192.168.70.138，SSH密钥已配置
- 主要在本地开发和测试，功能稳定后再部署到 Unraid

## 115 API 说明
- 复杂的函数优先参考 p115client 仓库：https://github.com/ChenyangGao/p115client，但是p115基于cookies调用更多。
- 115open需要 access_token 和 refresh_token 才能调用 API，文档参考https://www.yuque.com/115yun/open
- .env 中已提供 app_id 等凭据信息
- 项目启动时必须先执行 token 检查 / 账号授权流程：
  · 检查现有 token 是否有效
  · 无效则用 app_id 走授权流程获取新 token
  · 授权成功后再启动主服务
- 保留原项目的 http-cookies 扫码获取流程，这是一个独立功能模块，

## 开发原则
- 重构时对照 18x_rawdata 的功能，不得丢失已有功能
- 每次新增模块前先确认功能清单是否完整
- Docker 部署配置放在 docker/ 目录，保持本地和容器环境兼容
- 代码注释使用中文
