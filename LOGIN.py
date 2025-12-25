from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import random
import string

app = Flask(__name__)
CORS(app)

# =========================
# Database Configuration
# =========================
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

db = SQLAlchemy(app)

# =========================
# Database Models
# =========================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

class Room(db.Model):
    id = db.Column(db.String(6), primary_key=True)
    player1_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    player2_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='playing')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    player1 = db.relationship('User', foreign_keys=[player1_id])
    player2 = db.relationship('User', foreign_keys=[player2_id])

class GameState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(6), db.ForeignKey('room.id'), nullable=False)
    current_turn = db.Column(db.Integer, default=1)
    placed_tiles = db.Column(db.JSON, default=[])
    deck = db.Column(db.JSON, default=[])
    current_tile_p1 = db.Column(db.String(50), nullable=True)
    current_tile_p2 = db.Column(db.String(50), nullable=True)
    player1_score = db.Column(db.Integer, default=0)
    player2_score = db.Column(db.Integer, default=0)
    winner = db.Column(db.Integer, nullable=True)

with app.app_context():
    db.create_all()

# =========================
# Helper Functions
# =========================
def generate_room_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def create_deck():
    deck = []
    distribution = {
        "road_straight_ns": 4,
        "road_straight_nesw": 4,
        "road_straight_senw": 4,
        "road_t_junction": 3,
        "road_curve": 6,
        "river_straight_ns": 3,
        "river_straight_nesw": 3,
        "river_curve": 4,
        "city_road_1": 3,
        "city_road_2": 2,
        "city_full": 1
    }
    
    for tile_id, count in distribution.items():
        deck.extend([tile_id] * count)
    
    random.shuffle(deck)
    return deck

