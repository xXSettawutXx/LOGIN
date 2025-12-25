from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from threading import Thread
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
import resend  # เพิ่มการนำเข้า Resend

app = Flask(__name__)

# --- 1. Database Connection ---
db_url = os.getenv('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "connect_args": {"sslmode": "require"}
}

# --- 2. Resend Configuration ---
resend.api_key = os.getenv("RESEND_API_KEY")

db = SQLAlchemy(app)

# --- 3. Database Model ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)

with app.app_context():
    db.create_all()

# --- ฟังก์ชันส่งอีเมลเบื้องหลัง (Resend Async) ---
def send_async_email(username, receiver_email, verify_link):
    try:
        print(f"Resend: Sending email to {receiver_email}...")
        params = {
            "from": "onboarding@resend.dev",  # ช่วงทดสอบต้องใช้ตัวนี้
            "to": receiver_email,
            "subject": "ยืนยันการสมัครสมาชิก - Your Game",
            "html": f"<strong>สวัสดีคุณ {username}</strong><br>คลิกที่นี่เพื่อยืนยันตัวตน: <a href='{verify_link}'>ยืนยันบัญชี</a>",
        }
        resend.Emails.send(params)
        print("Resend: Email sent successfully!")
    except Exception as e:
        print(f"Resend Error: {str(e)}")

# --- 4. Register Route ---
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if not data: return jsonify({"message": "No data"}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    email = data.get('email', '').strip()

    if not all([username, password, email]):
        return jsonify({"message": "All fields required"}), 400
    
    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({"message": "Username or Email already exists"}), 400
    
    try:
        # 1. บันทึกลง Database
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, email=email, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        print(f"DB: User {username} saved.")
        
        # 2. เตรียมข้อมูลและส่งเมลเบื้องหลัง
        verify_link = f"https://{request.host}/verify/{username}"
        
        # ใช้ Thread เพื่อไม่ให้แอปค้าง (ป้องกัน Timeout)
        Thread(target=send_async_email, args=(username, email, verify_link)).start()
        
        return jsonify({"message": "Success! Check your email to verify."}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Server Error: {str(e)}"}), 500

# --- 5. Verify Route ---
@app.route('/verify/<username>')
def verify(username):
    user = User.query.filter_by(username=username).first()
    if user:
        user.is_verified = True
        db.session.commit()
        return "<h1>ยืนยันตัวตนสำเร็จ! เข้าเล่นเกมได้เลย</h1>", 200
    return "<h1>ไม่พบข้อมูลผู้ใช้</h1>", 404

# --- 6. Login Route ---
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    if not data: return jsonify({"message": "No credentials"}), 400
    
    user = User.query.filter_by(username=data.get('username')).first()
    if user and check_password_hash(user.password, data.get('password')):
        if not user.is_verified:
            return jsonify({"message": "Please verify your email first"}), 401
        return jsonify({"message": "Success", "username": user.username}), 200
    return jsonify({"message": "Invalid login"}), 401

if __name__ == "__main__":
    app.run()
