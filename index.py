import os
import random
import time
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

players = {}

# Sprites permanently increase your multiplier when bought
SPRITE_CATALOG = {
    'earth': {'name': 'Earth', 'price': 75, 'mult_boost': 2},
    'sonic': {'name': 'Sonic', 'price': 150, 'mult_boost': 5},
    'fire': {'name': 'Fire', 'price': 250, 'mult_boost': 10},
    'grim': {'name': 'Grim', 'price': 400, 'mult_boost': 25},
    'zeropoint': {'name': 'Zero Point', 'price': 600, 'mult_boost': 50}
}

current_question = {'num1': 0, 'num2': 0, 'answer': 0}

# Server-wide boost state
active_server_boost = 1
boost_end_time = 0

def generate_question():
    current_question['num1'] = random.randint(1, 20)
    current_question['num2'] = random.randint(1, 20)
    current_question['answer'] = current_question['num1'] + current_question['num2']

generate_question()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Steal A Sprite</title>
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        body { 
            font-family: sans-serif; 
            padding: 15px; 
            background: linear-gradient(135deg, #121212, #2c2c2c, #4a4a4a); 
            background-attachment: fixed;
            color: #fff; 
            text-align: center; 
        }
        .card { background: rgba(30, 30, 30, 0.9); padding: 15px; margin: 10px 0; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        button { background: #4CAF50; color: white; border: none; padding: 10px 12px; border-radius: 4px; margin: 4px; cursor: pointer; }
        input { padding: 8px; font-size: 16px; border-radius: 4px; border: 1px solid #444; margin-bottom: 5px; background: #222; color: #fff;}
        .admin-tag { color: #ff5252; font-weight: bold; }
        .admin-section { background: #2a1515; border: 2px solid #ff5252; padding: 10px; margin-top: 10px; border-radius: 6px; }
        .leaderboard-row { display: flex; justify-content: space-between; padding: 6px 10px; margin: 4px 0; background: #252525; border-radius: 4px; border-left: 4px solid #4CAF50; }
        .leaderboard-row.top-1 { border-left-color: #ffd700; }
        .leaderboard-row.top-2 { border-left-color: #c0c0c0; }
        .leaderboard-row.top-3 { border-left-color: #cd7f32; }
    </style>
</head>
<body>
    <h2>🎮 Steal A Sprite Live</h2>
    
    <div id="join-screen" class="card">
        <input type="text" id="name-input" placeholder="Enter your name">
        <button onclick="joinGame()">Join Game</button>
    </div>

    <div id="game-screen" class="card" style="display:none;">
        <h3 id="question">Loading problem...</h3>
        <input type="number" id="answer-input" placeholder="Your answer">
        <button onclick="submitAnswer()">Submit</button>
        <p id="alert" style="color:#ffeb3b; font-weight:bold;"></p>
        
        <div class="card">
            <h4>Shop & Multiplier Upgrades</h4>
            <button onclick="buySprite('earth')">Earth (75c) [+2x]</button>
            <button onclick="buySprite('sonic')">Sonic (150c) [+5x]</button>
            <button onclick="buySprite('fire')">Fire (250c) [+10x]</button>
            <button onclick="buySprite('grim')">Grim (400c) [+25x]</button>
            <button onclick="buySprite('zeropoint')">Zero Point (600c) [+50x]</button>
            <br><br>
            <button style="background:#e53935;" onclick="randomSteal()">Random Steal (25c)</button>
        </div>

        <div class="card" style="border: 1px solid #8e24aa;">
            <h4>Secret Codes</h4>
            <input type="text" id="code-input" placeholder="Enter code here...">
            <button onclick="submitSecretCode()" style="background:#8e24aa;">Redeem</button>
        </div>

        <div id="admin-panel" class="card" style="display:none; border: 2px solid #ff5252;">
            <h4 style="color: #ff5252;">👑 Admin Control Panel</h4>
            
            <div class="admin-section">
                <p style="margin:5px 0; font-size:14px;"><b>Server Multiplier Boosts</b></p>
                <button onclick="triggerBoost(2, 10)">2x (10m)</button>
                <button onclick="triggerBoost(3, 10)">3x (10m)</button>
                <button onclick="triggerBoost(5, 15)">5x (15m)</button>
                <button onclick="triggerBoost(10, 15)">10x (15m)</button>
                <button onclick="triggerBoost(25, 30)">25x (30m)</button>
                <button onclick="triggerBoost(50, 30)">50x (30m)</button>
            </div>

            <div class="admin-section">
                <p style="margin:5px 0; font-size:14px;"><b>Give Everyone a Sprite</b></p>
                <button onclick="giveSpriteAll('earth')">Give Earth</button>
                <button onclick="giveSpriteAll('sonic')">Give Sonic</button>
                <button onclick="giveSpriteAll('fire')">Give Fire</button>
                <button onclick="giveSpriteAll('grim')">Give Grim</button>
                <button onclick="giveSpriteAll('zeropoint')">Give Zero Point</button>
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

        function joinGame() {
            const name = document.getElementById('name-input').value;
            if(!name.trim()) return;
            socket.emit('joinGame', name);
            document.getElementById('join-screen').style.display = 'none';
            document.getElementById('game-screen').style.display = 'block';
        }

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

        function giveSpriteAll(spriteKey) {
            socket.emit('adminGiveSpriteAll', spriteKey);
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

        socket.on('updatePlayers', players => {
            // Sort players by coins for leaderboard
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
                
                rawHtml += `<p>${adminText}<b>${p.name}</b> | Coins: ${p.coins} | Mult: ${p.multiplier}x | Sprites: ${p.sprites.join(', ') || 'None'}</p>`;
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

@socketio.on('joinGame')
def handle_join(name):
    players[request.sid] = {
        'name': name,
        'coins': 0,
        'multiplier': 1,
        'sprites': [],
        'is_admin': False
    }
    emit('newQuestion', current_question)
    emit('updatePlayers', players, broadcast=True)

@socketio.on('submitAnswer')
def handle_answer(ans):
    global active_server_boost, boost_end_time
    p = players.get(request.sid)
    if not p: return
    
    if active_server_boost > 1 and time.time() > boost_end_time:
        active_server_boost = 1

    try:
        if int(ans) == current_question['answer']:
            earned = 10 * p['multiplier'] * active_server_boost
            p['coins'] += earned
            boost_text = f" (Server {active_server_boost}x Boost Active!)" if active_server_boost > 1 else ""
            emit('alertMessage', f"Correct! Earned {earned} coins{boost_text}.", room=request.sid)
            generate_question()
            emit('newQuestion', current_question, broadcast=True)
            emit('updatePlayers', players, broadcast=True)
        else:
            emit('alertMessage', "Wrong answer, try again!", room=request.sid)
    except ValueError:
        emit('alertMessage', "Please enter a number!", room=request.sid)

@socketio.on('buySprite')
def handle_buy(key):
    p = players.get(request.sid)
    if not p or key not in SPRITE_CATALOG: return
    
    sprite = SPRITE_CATALOG[key]
    if p['coins'] >= sprite['price']:
        p['coins'] -= sprite['price']
        p['sprites'].append(sprite['name'])
        p['multiplier'] += sprite['mult_boost']
        emit('alertMessage', f"Bought {sprite['name']}! Multiplier is now {p['multiplier']}x!", room=request.sid)
        emit('updatePlayers', players, broadcast=True)
    else:
        emit('alertMessage', "Not enough coins!", room=request.sid)

@socketio.on('randomSteal')
def handle_steal():
    p = players.get(request.sid)
    if not p: return
    
    if p['coins'] < 25:
        emit('alertMessage', "Need 25 coins to steal!", room=request.sid)
        return
        
    p['coins'] -= 25
    other_sids = [sid for sid in players.keys() if sid != request.sid]
    
    if not other_sids:
        emit('alertMessage', "No one else to steal from!", room=request.sid)
        emit('updatePlayers', players, broadcast=True)
        return
        
    target_sid = random.choice(other_sids)
    target = players[target_sid]
    
    steal_amount = random.randint(10, 50)
    if target['coins'] < steal_amount:
        steal_amount = target['coins']
        
    if steal_amount > 0:
        target['coins'] -= steal_amount
        p['coins'] += steal_amount
        emit('alertMessage', f"Stole {steal_amount} coins from {target['name']}!", room=request.sid)
        emit('alertMessage', f"{p['name']} stole {steal_amount} coins from you!", room=target_sid)
    else:
        emit('alertMessage', f"{target['name']} is broke!", room=request.sid)
        
    emit('updatePlayers', players, broadcast=True)

@socketio.on('submitCode')
def handle_code(code):
    p = players.get(request.sid)
    if not p: return
    
    code = code.strip().upper() 
    
    if code == "FREECOINS":
        p['coins'] += 500
        emit('alertMessage', "💰 CHEAT ACTIVATED: +500 Coins!", room=request.sid)
        emit('updatePlayers', players, broadcast=True)
        
    elif code == "ADMINMODE":
        p['is_admin'] = True
        p['coins'] += 99999
        p['multiplier'] = 100
        emit('alertMessage', "👑 ADMIN PRIVILEGES GRANTED!", room=request.sid)
        emit('adminGranted', room=request.sid)
        emit('updatePlayers', players, broadcast=True)
        
    else:
        emit('alertMessage', "Invalid code.", room=request.sid)

@socketio.on('adminServerBoost')
def handle_server_boost(data):
    global active_server_boost, boost_end_time
    p = players.get(request.sid)
    if not p or not p['is_admin']: return
    
    multiplier = int(data['multiplier'])
    minutes = int(data['minutes'])
    
    active_server_boost = multiplier
    boost_end_time = time.time() + (minutes * 60)
    
    emit('alertMessage', f"🚀 SERVER BOOST ACTIVATED: {multiplier}x for {minutes} minutes!", broadcast=True)

@socketio.on('adminGiveSpriteAll')
def handle_give_sprite_all(sprite_key):
    p = players.get(request.sid)
    if not p or not p['is_admin'] or sprite_key not in SPRITE_CATALOG: return
    
    sprite_name = SPRITE_CATALOG[sprite_key]['name']
    mult_add = SPRITE_CATALOG[sprite_key]['mult_boost']
    
    for sid in players:
        players[sid]['sprites'].append(sprite_name)
        players[sid]['multiplier'] += mult_add
        
    emit('alertMessage', f"🎁 ADMIN GIVEAWAY: Everyone received the {sprite_name} sprite!", broadcast=True)
    emit('updatePlayers', players, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in players:
        del players[request.sid]
        emit('updatePlayers', players, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