# =========================
# Auth Routes
# =========================
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if not data:
        return jsonify({"message": "No data"}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    email = data.get('email', '').strip()

    if not all([username, password, email]):
        return jsonify({"message": "All fields required"}), 400
    
    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({"message": "Username or Email already exists"}), 400
    
    try:
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, email=email, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({"message": "Success"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error: {str(e)}"}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    if not data:
        return jsonify({"message": "No credentials"}), 400
    
    user = User.query.filter_by(username=data.get('username')).first()
    if user and check_password_hash(user.password, data.get('password')):
        return jsonify({
            "message": "Success",
            "user_id": user.id,
            "username": user.username
        }), 200
    return jsonify({"message": "Invalid login"}), 401

# =========================
# 🚀 Instant Match Route (เข้าเกมเลย)
# =========================
@app.route('/quick_match', methods=['POST'])
def quick_match():
    """เข้าเกมทันที - จับคู่อัตโนมัติ"""
    data = request.json
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({"message": "user_id required"}), 400
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found"}), 404
    
    try:
        # 1. หาห้องที่รอผู้เล่นคนที่ 2 (ห้องที่ไม่เต็ม)
        waiting_room = Room.query.filter(
            Room.status == 'waiting',
            Room.player1_id != user_id  # ไม่ใช่ห้องของตัวเอง
        ).first()
        
        if waiting_room:
            # 🎉 เจอห้องรอ! เข้าไปเลย
            waiting_room.player2_id = user_id
            waiting_room.status = 'playing'
            
            # สร้าง game state
            deck = create_deck()
            game_state = GameState(
                room_id=waiting_room.id,
                current_turn=1,
                placed_tiles=[{
                    "q": 0, "r": 0,
                    "tile_id": "starter_y_junction",
                    "player": 0,
                    "rotation": 0
                }],
                deck=deck,
                current_tile_p1=deck.pop(0) if deck else None,
                current_tile_p2=deck.pop(0) if deck else None
            )
            db.session.add(game_state)
            db.session.commit()
            
            return jsonify({
                "message": "Match found",
                "room_id": waiting_room.id,
                "player_number": 2
            }), 200
            
        else:
            # ไม่มีห้องรอ → สร้างห้องใหม่รอคนอื่น
            room_id = generate_room_id()
            new_room = Room(
                id=room_id,
                player1_id=user_id,
                player2_id=user_id,  # ชั่วคราว (จะถูกแทนที่)
                status='waiting'
            )
            db.session.add(new_room)
            db.session.commit()
            
            return jsonify({
                "message": "Waiting for opponent",
                "room_id": room_id,
                "player_number": 1
            }), 200
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error: {str(e)}"}), 500

# =========================
# Game State Routes
# =========================
@app.route('/game/state/<room_id>', methods=['GET'])
def get_game_state(room_id):
    """ดู game state"""
    game = GameState.query.filter_by(room_id=room_id).first()
    room = Room.query.get(room_id)
    
    if not room:
        return jsonify({"message": "Room not found"}), 404
    
    # ถ้ายังไม่มี game state (ยังรอผู้เล่นคนที่ 2)
    if not game:
        return jsonify({
            "room_id": room_id,
            "status": room.status,
            "message": "Waiting for player 2"
        }), 200
    
    return jsonify({
        "room_id": room_id,
        "status": room.status,
        "current_turn": game.current_turn,
        "placed_tiles": game.placed_tiles,
        "current_tile_p1": game.current_tile_p1,
        "current_tile_p2": game.current_tile_p2,
        "player1_score": game.player1_score,
        "player2_score": game.player2_score,
        "winner": game.winner,
        "tiles_remaining": len(game.deck) if game.deck else 0
    }), 200

@app.route('/game/place_tile', methods=['POST'])
def place_tile():
    """วาง tile"""
    data = request.json
    room_id = data.get('room_id')
    user_id = data.get('user_id')
    q = data.get('q')
    r = data.get('r')
    tile_id = data.get('tile_id')
    rotation = data.get('rotation', 0)
    
    if not all([room_id, user_id, q is not None, r is not None, tile_id]):
        return jsonify({"message": "Missing parameters"}), 400
    
    game = GameState.query.filter_by(room_id=room_id).first()
    room = Room.query.get(room_id)
    
    if not game or not room:
        return jsonify({"message": "Game not found"}), 404
    
    # ตรวจสอบเทิร์น
    if game.current_turn == 1 and room.player1_id != user_id:
        return jsonify({"message": "Not your turn"}), 403
    if game.current_turn == 2 and room.player2_id != user_id:
        return jsonify({"message": "Not your turn"}), 403
    
    try:
        # บันทึก tile
        placed = {
            "q": q,
            "r": r,
            "tile_id": tile_id,
            "player": game.current_turn,
            "rotation": rotation
        }
        
        if game.placed_tiles is None:
            game.placed_tiles = []
        
        game.placed_tiles.append(placed)
        
        # อัพเดทคะแนน
        if game.current_turn == 1:
            game.player1_score += 1
        else:
            game.player2_score += 1
        
        # จั่ว tile ใหม่
        if game.deck and len(game.deck) > 0:
            new_tile = game.deck.pop(0)
            if game.current_turn == 1:
                game.current_tile_p1 = new_tile
            else:
                game.current_tile_p2 = new_tile
        else:
            # จบเกม
            if game.player1_score > game.player2_score:
                game.winner = 1
            elif game.player2_score > game.player1_score:
                game.winner = 2
            else:
                game.winner = 0
            room.status = 'finished'
        
        # สลับเทิร์น
        game.current_turn = 2 if game.current_turn == 1 else 1
        
        # Mark for update
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(game, 'placed_tiles')
        flag_modified(game, 'deck')
        
        db.session.commit()
        
        return jsonify({
            "message": "Tile placed",
            "current_turn": game.current_turn,
            "game_over": room.status == 'finished',
            "winner": game.winner
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error: {str(e)}"}), 500

# =========================
# Debug Routes
# =========================
@app.route('/debug/rooms', methods=['GET'])
def debug_rooms():
    rooms = Room.query.all()
    return jsonify([{
        "room_id": r.id,
        "status": r.status,
        "player1": r.player1.username,
        "player2": r.player2.username if r.player2_id != r.player1_id else "Waiting..."
    } for r in rooms]), 200

@app.route('/debug/clear', methods=['POST'])
def debug_clear():
    """ลบข้อมูลทั้งหมด (สำหรับทดสอบ)"""
    try:
        GameState.query.delete()
        Room.query.delete()
        db.session.commit()
        return jsonify({"message": "All rooms cleared"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True)
