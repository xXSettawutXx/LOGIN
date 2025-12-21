from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re

app = Flask(__name__)

# เชื่อมต่อ Database (Render PostgreSQL)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# โครงสร้างตาราง User
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


with app.app_context():
    db.create_all()


@app.route('/register', methods=['POST'])
def register():
    data = request.json
    # 1. ตรวจสอบว่ามีข้อมูลส่งมาไหม
    if not data:
        return jsonify({"message": "No data provided"}), 400

    username = data.get('username', '')
    password = data.get('password', '') # ใช้ .get เพื่อความปลอดภัย

    # 2. เช็คว่ากรอกครบไหม
    if not username or not password:
        return jsonify({"message": "Username and password are required"}), 400
    
    # 3. เช็คตัวอักษรพิเศษ (โค้ดคุณถูกต้องแล้ว)
    if not re.match("^[a-zA-Z0-9]*$", username):
        return jsonify({"message": "Invalid characters in username"}), 400

    # 4. เช็คชื่อซ้ำ (โค้ดคุณถูกต้องแล้ว)
    if User.query.filter_by(username=username).first():
        return jsonify({"message": "Username already exists"}), 400
    
    # 5. เข้ารหัสและบันทึก
    hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
    new_user = User(username=username, password=hashed_pw)
    
    try:
        db.session.add(new_user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Database error"}), 500

    return jsonify({"message": "Success"}), 201


@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user and check_password_hash(user.password, data['password']):
        return jsonify({"message": "Success", "username": user.username}), 200
    return jsonify({"message": "Invalid login"}), 401


if __name__ == "__main__":

    app.run()
