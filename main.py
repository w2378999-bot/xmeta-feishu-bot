import json
import os
import time
import requests
import threading
from flask import Flask, request, jsonify

app = Flask(__name__)

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
FEISHU_VERIFY_TOKEN = os.environ.get("FEISHU_VERIFY_TOKEN", "")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY")
DIFY_API_URL = os.environ.get("DIFY_API_URL", "https://api.dify.ai/v1")

processed_messages = set()
user_conversations = {}

def get_feishu_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    })
    result = resp.json()
    print(f"[token] code={result.get('code')} msg={result.get('msg')}")
    return result.get("tenant_access_token")

def send_feishu_message(receive_id, receive_id_type, content):
    token = get_feishu_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    params = {"receive_id_type": receive_id_type}
    data = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": content})
    }
    resp = requests.post(url, headers=headers, params=params, json=data)
    print(f"[send_msg] receive_id={receive_id} type={receive_id_type} status={resp.status_code} body={resp.text}")
    return resp.json()

def call_dify(user_message, user_id, conversation_id=None):
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
    
    print(f"[dify] calling with query='{user_message}' user={user_id}")
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    print(f"[dify] status={resp.status_code} body={resp.text[:500]}")
    data = resp.json()
    return data.get("answer", "抱歉，暂时无法获取回答，请稍后重试。"), data.get("conversation_id")

def handle_message(receive_id, receive_id_type, user_text, sender_id):
    try:
        print(f"[handle] receive_id={receive_id} type={receive_id_type} text='{user_text}' sender={sender_id}")
        send_feishu_message(receive_id, receive_id_type, "⏳ 正在查询，请稍候...")
        conv_id = user_conversations.get(sender_id)
        answer, new_conv_id = call_dify(user_text, sender_id, conv_id)
        user_conversations[sender_id] = new_conv_id
        send_feishu_message(receive_id, receive_id_type, answer)
        print(f"[handle] done, answer='{answer[:100]}'")
    except Exception as e:
        print(f"[error] handle_message failed: {e}")
        try:
            send_feishu_message(receive_id, receive_id_type, "❌ 处理出错，请稍后重试。")
        except:
            pass

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print(f"[webhook] raw data: {json.dumps(data, ensure_ascii=False)[:1000]}")

    # URL 验证
    if data.get("type") == "url_verification":
        print("[webhook] url_verification challenge")
        return jsonify({"challenge": data.get("challenge")})

    if data.get("schema") == "2.0":
        header = data.get("header", {})
        event = data.get("event", {})
        event_type = header.get("event_type")
        print(f"[webhook] event_type={event_type}")

        if event_type != "im.message.receive_v1":
            return jsonify({"code": 0})

        message = event.get("message", {})
        message_id = message.get("message_id", "")
        print(f"[webhook] message_id={message_id}")

        # 防重复
        if message_id in processed_messages:
            print(f"[webhook] duplicate message_id={message_id}, skip")
            return jsonify({"code": 0})
        processed_messages.add(message_id)
        if len(processed_messages) > 1000:
            processed_messages.clear()

        msg_type = message.get("message_type")
        print(f"[webhook] msg_type={msg_type}")
        if msg_type != "text":
            return jsonify({"code": 0})

        try:
            raw_content = message.get("content", "{}")
            print(f"[webhook] raw_content={raw_content}")
            content = json.loads(raw_content)
            user_text = content.get("text", "").strip()
            print(f"[webhook] user_text before strip='{user_text}'")
            if user_text.startswith("@"):
                user_text = " ".join(user_text.split()[1:]).strip()
            print(f"[webhook] user_text after strip='{user_text}'")
        except Exception as e:
            print(f"[webhook] parse error: {e}")
            return jsonify({"code": 0})

        if not user_text:
            print("[webhook] user_text is empty, skip")
            return jsonify({"code": 0})

        sender = event.get("sender", {})
        sender_id = sender.get("sender_id", {}).get("open_id", "anonymous")
        print(f"[webhook] sender_id={sender_id}")

        chat_type = message.get("chat_type")
        chat_id = message.get("chat_id")
        print(f"[webhook] chat_type={chat_type} chat_id={chat_id}")

        if chat_type == "p2p":
            receive_id = sender_id
            receive_id_type = "open_id"
        else:
            receive_id = chat_id
            receive_id_type = "chat_id"

        thread = threading.Thread(
            target=handle_message,
            args=(receive_id, receive_id_type, user_text, sender_id)
        )
        thread.daemon = True
        thread.start()
        print(f"[webhook] thread started for sender={sender_id}")

    return jsonify({"code": 0})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": int(time.time())})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
