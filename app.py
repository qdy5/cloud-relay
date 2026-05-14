"""
微信消息云中转 — 极简版
部署到 Railway / Render 等平台，提供固定公网 URL
本地 Flask 定时拉取消息
"""
import os
import hashlib
import time
import xml.etree.ElementTree as ET
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, g

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'relay.db')
WECHAT_TOKEN = os.environ.get('WECHAT_TOKEN', 'claudecode2026')


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                openid TEXT DEFAULT '',
                content TEXT NOT NULL,
                pulled INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.commit()


# ═══════════════════════════════════════
# 微信接口：验证 + 接收
# ═══════════════════════════════════════

@app.route('/wechat', methods=['GET', 'POST'])
def wechat():
    if request.method == 'GET':
        signature = request.args.get('signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        echostr = request.args.get('echostr', '')

        tmp = sorted([WECHAT_TOKEN, timestamp, nonce])
        calc = hashlib.sha1(''.join(tmp).encode('utf-8')).hexdigest()

        if calc == signature:
            return echostr
        return 'signature check failed', 403

    # POST: 接收消息
    try:
        root = ET.fromstring(request.data)
        msg_type_el = root.find('MsgType')
        msg_type = msg_type_el.text if msg_type_el is not None else ''

        from_user = root.find('FromUserName')
        to_user = root.find('ToUserName')
        content_el = root.find('Content')

        openid = from_user.text if from_user is not None else ''
        to_oa = to_user.text if to_user is not None else ''
        content = content_el.text if content_el is not None else ''

        if msg_type == 'text' and content:
            db = get_db()
            db.execute(
                'INSERT INTO messages (openid, content) VALUES (?, ?)',
                (openid, content)
            )
            db.commit()

            # 不再发送自动回复，由本地 merged_worker 在2秒内通过客服消息推送真实回复
            return 'success'
            reply = f'''<xml>
<ToUserName><![CDATA[{openid}]]></ToUserName>
<FromUserName><![CDATA[{to_oa}]]></FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{reply_text}]]></Content>
</xml>'''
            return reply, 200, {'Content-Type': 'application/xml; charset=utf-8'}

    except ET.ParseError:
        pass

    return 'success'


# ═══════════════════════════════════════
# 本地拉取接口
# ═══════════════════════════════════════

@app.route('/api/messages')
def api_messages():
    """本地 Flask 调用：拉取未拉取的消息"""
    since_id = request.args.get('since_id', 0, type=int)
    db = get_db()
    msgs = db.execute(
        'SELECT * FROM messages WHERE id > ? ORDER BY id ASC LIMIT 50',
        (since_id,)
    ).fetchall()
    return jsonify({
        'messages': [dict(m) for m in msgs],
    })


@app.route('/api/messages/<int:msg_id>/pulled', methods=['POST'])
def api_mark_pulled(msg_id):
    """标记消息已被本地拉走"""
    db = get_db()
    db.execute('UPDATE messages SET pulled = 1 WHERE id = ?', (msg_id,))
    db.commit()
    return jsonify({'ok': True})


@app.route('/')
def index():
    return jsonify({'status': 'ok', 'service': 'wechat-relay'})


init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
