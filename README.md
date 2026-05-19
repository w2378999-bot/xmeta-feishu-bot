# X-META 飞书政策助手机器人

## 部署到 Railway

1. 把这个仓库推到 GitHub（私有仓库）
2. Railway → New Project → GitHub Repository → 选择这个仓库
3. 在 Railway 的 Variables 里填入以下环境变量：

| 变量名 | 值 |
|---|---|
| FEISHU_APP_ID | 飞书后台的 App ID |
| FEISHU_APP_SECRET | 飞书后台的 App Secret |
| FEISHU_VERIFY_TOKEN | 飞书事件订阅里的 Verification Token |
| DIFY_API_KEY | Dify 的 API Key |
| DIFY_API_URL | https://api.dify.ai/v1 |

4. 部署完成后，Railway 会给你一个域名，格式是 `https://xxx.railway.app`
5. 回到飞书后台 → 事件与回调 → 配置 Webhook URL 为 `https://xxx.railway.app/webhook`

## 本地测试

```bash
pip install -r requirements.txt
cp .env.example .env  # 填入真实值
python main.py
```
