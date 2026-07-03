# API 调用示例

本文档说明当前程序对外暴露的 OpenAI 兼容接口调用方式。

默认服务地址示例：

```text
https://free-api.yccc.me
```

本地开发地址示例：

```text
http://localhost:8000
```

所有 AI 接口都需要携带鉴权头：

```http
Authorization: Bearer <auth-key>
```

如果使用当前默认配置，示例中的密钥为：

```text
chatgpt2api
```

也可以使用兼容请求头：

```http
x-api-key: <auth-key>
```

或：

```http
api-key: <auth-key>
```

## 查询模型

```powershell
curl.exe "https://free-api.yccc.me/v1/models" `
  -H "Authorization: Bearer chatgpt2api"
```

返回的模型列表以接口实际结果为准，常用图片模型：

```text
gpt-image-2
codex-gpt-image-2
auto
```

## 文生图

接口：

```text
POST /v1/images/generations
```

基础调用：

```powershell
curl.exe -X POST "https://free-api.yccc.me/v1/images/generations" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer chatgpt2api" `
  -d '{
    "model": "gpt-image-2",
    "prompt": "生成一张雨夜东京街头的赛博朋克猫",
    "n": 1,
    "response_format": "url"
  }'
```

返回 base64：

```powershell
curl.exe -X POST "https://free-api.yccc.me/v1/images/generations" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer chatgpt2api" `
  -d '{
    "model": "gpt-image-2",
    "prompt": "一只漂浮在太空里的猫",
    "n": 1,
    "response_format": "b64_json"
  }'
```

带分辨率：

```powershell
curl.exe -X POST "https://free-api.yccc.me/v1/images/generations" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer chatgpt2api" `
  -d '{
    "model": "gpt-image-2",
    "prompt": "生成一张电影感宽屏科幻城市概念图",
    "n": 1,
    "size": "1536x1024",
    "quality": "auto",
    "response_format": "url"
  }'
```

竖图示例：

```json
{
  "model": "gpt-image-2",
  "prompt": "生成一张手机壁纸，赛博朋克城市",
  "n": 1,
  "size": "1024x1536",
  "quality": "auto",
  "response_format": "url"
}
```

4K 示例：

```json
{
  "model": "gpt-image-2",
  "prompt": "生成一张 4K 科幻城市概念图",
  "n": 1,
  "size": "3840x2160",
  "quality": "auto",
  "response_format": "url"
}
```

说明：

- `n` 支持 `1-4`。
- `response_format` 可用 `url` 或 `b64_json`。
- `size` 会进入当前程序的图片生成流程，并作为尺寸要求传递给后端。
- 最终图片是否严格等于请求分辨率，取决于后端账号、模型能力和上游返回结果。

## 图片编辑

接口：

```text
POST /v1/images/edits
```

上传本地图片：

```powershell
curl.exe -X POST "https://free-api.yccc.me/v1/images/edits" `
  -H "Authorization: Bearer chatgpt2api" `
  -F "model=gpt-image-2" `
  -F "prompt=把这张图改成赛博朋克夜景风格，保留主体构图" `
  -F "n=1" `
  -F "size=1024x1536" `
  -F "quality=auto" `
  -F "response_format=url" `
  -F "image=@C:\Users\Administrator\Desktop\input.png"
```

使用图片 URL：

```powershell
curl.exe -X POST "https://free-api.yccc.me/v1/images/edits" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer chatgpt2api" `
  -d '{
    "model": "gpt-image-2",
    "prompt": "把图片改成动漫海报风格，保留人物姿势",
    "n": 1,
    "size": "1024x1536",
    "quality": "auto",
    "response_format": "url",
    "images": [
      {
        "image_url": "https://example.com/input.png"
      }
    ]
  }'
```

多图参考编辑：

```json
{
  "model": "gpt-image-2",
  "prompt": "参考第二张图的色彩风格，重绘第一张图",
  "n": 1,
  "size": "1536x1024",
  "quality": "auto",
  "response_format": "url",
  "images": [
    {
      "image_url": "https://example.com/source.png"
    },
    {
      "image_url": "https://example.com/style.png"
    }
  ]
}
```

说明：

- 表单模式使用 `image=@文件路径` 上传图片。
- JSON 模式使用 `images` 数组传图片 URL。
- 编辑接口同样支持 `size` 和 `quality`。
- 最终输出尺寸不一定严格等于请求值，具体取决于后端能力。

## Chat Completions 兼容接口

接口：

```text
POST /v1/chat/completions
```

当前程序的 Chat Completions 更偏向图片生成场景，不是完整通用聊天代理。

```powershell
curl.exe -X POST "https://free-api.yccc.me/v1/chat/completions" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer chatgpt2api" `
  -d '{
    "model": "gpt-image-2",
    "messages": [
      {
        "role": "user",
        "content": "生成一张雨夜东京街头的赛博朋克猫"
      }
    ],
    "n": 1,
    "size": "1024x1024",
    "quality": "auto"
  }'
```

## Python requests 示例

```python
import requests

base_url = "https://free-api.yccc.me"
api_key = "chatgpt2api"

response = requests.post(
    f"{base_url}/v1/images/generations",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": "gpt-image-2",
        "prompt": "生成一张雨夜东京街头的赛博朋克猫",
        "n": 1,
        "size": "1024x1024",
        "quality": "auto",
        "response_format": "url",
    },
    timeout=180,
)

print(response.status_code)
print(response.text)
```

## OpenAI SDK 示例

安装：

```powershell
pip install openai
```

文生图：

```python
from openai import OpenAI

client = OpenAI(
    api_key="chatgpt2api",
    base_url="https://free-api.yccc.me/v1",
)

result = client.images.generate(
    model="gpt-image-2",
    prompt="生成一张雨夜东京街头的赛博朋克猫",
    n=1,
    size="1024x1024",
)

print(result)
```

图片编辑：

```python
from openai import OpenAI

client = OpenAI(
    api_key="chatgpt2api",
    base_url="https://free-api.yccc.me/v1",
)

with open(r"C:\Users\Administrator\Desktop\input.png", "rb") as image:
    result = client.images.edit(
        model="gpt-image-2",
        image=image,
        prompt="把这张图改成赛博朋克夜景风格，保留主体构图",
        n=1,
        size="1024x1536",
    )

print(result)
```

## 常见问题

### 连接被远端强制关闭

如果报错类似：

```text
wsarecv: An existing connection was forcibly closed by the remote host
```

常见原因：

- 程序自己的上游地址配置成了自己的公网域名，形成自我请求循环。
- 图片生成耗时较长，反向代理或客户端超时。
- 后端账号不可用、额度不足或被风控。
- 代理、Cloudflare clearance 或网络链路异常。

如果 `https://free-api.yccc.me` 就是当前程序自身域名，那么客户端可以调用它，但程序内部的上游配置不要再填这个地址。

### 分辨率不生效

当前程序支持传入：

```json
{
  "size": "1024x1024"
}
```

但该值会作为图片生成参数和提示要求进入流程，不能保证所有后端都严格输出对应像素。

### 图片编辑上传失败

检查：

- 文件路径是否真实存在。
- PowerShell 中 `-F "image=@C:\path\input.png"` 路径是否正确。
- 图片文件是否过大。
- 服务端是否能访问 JSON 模式里的远程图片 URL。

