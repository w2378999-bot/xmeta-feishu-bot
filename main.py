import hashlib
import json
import os
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# 环境变量
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
FEISHU_VERIFY_TOKEN = os.environ.get("FEISHU_VERIFY_TOKEN", "")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY")
DIFY_API_URL = os.environ.get("DIFY_API_URL", "https://api.dify.ai/v1")

# 用于记录已处理的消息ID（防重复处理）
processed_messages = set()

def get_feishu_token():
    """获取飞书 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    })
    return resp.json().get("tenant_access_token")

def send_feishu_message(receive_id, receive_id_type, content, msg_type="text"):
    """发送飞书消息"""
    token = get_feishu_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    params = {"receive_id_type": receive_id_type}
    
    if msg_type == "text":
        body = json.dumps({"text": content})
    else:
        body = content
    
    data = {
        "receive_id": receive_id,
        "msg_type": msg_type,
        "content": body
    }
    resp = requests.post(url, headers=headers, params=params, json=data)
    return resp.json()

def call_dify(user_message, user_id, conversation_id=None):
    """调用 Dify Chatflow API"""
    url = f"{DIFY_API_URL}/chat-messages"
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": {},
        "query": user_message,
        "response_mode": "blocking",
        "user": user_id,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    data = resp.json()
    return data.get("answer", "抱歉，暂时无法获取回答，请稍后重试。"), data.get("conversation_id")

# 存储用户会话ID（简单内存存储，重启后重置）
user_conversations = {}

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    
    # 1. URL 验证（飞书首次验证）
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})
    
    # 2. 处理消息事件
    if data.get("schema") == "2.0":
        header = data.get("header", {})
        event = data.get("event", {})
        event_type = header.get("event_type")
        
        # 只处理消息接收事件
        if event_type != "im.message.receive_v1":
            return jsonify({"code": 0})
        
        message = event.get("message", {})
        message_id = message.get("message_id", "")
        
        # 防重复处理
        if message_id in processed_messages:
            return jsonify({"code": 0})
        processed_messages.add(message_id)
        # 只保留最近1000条
        if len(processed_messages) > 1000:
            processed_messages.pop()
        
        # 解析消息内容
        msg_type = message.get("message_type")
        if msg_type != "text":
            return jsonify({"code": 0})  # 只处理文本消息
        
        try:
            content = json.loads(message.get("content", "{}"))
            user_text = content.get("text", "").strip()
            # 去掉@机器人的前缀
            if user_text.startswith("@"):
                user_text = " ".join(user_text.split()[1:]).strip()
        except:
            return jsonify({"code": 0})
        
        if not user_text:
            return jsonify({"code": 0})
        
        # 获取发送方信息
        sender = event.get("sender", {})
        sender_id = sender.get("sender_id", {}).get("open_id", "anonymous")
        
        # 判断消息来源（单聊 or 群聊）
        chat_type = message.get("chat_type")  # "p2p" or "group"
        chat_id = message.get("chat_id")
        
        if chat_type == "p2p":
            receive_id = sender_id
            receive_id_type = "open_id"
        else:
            receive_id = chat_id
            receive_id_type = "chat_id"
        
        # 先发送"正在思考"提示
        send_feishu_message(receive_id, receive_id_type, "⏳ 正在查询，请稍候...")
        
        # 调用 Dify
        conv_id = user_conversations.get(sender_id)
        answer, new_conv_id = call_dify(user_text, sender_id, conv_id)
        user_conversations[sender_id] = new_conv_id
        
        # 回复用户
        send_feishu_message(receive_id, receive_id_type, answer)
    
    return jsonify({"code": 0})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": int(time.time())})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
