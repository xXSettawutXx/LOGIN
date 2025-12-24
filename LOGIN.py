from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re

app = Flask(__name__)

# --- 1. การเชื่อมต่อ Database ---
# แก้ไขปัญหา postgres:// ของ Render อัตโนมัติ
db_url = os.getenv('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key_here'

# --- 2. การตั้งค่า Email ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'settawut2548l@gmail.com'
app.config['MAIL_PASSWORD'] = os.getenv('EMAIL_PASS') # ดึงจาก Environment Variable

db = SQLAlchemy(app)
mail = Mail(app)

# --- 3. โครงสร้างตาราง User (เพิ่ม Email และ Verification) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False) # 1 Email ต่อ 1 ID
    password = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False) # เช็คว่ายืนยันเมลยัง

with app.app_context():
    db.create_all()

# --- 4. ระบบ Register ---
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if not data:
        return jsonify({"message": "No data provided"}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    email = data.get('email', '').strip()

    # เช็คว่ากรอกครบไหม
    if not all([username, password, email]):
        return jsonify({"message": "Username, Password, and Email are required"}), 400
    
    # เช็คตัวอักษรพิเศษ
    if not re.match("^[a-zA-Z0-9]*$", username):
        return jsonify({"message": "Invalid characters in username"}), 400

    # เช็คชื่อหรืออีเมลซ้ำ
    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({"message": "Username or Email already exists"}), 400
    
    hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
    new_user = User(username=username, email=email, password=hashed_pw)
    
    try:
        db.session.add(new_user)
        db.session.commit()

        # --- ส่งอีเมลยืนยัน ---
        verify_link = f"https://{request.host}/verify/{username}"
        msg = Message("Confirm your Account",
                      sender=app.config['MAIL_USERNAME'],
                      recipients=[email])
        msg.html = f"สวัสดีคุณ {username},<br>กรุณาคลิกลิงก์เพื่อยืนยันตัวตน: <a href='{verify_link}'>ยืนยันที่นี่</a>"
        mail.send(msg)

        return jsonify({"message": "Success! Check your email to verify."}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error: {str(e)}"}), 500

# --- 5. ระบบ Verify (คลิกจากอีเมล) ---
@app.route('/verify/<username>')
def verify(username):
    user = User.query.filter_by(username=username).first()
    if user:
        user.is_verified = True
        db.session.commit()
        return "<h1>ยืนยันสำเร็จ! เข้าเกมได้เลย</h1>", 200
    return "<h1>ไม่พบผู้ใช้</h1>", 404

# --- 6. ระบบ Login ---
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({"message": "Missing credentials"}), 400

    user = User.query.filter_by(username=data['username']).first()
    
    if user and check_password_hash(user.password, data['password']):
        if not user.is_verified:
            return jsonify({"message": "Please verify your email first"}), 401
        return jsonify({"message": "Success", "username": user.username}), 200
    
    return jsonify({"message": "Invalid login"}), 401

if __name__ == "__main__":
    app.run()
