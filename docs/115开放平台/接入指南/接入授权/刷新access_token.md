# 刷新 access_token

## 刷新 access_token

### 基本信息

**接口名称：**刷新 access_token
**接口路径：**POST https://passportapi.115.com/open/refreshToken
### 备注

请勿频繁刷新，否则列入频控。
### 请求参数

**Headers**

| 参数名称 | 参数值 | 是否必须 | 示例 | 备注 |
| --- | --- | --- | --- | --- |
| Content-Type | application/x-www-form-urlencoded | 是 | | |

**Body**

| 参数名称 | 参数类型 | 是否必须 | 示例 | 备注 |
| --- | --- | --- | --- | --- |
| refresh_token | text | 是 | | 刷新的凭证 |

### 返回数据

| 名称 | 类型 | 是否必须 | 默认值 | 备注 | 其他信息 |
| --- | --- | --- | --- | --- | --- |
| state | number | 非必须 | | | |
| code | number | 非必须 | | | |
| message | string | 非必须 | | | |
| data | object | 非必须 | | | |
| ├─ access_token | string | 非必须 | | **新的**access_token，同时刷新有效期 | |
| ├─ refresh_token | string | 非必须 | | **新的**refresh_token，**有效期**不延长不改变 | |
| ├─ expires_in | number | 非必须 | | access_token 有效期，单位秒 | mock: 2592000 |
| error | string | 非必须 | | | |
| errno | number | 非必须 | | | |
> 更新: 2025-04-02 11:29:22
> 原文: <https://www.yuque.com/115yun/open/opnx8yezo4at2be6>