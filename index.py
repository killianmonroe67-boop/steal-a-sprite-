import os
import random
import time
import sqlite3
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize SQLite Database for persistent user accounts
def init_db():
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, coins INTEGER, multiplier INTEGER, sprites TEXT)''')
    conn.commit()
    conn.close()

init_db()

active_sessions = {}  # Tracks socket_id -> {'username': str, 'is_admin': bool}

# Sprite catalog with Grim & Zero Point at 500x multiplier
SPRITE_CATALOG = {
    'earth': {'name': 'Earth', 'price': 50, 'mult_boost': 1},
    'fire': {'name': 'Fire', 'price': 75, 'mult_boost': 2},
    'water': {'name': 'Water', 'price': 100, 'mult_boost': 3},
    'grim': {'name': 'Grim', 'price': 15000, 'mult_boost': 500},
    'zeropoint': {'name': 'Zero Point', 'price': 15000, 'mult_boost': 500},
    'aura': {'name': 'Aura', 'price': 300, 'mult_boost': 7},
    'king': {'name': 'King', 'price': 400, 'mult_boost': 10},
    'sonic': {'name': 'Sonic', 'price': 500, 'mult_boost': 12},
    'shadow': {'name': 'Shadow', 'price': 650, 'mult_boost': 15},
    'klombo': {'name': 'Klombo', 'price': 800, 'mult_boost': 20},
    'air': {'name': 'Air', 'price': 1000, 'mult_boost': 25},
    'tails': {'name': 'Tails', 'price': 1250, 'mult_boost': 30},
    'duck': {'name': 'Duck', 'price': 1500, 'mult_boost': 35},
    'ghost': {'name': 'Ghost', 'price': 2000, 'mult_boost': 45},
    'demon': {'name': 'Demon', 'price': 2500, 'mult_boost': 60},
    'llama': {'name': 'Llama', 'price': 3000, 'mult_boost': 75},
    'peely': {'name': 'Peely', 'price': 4000, 'mult_boost': 100},
    'ironmouse': {'name': 'Ironmouse', 'price': 5000, 'mult_boost': 125},
    'vinyjr': {'name': 'Vini Jr', 'price': 6500, 'mult_boost': 150},
    'burntpeanut': {'name': 'Burnt Peanut', 'price': 8000, 'mult_boost': 200},
    'batman': {'name': 'Batman', 'price': 10000, 'mult_boost': 250}
}

current_question = {'num1': 0, 'num2': 0, 'answer': 0}

active_server_boost = 1
boost_end_time = 0

def generate_question():
    current_question['num1'] = random.randint(1, 20)
    current_question['num2'] = random.randint(1, 20)
    current_question['answer'] = current_question['num1'] + current_question['num2']

generate_question()

def get_all_online_players():
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    players_data = {}
    for sid, data in active_sessions.items():
        uname = data['username']
        is_admin = data['is_admin']
        c.execute("SELECT coins, multiplier, sprites FROM users WHERE username = ?", (uname,))
        row = c.fetchone()
        if row:
            coins, mult, sprites_str = row
            sprites_list = sprites_str.split(',') if sprites_str else []
            players_data[sid] = {
                'name': uname,
                'coins': coins,
                'multiplier': mult,
                'sprites': [s for s in sprites_list if s],
                'is_admin': is_admin
            }
    conn.close()
    return players_data

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Steal A Sprite - Custom Edition</title>
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        body { 
            font-family: sans-serif; 
            padding: 15px; 
            background: #ffffff; 
            color: #121212; 
            text-align: center; 
        }
        .card { background: #f9f9f9; padding: 15px; margin: 10px 0; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: 1px solid #dcdcdc; color: #121212; }
        button { background: #4CAF50; color: white; border: none; padding: 10px 12px; border-radius: 4px; margin: 4px; cursor: pointer; font-weight: bold; }
        input, select { padding: 8px; font-size: 16px; border-radius: 4px; border: 1px solid #ccc; margin-bottom: 5px; background: #fff; color: #000; display: block; margin-left: auto; margin-right: auto;}
        .admin-tag { color: #d32f2f; font-weight: bold; }
        .admin-section { background: #ffebee; border: 2px solid #ff5252; padding: 10px; margin-top: 10px; border-radius: 6px; }
        .shop-grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; }
        .leaderboard-row { display: flex; justify-content: space-between; padding: 6px 10px; margin: 4px 0; background: #f2f2f2; border-radius: 4px; border-left: 4px solid #4CAF50; color: #121212; }
        .leaderboard-row.top-1 { border-left-color: #ffd700; background: #fffde7; }
        .leaderboard-row.top-2 { border-left-color: #c0c0c0; background: #f5f5f5; }
        .leaderboard-row.top-3 { border-left-color: #cd7f32; background: #fbe9e7; }
    </style>
</head>
<body>
    <h2>🎮 Steal A Sprite (Custom Edition)</h2>
    
    <div id="join-screen" class="card">
        <h3>Login or Register</h3>
        <input type="text" id="username-input" placeholder="Username">
        <input type="password" id="password-input" placeholder="Password">
        <button onclick="loginAccount()">Log In</button>
        <button onclick="registerAccount()" style="background:#2196F3;">Register Account</button>
        <p id="auth-alert" style="color:#d32f2f; font-weight:bold;"></p>
    </div>

    <div id="game-screen" class="card" style="display:none;">
        <h3 id="question">Loading problem...</h3>
        <input type="number" id="answer-input" placeholder="Your answer">
        <button onclick="submitAnswer()">Submit</button>
        <p id="alert" style="color:#d81b60; font-weight:bold;"></p>
        
        <div class="card">
            <h4>Sprite Shop (Infinite Stack)</h4>
            <div class="shop-grid">
                <button onclick="buySprite('earth')">Earth (50c) [+1x]</button>
                <button onclick="buySprite('fire')">Fire (75c) [+2x]</button>
                <button onclick="buySprite('water')">Water (100c) [+3x]</button>
                <button onclick="buySprite('grim')" style="background:#8e24aa;">Grim (15000c) [+500x]</button>
                <button onclick="buySprite('zeropoint')" style="background:#8e24aa;">Zero Point (15000c) [+500x]</button>
                <button onclick="buySprite('aura')">Aura (300c) [+7x]</button>
                <button onclick="buySprite('king')">King (400c) [+10x]</button>
                <button onclick="buySprite('sonic')">Sonic (500c) [+12x]</button>
                <button onclick="buySprite('shadow')">Shadow (650c) [+15x]</button>
                <button onclick="buySprite('klombo')">Klombo (800c) [+20x]</button>
                <button onclick="buySprite('air')">Air (1000c) [+25x]</button>
                <button onclick="buySprite('tails')">Tails (1250c) [+30x]</button>
                <button onclick="buySprite('duck')">Duck (1500c) [+35x]</button>
                <button onclick="buySprite('ghost')">Ghost (2000c) [+45x]</button>
                <button onclick="buySprite('demon')">Demon (2500c) [+60x]</button>
                <button onclick="buySprite('llama')">Llama (3000c) [+75x]</button>
                <button onclick="buySprite('peely')">Peely (4000c) [+100x]</button>
                <button onclick="buySprite('ironmouse')">Ironmouse (5000c) [+125x]</button>
                <button onclick="buySprite('vinyjr')">Vini Jr (6500c) [+150x]</button>
                <button onclick="buySprite('burntpeanut')">Burnt Peanut (8000c) [+200x]</button>
                <button onclick="buySprite('batman')">Batman (10000c) [+250x]</button>
            </div>
            <br>
            <button style="background:#e53935;" onclick="randomSteal()">Random Steal (25c)</button>
        </div>

        <div class="card" style="border: 1px solid #8e24aa;">
            <h4>Secret Codes</h4>
            <input type="text" id="code-input" placeholder="Enter code here...">
            <button onclick="submitSecretCode()" style="background:#8e24aa;">Redeem</button>
        </div>

        <div id="admin-panel" class="card" style="display:none; border: 2px solid #ff5252;">
            <h4 style="color: #d32f2f;">👑 Admin Control Panel</h4>
            
            <div class="admin-section">
                <p style="margin:5px 0; font-size:14px;"><b>Server Multiplier Boosts</b></p>
                <button onclick="triggerBoost(2, 10)">2x (10m)</button>
                <button onclick="triggerBoost(5, 15)">5x (15m)</button>
                <button onclick="triggerBoost(10, 15)">10x (15m)</button>
                <button onclick="triggerBoost(50, 30)">50x (30m)</button>
            </div>

            <div class="admin-section" style="margin-top: 10px;">
                <p style="margin:5px 0; font-size:14px;"><b>Give Sprite To All Players</b></p>
                <select id="admin-sprite-select">
                    <option value="grim">Grim (+500x)</option>
                    <option value="zeropoint">Zero Point (+500x)</option>
                    <option value="earth">Earth (+1x)</option>
                    <option value="batman">Batman (+250x)</option>
                </select>
                <button onclick="giveAllSprite()" style="background:#d32f2f;">Give To Everyone</button>
            </div>
        </div>

        <div class="card">
            <h4>🏆 Global Leaderboard</h4>
            <div id="leaderboard-list"></div>
        </div>

        <div class="card">
            <h4>Active Players List</h4>
            <div id="players-list"></div>
        </div>
    </div>

    <script>
        const socket = io();

        function loginAccount() {
            const username = document.getElementById('username-input').value;
            const password = document.getElementById('password-input').value;
            if(!username || !password) {
                document.getElementById('auth-alert').innerText = "Enter username and password!";
                return;
            }
            socket.emit('login', {username, password});
        }

        function registerAccount() {
            const username = document.getElementById('username-input').value;
            const password = document.getElementById('password-input').value;
            if(!username || !password) {
                document.getElementById('auth-alert').innerText = "Enter username and password!";
                return;
            }
            socket.emit('register', {username, password});
        }

        socket.on('authResponse', data => {
            if(data.success) {
                document.getElementById('join-screen').style.display = 'none';
                document.getElementById('game-screen').style.display = 'block';
                if(data.is_admin) {
                    document.getElementById('admin-panel').style.display = 'block';
                }
            } else {
                document.getElementById('auth-alert').innerText = data.message;
            }
        });

        function submitAnswer() {
            const ans = document.getElementById('answer-input').value;
            socket.emit('submitAnswer', ans);
            document.getElementById('answer-input').value = '';
        }

        function submitSecretCode() {
            const code = document.getElementById('code-input').value;
            socket.emit('submitCode', code);
            document.getElementById('code-input').value = '';
        }

        function buySprite(key) { socket.emit('buySprite', key); }
        function randomSteal() { socket.emit('randomSteal'); }
        
        function triggerBoost(multiplier, minutes) {
            socket.emit('adminServerBoost', { multiplier: multiplier, minutes: minutes });
        }

        function giveAllSprite() {
            const spriteKey = document.getElementById('admin-sprite-select').value;
            socket.emit('adminGiveAllSprite', { spriteKey: spriteKey });
        }

        socket.on('newQuestion', p => {
            document.getElementById('question').innerText = `${p.num1} + ${p.num2} = ?`;
        });

        socket.on('alertMessage', msg => {
            document.getElementById('alert').innerText = msg;
            setTimeout(() => { document.getElementById('alert').innerText = ''; }, 4000);
        });

        socket.on('adminGranted', () => {
            document.getElementById('admin-panel').style.display = 'block';
        });

        function formatSpritesWithCounts(spritesArray) {
            if (!spritesArray || spritesArray.length === 0) return 'None';
            let counts = {};
            spritesArray.forEach(s => {
                if (s) counts[s] = (counts[s] || 0) + 1;
            });
            return Object.entries(counts)
                .map(([name, count]) => count > 1 ? `${name} (x${count})` : name)
                .join(', ');
        }

        socket.on('updatePlayers', players => {
            let sortedPlayers = Object.values(players).sort((a, b) => b.coins - a.coins);

            let lbHtml = '';
            let rawHtml = '';
            
            sortedPlayers.forEach((p, index) => {
                const adminText = p.is_admin ? '<span class="admin-tag">[ADMIN]</span> ' : '';
                const rankClass = index === 0 ? 'top-1' : (index === 1 ? 'top-2' : (index === 2 ? 'top-3' : ''));
                
                lbHtml += `
                    <div class="leaderboard-row ${rankClass}">
                        <span>#${index + 1} ${adminText}<b>${p.name}</b></span>
                        <span>💰 ${p.coins}c | ⚡ ${p.multiplier}x</span>
                    </div>`;
                
                const formattedSprites = formatSpritesWithCounts(p.sprites);
                rawHtml += `<p>${adminText}<b>${p.name}</b> | Coins: ${p.coins} | Mult: ${p.multiplier}x | Sprites: ${formattedSprites}</p>`;
            });

            document.getElementById('leaderboard-list').innerHTML = lbHtml || '<p>No players yet</p>';
            document.getElementById('players-list').innerHTML = rawHtml;
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@socketio.on('register')
def handle_register(data):
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        emit('authResponse', {'success': False, 'message': 'Fields cannot be empty.'})
        return

    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username,))
    if c.fetchone():
        conn.close()
        emit('authResponse', {'success': False, 'message': 'Username already taken!'})
        return

    c.execute("INSERT INTO users (username, password, coins, multiplier, sprites) VALUES (?, ?, 0, 1, '')", (username, password))
    conn.commit()
    conn.close()

    is_admin = (username.upper() == "ADMIN")
    active_sessions[request.sid] = {'username': username, 'is_admin': is_admin}
    emit('authResponse', {'success': True, 'is_admin': is_admin})
    emit('newQuestion', current_question, room=request.sid)
    emit('updatePlayers', get_all_online_players(), broadcast=True)

@socketio.on('login')
def handle_login(data):
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute("SELECT password FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()

    if not row or row[0] != password:
        emit('authResponse', {'success': False, 'message': 'Invalid username or password!'})
        return

    is_admin = (username.upper() == "ADMIN" or password == "ADMINMODE")
    active_sessions[request.sid] = {'username': username, 'is_admin': is_admin}
    emit('authResponse', {'success': True, 'is_admin': is_admin})
    emit('newQuestion', current_question, room=request.sid)
    emit('updatePlayers', get_all_online_players(), broadcast=True)

@socketio.on('submitAnswer')
def handle_answer(ans):
    global active_server_boost, boost_end_time
    session_info = active_sessions.get(request.sid)
    if not session_info: return
    uname = session_info['username']

    if active_server_boost > 1 and time.time() > boost_end_time:
        active_server_boost = 1

    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute("SELECT coins, multiplier FROM users WHERE username = ?", (uname,))
    row = c.fetchone()
    if not row:
        conn.close()
        return
    coins, multiplier = row

    try:
        if int(ans) == current_question['answer']:
            earned = 10 * multiplier * active_server_boost
            coins += earned
            c.execute("UPDATE users SET coins = ? WHERE username = ?", (coins, uname))
            conn.commit()
            conn.close()

            boost_text = f" (Server {active_server_boost}x Boost Active!)" if active_server_boost > 1 else ""
            emit('alertMessage', f"Correct! Earned {earned} coins{boost_text}.", room=request.sid)
            generate_question()
            emit('newQuestion', current_question, broadcast=True)
            emit('updatePlayers', get_all_online_players(), broadcast=True)
        else:
            conn.close()
            emit('alertMessage', "Wrong answer, try again!", room=request.sid)
    except ValueError:
        conn.close()
        emit('alertMessage', "Please enter a number!", room=request.sid)

@socketio.on('buySprite')
def handle_buy(key):
    session_info = active_sessions.get(request.sid)
    if not session_info or key not in SPRITE_CATALOG: return
    uname = session_info['username']

    sprite = SPRITE_CATALOG[key]
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute("SELECT coins, multiplier, sprites FROM users WHERE username = ?", (uname,))
    row = c.fetchone()
    if not row:
        conn.close()
        return
    coins, multiplier, sprites_str = row
    
    if coins >= sprite['price']:
        coins -= sprite['price']
        multiplier += sprite['mult_boost']
        
        current_sprites = sprites_str.split(',') if sprites_str else []
        current_sprites.append(sprite['name'])
        new_sprites_str = ','.join(current_sprites)

        c.execute("UPDATE users SET coins = ?, multiplier = ?, sprites = ? WHERE username = ?", (coins, multiplier, new_sprites_str, uname))
        conn.commit()
        conn.close()

        emit('alertMessage', f"Bought {sprite['name']}! Multiplier is now {multiplier}x!", room=request.sid)
        emit('updatePlayers', get_all_online_players(), broadcast=True)
    else:
        conn.close()
        emit('alertMessage', "Not enough coins!", room=request.sid)

@socketio.on('randomSteal')
def handle_steal():
    session_info = active_sessions.get(request.sid)
    if not session_info: return
    uname = session_info['username']

    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE username = ?", (uname,))
    row = c.fetchone()
    if not row or row[0] < 25:
        conn.close()
        emit('alertMessage', "Need 25 coins to steal!", room=request.sid)
        return

    c.execute("UPDATE users SET coins = coins - 25 WHERE username = ?", (uname,))
    
    other_sids = [sid for sid, data in active_sessions.items() if sid != request.sid]
    if not other_sids:
        conn.commit()
        conn.close()
        emit('alertMessage', "No one else online to steal from!", room=request.sid)
        emit('updatePlayers', get_all_online_players(), broadcast=True)
        return

    target_sid = random.choice(other_sids)
    target_uname = active_sessions[target_sid]['username']

    c.execute("SELECT coins FROM users WHERE username = ?", (target_uname,))
    target_row = c.fetchone()
    target_coins = target_row[0] if target_row else 0

    steal_amount = random.randint(10, 50)
    if target_coins < steal_amount:
        steal_amount = target_coins

    if steal_amount > 0:
        c.execute("UPDATE users SET coins = coins - ? WHERE username = ?", (steal_amount, target_uname))
        c.execute("UPDATE users SET coins = coins + ? WHERE username = ?", (steal_amount, uname))
        conn.commit()
        conn.close()
        emit('alertMessage', f"Stole {steal_amount} coins from {target_uname}!", room=request.sid)
        emit('alertMessage', f"{uname} stole {steal_amount} coins from you!", room=target_sid)
    else:
        conn.commit()
        conn.close()
        emit('alertMessage', f"{target_uname} is broke!", room=request.sid)

    emit('updatePlayers', get_all_online_players(), broadcast=True)

@socketio.on('submitCode')
def handle_code(code):
    session_info = active_sessions.get(request.sid)
    if not session_info: return
    uname = session_info['username']
    
    code = code.strip().upper() 
    conn = sqlite3.connect('game.db')
    c = conn.cursor()

    if code == "FREECOINS":
        c.execute("UPDATE users SET coins = coins + 500 WHERE username = ?", (uname,))
        conn.commit()
        conn.close()
        emit('alertMessage', "💰 CHEAT ACTIVATED: +500 Coins!", room=request.sid)
        emit('updatePlayers', get_all_online_players(), broadcast=True)
        
    elif code == "ADMINMODE":
        c.execute("UPDATE users SET coins = coins + 99999, multiplier = 100 WHERE username = ?", (uname,))
        conn.commit()
        active_sessions[request.sid]['is_admin'] = True
        conn.close()
        emit('alertMessage', "👑 ADMIN PRIVILEGES GRANTED!", room=request.sid)
        emit('adminGranted', room=request.sid)
        emit('updatePlayers', get_all_online_players(), broadcast=True)
        
    else:
        conn.close()
        emit('alertMessage', "Invalid code.", room=request.sid)

@socketio.on('adminServerBoost')
def handle_server_boost(data):
    global active_server_boost, boost_end_time
    session_info = active_sessions.get(request.sid)
    if not session_info or not session_info.get('is_admin'): return
    
    multiplier = int(data['multiplier'])
    minutes = int(data['minutes'])
    
    active_server_boost = multiplier
    boost_end_time = time.time() + (minutes * 60)
    
    emit('alertMessage', f"🚀 SERVER BOOST ACTIVATED: {multiplier}x for {minutes} minutes!", broadcast=True)

@socketio.on('adminGiveAllSprite')
def handle_admin_give_all(data):
    session_info = active_sessions.get(request.sid)
    if not session_info or not session_info.get('is_admin'): return

    sprite_key = data.get('spriteKey')
    if sprite_key not in SPRITE_CATALOG: return

    sprite = SPRITE_CATALOG[sprite_key]
    
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    # Fetch all registered users
    c.execute("SELECT username, multiplier, sprites FROM users")
    all_users = c.fetchall()

    for u_row in all_users:
        u_name, u_mult, u_sprites_str = u_row
        new_mult = u_mult + sprite['mult_boost']
        
        current_sprites = u_sprites_str.split(',') if u_sprites_str else []
        current_sprites.append(sprite['name'])
        new_sprites_str = ','.join(current_sprites)

        c.execute("UPDATE users SET multiplier = ?, sprites = ? WHERE username = ?", (new_mult, new_sprites_str, u_name))

    conn.commit()
    conn.close()

    emit('alertMessage', f"🎁 ADMIN COMMAND: Gave {sprite['name']} (+{sprite['mult_boost']}x) to all players!", broadcast=True)
    emit('updatePlayers', get_all_online_players(), broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in active_sessions:
        del active_sessions[request.sid]
        emit('updatePlayers', get_all_online_players(), broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
