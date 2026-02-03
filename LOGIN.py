import eventlet
eventlet.monkey_patch()

import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
import resend
rooms_players = {}
app = Flask(__name__)
# เพิ่ม async_mode='eventlet' เพื่อให้รองรับ WebSocket บน Render
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- 1. Database Connection ---
db_url = os.getenv('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
    "connect_args": {"sslmode": "require"}
}

resend.api_key = os.getenv("RESEND_API_KEY")
db = SQLAlchemy(app)

# --- 2. Database Model ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)

with app.app_context():
    db.create_all()

# --- 3. Async Email Function ---
def send_async_email(username, receiver_email, verify_link):
    try:
        params = {
            "from": "onboarding@resend.dev",
            "to": receiver_email,
            "subject": "ยืนยันการสมัครสมาชิก",
            "html": f"<strong>สวัสดีคุณ {username}</strong><br>คลิกยืนยัน: <a href='{verify_link}'>ยืนยันบัญชี</a>",
        }
        resend.Emails.send(params)
        print(f"Resend: Sent to {receiver_email}")
    except Exception as e:
        print(f"Resend Error: {str(e)}")

# --- 4. Routes ---
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if not data: return jsonify({"message": "No data"}), 400
    username, password, email = data.get('username','').strip(), data.get('password','').strip(), data.get('email','').strip()
    
    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({"message": "Exists"}), 400
    
    hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
    new_user = User(username=username, email=email, password=hashed_pw)
    db.session.add(new_user)
    db.session.commit()
    
    verify_link = f"https://{request.host}/verify/{username}"
    # ใช้ SocketIO background task แทน Thread ปกติเพื่อความเข้ากันได้กับ eventlet
    socketio.start_background_task(send_async_email, username, email, verify_link)
    return jsonify({"message": "Success"}), 201

@app.route('/verify/<username>')
def verify(username):
    user = User.query.filter_by(username=username).first()
    if user:
        user.is_verified = True
        db.session.commit()
        return "<h1>Verified!</h1>", 200
    return "<h1>Not Found</h1>", 404

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    user = User.query.filter_by(username=username).first()
    
    if user and check_password_hash(user.password, password):
        return jsonify({"message": "Login successful", "username": user.username}), 200
    else:
        return jsonify({"message": "Invalid username or password"}), 401

# --- 5. SocketIO Events (ต้องอยู่ก่อนคำสั่งรัน) ---
@socketio.on('join_game')
def on_join(data):
    username = data.get('username')
    room = data.get('room', 'global_room')
    join_room(room)
    
    if room not in rooms_players:
        rooms_players[room] = []
    
    if username not in rooms_players[room]:
        rooms_players[room].append(username)
        
    # ใครเข้าคนแรก คนนั้นคือคนเริ่ม (Index 0)
    starting_player = rooms_players[room][0]
    
    print(f"Room {room}: {rooms_players[room]}")
    # ส่งบอกทุกคนว่าใครคือคนที่มีสิทธิ์เล่นคนแรก
    emit('turn_switched', {'next_player': starting_player}, room=room)
    
@socketio.on('next_turn')
def handle_next_turn(data):
    room = data.get('room', 'global_room')
    current_user = data.get('username')
    
    players = rooms_players.get(room, [])
    if len(players) < 2:
        emit('turn_switched', {'next_player': current_user}, room=room)
        return

    # คำนวณหาคนถัดไปในรายชื่อ [0] -> [1] -> [0]
    try:
        current_idx = players.index(current_user)
        next_idx = (current_idx + 1) % len(players)
        next_player = players[next_idx]
        
        emit('turn_switched', {'next_player': next_player}, room=room)
    except:
        pass
        
@socketio.on('place_tile')
def handle_place_tile(data):
    # ตรวจสอบว่า data เป็น List หรือไม่ (Godot ชอบส่งมาแบบนี้)
    if isinstance(data, list):
        data = data[0]
        
    print(f"--- SERVER RECEIVED RAW: {data} ---")
    
    room = data.get('room', 'global_room')
    
    # บังคับพิมพ์สถานะห้องว่าเจอไหม
    print(f"Target Room: {room}")
    
    # กระจายข้อมูล
    emit('tile_placed_sync', data, room=room, include_self=False)
    print(f"--- SERVER BROADCASTED SUCCESS ---")
# --- 6. Run ---
if __name__ == "__main__":
    # ใช้พอร์ตที่ Render กำหนด หรือ 10000 เป็นค่าเริ่มต้น
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
# เพิ่มต่อจากฟังก์ชัน handle_place_tile
@socketio.on_error_default
def default_error_handler(e):
    print(f"DEBUG ERROR: {e}")

@socketio.on('message')
def handle_message(msg):
    print(f"DEBUG MESSAGE: {msg}")




