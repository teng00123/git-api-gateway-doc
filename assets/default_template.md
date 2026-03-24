### 描述

$description

### 请求头

```javascript
'X-Bkapi-Authorization': {"bk_app_code": "abc", "bk_app_secret": "test", "bk_username":"wxid"}
```

- bk_app_code与bk_app_secret 需要在蓝鲸开发者中心申请
- bk_username：是调用用户名，如果是平台级别的调用需要提前申请虚拟账号


### 输入参数
$request_params

### 调用示例
```bash
curl -X '$method' \
  'http://example.com/$path' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -H 'X-Bkapi-Authorization: {"bk_app_code": "abc", "bk_app_secret": "test", "bk_username":"wxid"}' \
  -d '{}'
```

### 请求参数示例


$request_example


### 响应示例

$response_example


### 响应参数说明
$response_params