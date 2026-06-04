# PPT / PSD 生成接口文档

本文档说明可编辑文件生成接口的调用方式。PPT 和 PSD 生成都是异步任务：先提交任务，再通过任务查询接口轮询结果，完成后通过返回的文件地址下载。

## 鉴权

所有任务提交和查询接口都需要携带 API Key：

```http
Authorization: Bearer <你的 API Key>
```

本地默认示例：

```text
Authorization: Bearer chatgpt2api
```

## 提交 PPT 生成任务

```http
POST /v1/ppt/generations
Content-Type: application/json
```

请求体：

```json
{
  "client_task_id": "ppt-test-001",
  "prompt": "生成一个产品介绍 PPT，科技风，5 页",
  "base64_images": []
}
```

参数说明：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `client_task_id` | string | 否 | 客户端自定义任务 ID。不传时后端自动生成。重复提交同一个 ID 会返回已有任务。 |
| `prompt` | string | 否 | PPT 生成需求。为空时会使用后端内置默认提示词。 |
| `base64_images` | string[] | 否 | 参考图片数组，支持纯 base64 或 `data:image/png;base64,...` 格式。PPT 可不传图片。 |

curl 示例：

```bash
curl http://localhost:8000/v1/ppt/generations \
  -H "Authorization: Bearer chatgpt2api" \
  -H "Content-Type: application/json" \
  -d '{
    "client_task_id": "ppt-test-001",
    "prompt": "生成一个产品介绍 PPT，科技风，5 页",
    "base64_images": []
  }'
```

## 提交 PSD 生成任务

```http
POST /v1/psd/generations
Content-Type: application/json
```

请求体：

```json
{
  "client_task_id": "psd-test-001",
  "prompt": "把这张海报拆成可编辑 PSD 图层",
  "base64_images": [
    "data:image/png;base64,xxxx"
  ]
}
```

参数说明：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `client_task_id` | string | 否 | 客户端自定义任务 ID。不传时后端自动生成。重复提交同一个 ID 会返回已有任务。 |
| `prompt` | string | 否 | PSD 生成需求。为空时会使用后端内置默认提示词。 |
| `base64_images` | string[] | 是 | 参考图片数组。PSD 生成至少需要 1 张图片。 |

curl 示例：

```bash
curl http://localhost:8000/v1/psd/generations \
  -H "Authorization: Bearer chatgpt2api" \
  -H "Content-Type: application/json" \
  -d '{
    "client_task_id": "psd-test-001",
    "prompt": "把这张海报拆成可编辑 PSD 图层",
    "base64_images": ["data:image/png;base64,xxxx"]
  }'
```

## 提交响应

提交成功后会立即返回任务信息：

```json
{
  "id": "ppt-test-001",
  "taskId": "ppt-test-001",
  "status": "queued",
  "kind": "ppt",
  "created_at": "2026-06-03 20:00:00",
  "updated_at": "2026-06-03 20:00:00",
  "elapsed_seconds": 0
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `id` / `taskId` | 任务 ID。 |
| `status` | 任务状态，可能是 `queued`、`running`、`success`、`error`。 |
| `kind` | 任务类型，`ppt` 或 `psd`。 |
| `created_at` | 创建时间。 |
| `updated_at` | 最近更新时间。 |
| `elapsed_seconds` | 已耗时秒数。 |
| `result` | 成功后出现，包含文件下载地址。 |
| `error` | 失败后出现，包含错误信息。 |

## 查询任务结果

```http
GET /v1/editable-file-tasks?ids=<任务ID>
```

查询单个任务：

```bash
curl "http://localhost:8000/v1/editable-file-tasks?ids=ppt-test-001" \
  -H "Authorization: Bearer chatgpt2api"
```

查询多个任务：

```bash
curl "http://localhost:8000/v1/editable-file-tasks?ids=ppt-test-001,psd-test-001" \
  -H "Authorization: Bearer chatgpt2api"
```

查询当前 Key 下所有任务：

```bash
curl "http://localhost:8000/v1/editable-file-tasks" \
  -H "Authorization: Bearer chatgpt2api"
```

成功响应示例：

```json
{
  "items": [
    {
      "id": "ppt-test-001",
      "taskId": "ppt-test-001",
      "status": "success",
      "kind": "ppt",
      "created_at": "2026-06-03 20:00:00",
      "updated_at": "2026-06-03 20:05:30",
      "elapsed_seconds": 330,
      "result": {
        "conversation_id": "abc123",
        "primary_url": "/files/ppt/user-xxx:ppt-test-001/output.pptx",
        "zip_url": "/files/ppt/user-xxx:ppt-test-001/assets.zip"
      }
    }
  ],
  "missing_ids": []
}
```

失败响应示例：

```json
{
  "items": [
    {
      "id": "psd-test-001",
      "taskId": "psd-test-001",
      "status": "error",
      "kind": "psd",
      "created_at": "2026-06-03 20:00:00",
      "updated_at": "2026-06-03 20:01:00",
      "elapsed_seconds": 60,
      "error": "base64_images is empty"
    }
  ],
  "missing_ids": []
}
```

## 下载文件

任务成功后，使用 `result.primary_url` 和 `result.zip_url` 下载文件。

```bash
curl -L "http://localhost:8000/files/ppt/user-xxx:ppt-test-001/output.pptx" \
  -o output.pptx
```

```bash
curl -L "http://localhost:8000/files/ppt/user-xxx:ppt-test-001/assets.zip" \
  -o assets.zip
```

返回文件说明：

| 字段 | PPT 任务 | PSD 任务 |
| --- | --- | --- |
| `primary_url` | PPT 文件地址 | PSD 文件地址 |
| `zip_url` | 素材包 ZIP 地址 | 图层素材 ZIP 地址 |

## 注意事项

- 任务是异步执行，提交接口不会等待生成完成。
- PSD 任务必须传 `base64_images`，PPT 任务可以不传。
- 当前生成使用后端固定模型 `gpt-5-5-thinking`。
- 后端会从 Plus / Team / Pro / Enterprise 账号中选择可用账号执行任务。
- 如果服务重启，未完成任务会被标记为 `error`，错误信息为“服务已重启，未完成的任务已中断”。
