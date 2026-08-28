import os
import random
import time
import sqlite3
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize SQLite Database with shield support
def init_db():
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, coins INTEGER, multiplier INTEGER, sprites TEXT, shield_until REAL)''')
    conn.commit()
    conn.close()

init_db()

active_sessions = {}  # Tracks socket_id -> {'username': str, 'is_admin': bool}
active_trades = {}    # Tracks target_sid -> trade payload

# Sprite catalog including Shields
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
    'batman': {'name': 'Batman', 'price': 10000, 'mult_boost': 250},
    'shield': {'name': 'Shield', 'price': 250, 'mult_boost': 0}
}

SPRITE_NAME_TO_MULT = {v['name']: v['mult_boost'] for v in SPRITE_CATALOG.values()}

# Sprite Variants System
SPRITE_VARIANTS = {
    'Normal': {'mult_multiplier': 1},
    'Shiny': {'mult_multiplier': 2},
    'Golden': {'mult_multiplier': 5},
    'Corrupted': {'mult_multiplier': 10}
}

def roll_sprite_variant():
    # Adjusted odds for easier testing: 50% Normal, 30% Shiny, 15% Golden, 5% Corrupted
    roll = random.random()
    if roll < 0.05:
        return 'Corrupted', 10
    elif roll < 0.20:
        return 'Golden', 5
    elif roll < 0.50:
        return 'Shiny', 2
    else:
        return 'Normal', 1

def get_sprite_multiplier_value(sprite_full_name):
    for variant in ['Shiny', 'Golden', 'Corrupted']:
        if sprite_full_name.startswith(variant + ' '):
            base_name = sprite_full_name[len(variant)+1:]
            base_mult = SPRITE_NAME_TO_MULT.get(base_name, 1)
            variant_multiplier = SPRITE_VARIANTS[variant]['mult_multiplier']
            return base_mult * variant_multiplier
    return SPRITE_NAME_TO_MULT.get(sprite_full_name, 1)

current_question = {'num1': 0, 'num2': 0, 'answer': 0}

active_server_boost = 1
boost_end_time = 0
giveaway_task_active = False

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
        c.execute("SELECT coins, multiplier, sprites, shield_until FROM users WHERE username = ?", (uname,))
        row = c.fetchone()
        if row:
            coins, mult, sprites_str, shield_until = row
            sprites_list = sprites_str.split(',') if sprites_str else []
            is_shielded = shield_until and time.time() < shield_until
            players_data[sid] = {
                'name': uname,
                'coins': coins,
                'multiplier': mult,
                'sprites': [s for s in sprites_list if s],
                'is_admin': is_admin,
                'is_shielded': is_shielded
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
            background: #eef2f5; 
            color: #121212; 
            text-align: center; 
            margin: 0;
        }
        .layout-grid {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 15px;
            max-width: 1400px;
            margin: 0 auto;
        }
        .side-col {
            flex: 1;
            min-width: 250px;
            max-width: 320px;
        }
        .main-col {
            flex: 2;
            min-width: 320px;
            max-width: 650px;
        }
        .card { 
            background: #ffffff; 
            padding: 15px; 
            margin: 10px 0; 
            border-radius: 8px; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.08); 
            border: 1px solid #dcdcdc; 
            color: #121212; 
        }
        button { background: #4CAF50; color: white; border: none; padding: 8px 10px; border-radius: 4px; margin: 3px; cursor: pointer; font-weight: bold; }
        input, select { padding: 8px; font-size: 14px; border-radius: 4px; border: 1px solid #ccc; margin-bottom: 5px; background: #fff; color: #000; display: block; margin-left: auto; margin-right: auto;}
        .admin-tag { color: #d32f2f; font-weight: bold; }
        .shield-tag { color: #00acc1; font-weight: bold; }
        .admin-section { background: #ffebee; border: 2px solid #ff5252; padding: 10px; margin-top: 10px; border-radius: 6px; }
        .shop-grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 4px; }
        .leaderboard-row { display: flex; justify-content: space-between; padding: 6px 10px; margin: 4px 0; background: #f2f2f2; border-radius: 4px; border-left: 4px solid #4CAF50; color: #121212; }
        .leaderboard-row.top-1 { border-left-color: #ffd700; background: #fffde7; }
        .leaderboard-row.top-2 { border-left-color: #c0c0c0; background: #f5f5f5; }
        .leaderboard-row.top-3 { border-left-color: #cd7f32; background: #fbe9e7; }
        
        #chat-box { height: 140px; overflow-y: scroll; background: #fff; border: 1px solid #ccc; border-radius: 4px; padding: 8px; text-align: left; font-size: 14px; margin-bottom: 8px; }
        .chat-msg { margin: 4px 0; border-bottom: 1px solid #eee; padding-bottom: 2px; }

        /* ASMR Keyboard Styles */
        .asmr-keyboard { display: flex; flex-direction: column; gap: 4px; align-items: center; margin-top: 10px; }
        .asmr-row { display: flex; gap: 4px; }
        .asmr-key { 
            width: 24px; height: 28px; background: #333; color: #fff; border-radius: 4px; 
            font-size: 11px; display: flex; align-items: center; justify-content: center; 
            box-shadow: 0 3px 0 #111; cursor: pointer; user-select: none;
        }
        .asmr-key:active, .asmr-key.active { transform: translateY(2px); box-shadow: 0 1px 0 #111; background: #00acc1; }
        .space-key { width: 120px; }

        /* Flappy Canvas Styling */
        #flappyCanvas { background: #70c5ce; border-radius: 6px; border: 2px solid #333; cursor: pointer; }
    </style>
</head>
<body>
    <h2>🎮 Steal A Sprite (Custom Edition)</h2>
    
    <div id="join-screen" class="card" style="max-width: 400px; margin: 0 auto;">
        <h3>Login or Register</h3>
        <input type="text" id="username-input" placeholder="Username">
        <input type="password" id="password-input" placeholder="Password">
        <button onclick="loginAccount()">Log In</button>
        <button onclick="registerAccount()" style="background:#2196F3;">Register Account</button>
        <p id="auth-alert" style="color:#d32f2f; font-weight:bold;"></p>
    </div>

    <div id="game-screen" style="display:none;">
        <div class="layout-grid">
            
            <div class="side-col">
                <div class="card">
                    <h4>⌨️ ASMR Sound Board</h4>
                    <p style="font-size: 12px; color: #666;">Press keys or tap below for crunchy mechanical keyboard ASMR sounds!</p>
                    <div class="asmr-keyboard" id="keyboard-visual">
                        <div class="asmr-row">
                            <div class="asmr-key" data-key="q">Q</div><div class="asmr-key" data-key="w">W</div><div class="asmr-key" data-key="e">E</div>
                            <div class="asmr-key" data-key="r">R</div><div class="asmr-key" data-key="t">T</div><div class="asmr-key" data-key="y">Y</div>
                            <div class="asmr-key" data-key="u">U</div><div class="asmr-key" data-key="i">I</div><div class="asmr-key" data-key="o">O</div><div class="asmr-key" data-key="p">P</div>
                        </div>
                        <div class="asmr-row">
                            <div class="asmr-key" data-key="a">A</div><div class="asmr-key" data-key="s">S</div><div class="asmr-key" data-key="d">D</div>
                            <div class="asmr-key" data-key="f">F</div><div class="asmr-key" data-key="g">G</div><div class="asmr-key" data-key="h">H</div>
                            <div class="asmr-key" data-key="j">J</div><div class="asmr-key" data-key="k">K</div><div class="asmr-key" data-key="l">L</div>
                        </div>
                        <div class="asmr-row">
                            <div class="asmr-key" data-key="z">Z</div><div class="asmr-key" data-key="x">X</div><div class="asmr-key" data-key="c">C</div>
                            <div class="asmr-key" data-key="v">V</div><div class="asmr-key" data-key="b">B</div><div class="asmr-key" data-key="n">N</div><div class="asmr-key" data-key="m">M</div>
                        </div>
                        <div class="asmr-row">
                            <div class="asmr-key space-key" data-key=" ">SPACE</div>
                        </div>
                    </div>
                </div>

                <div class="card">
                    <h4>💬 Live Chat</h4>
                    <div id="chat-box"></div>
                    <input type="text" id="chat-input" placeholder="Type a message..." onkeydown="checkChatEnter(event)">
                    <button onclick="sendChatMessage()" style="background:#2196F3;">Send</button>
                </div>
            </div>

            <div class="main-col">
                <div class="card">
                    <h3 id="question">Loading problem...</h3>
                    <input type="number" id="answer-input" placeholder="Your answer">
                    <button onclick="submitAnswer()">Submit</button>
                    <p id="alert" style="color:#d81b60; font-weight:bold;"></p>
                </div>
                
                <div class="card">
                    <h4>Sprite Shop & Utilities</h4>
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
                        <button onclick="buyShield()" style="background:#00acc1;">Buy Shield (250c) [5m]</button>
                    </div>
                    <br>
                    <button style="background:#e53935;" onclick="stealSprite()">Steal Random Sprite (100c)</button>
                </div>

                <div class="card" style="border: 1px solid #0288d1;">
                    <h4>🤝 Direct Player Trade</h4>
                    <input type="text" id="trade-target" placeholder="Target Username">
                    <input type="text" id="trade-offer" placeholder="Sprite You Give">
                    <input type="text" id="trade-request" placeholder="Sprite You Want">
                    <button onclick="sendTrade()" style="background:#0288d1;">Send Trade Request</button>
                    <div id="trade-notification" style="margin-top:8px;"></div>
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
                        <button onclick="triggerBoost(100, 30)" style="background:#d32f2f;">100x (30m)</button>
                        <button onclick="triggerBoost(1000, 30)" style="background:#b71c1c;">1000x (30m)</button>
                    </div>

                    <div class="admin-section" style="margin-top: 10px;">
                        <p style="margin:5px 0; font-size:14px;"><b>🎉 Lucky Giveaway Event</b></p>
                        <button onclick="triggerGiveawayTime()" style="background:#d32f2f; font-size:14px; padding:10px;">Start Lucky Giveaway (10B Coins every 10m to random player)</button>
                    </div>

                    <div class="admin-section" style="margin-top: 10px;">
                        <p style="margin:5px 0; font-size:14px;"><b>Quick Coin Grants</b></p>
                        <button onclick="adminGiveCoinsAmount(100)" style="background:#d32f2f;">Give 100 Coins (All)</button>
                        <button onclick="adminGiveCoinsAmount(1000)" style="background:#d32f2f;">Give 1000 Coins (All)</button>
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

                    <div class="admin-section" style="margin-top: 10px;">
                        <p style="margin:5px 0; font-size:14px;"><b>Custom Give Coins</b></p>
                        <input type="text" id="admin-coin-target" placeholder="Username (or leave blank for ALL)" style="width:80%;">
                        <input type="number" id="admin-coin-amount" placeholder="Coin Amount" style="width:80%;">
                        <button onclick="adminGiveCoins()" style="background:#d32f2f;">Give Coins</button>
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

            <div class="side-col">
                <div class="card">
                    <h4>🐤 Mini Flappy Bird</h4>
                    <p style="font-size:12px; color:#666;">Click canvas to jump!</p>
                    <canvas id="flappyCanvas" width="220" height="320"></canvas>
                </div>
            </div>

        </div>
    </div>

    <script>
        const socket = io();

        // AUTH
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
                initFlappy();
            } else {
                document.getElementById('auth-alert').innerText = data.message;
            }
        });

        // ASMR SOUND GENERATOR USING WEB AUDIO API
        let audioCtx = null;
        function playAsmrSound() {
            try {
                if(!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                if(audioCtx.state === 'suspended') audioCtx.resume();
                
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(1200 + Math.random() * 400, audioCtx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(150, audioCtx.currentTime + 0.04);
                
                gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.04);
                
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                
                osc.start();
                osc.stop(audioCtx.currentTime + 0.04);
            } catch(e) {}
        }

        document.querySelectorAll('.asmr-key').forEach(key => {
            key.addEventListener('click', () => {
                playAsmrSound();
                key.classList.add('active');
                setTimeout(() => key.classList.remove('active'), 100);
            });
        });

        window.addEventListener('keydown', (e) => {
            playAsmrSound();
            const keyEl = document.querySelector(`.asmr-key[data-key="${e.key.toLowerCase()}"]`);
            if(keyEl) {
                keyEl.classList.add('active');
                setTimeout(() => keyEl.classList.remove('active'), 100);
            }
        });

        // FLAPPY BIRD MINIGAME
        let flappyCanvas, fCtx;
        let birdY = 150, birdV = 0, gravity = 0.2, jump = -4;
        let pipes = [];
        let flappyScore = 0;
        let flappyGameOver = false;

        function initFlappy() {
            flappyCanvas = document.getElementById('flappyCanvas');
            fCtx = flappyCanvas.getContext('2d');
            
            flappyCanvas.addEventListener('click', () => {
                if(flappyGameOver) resetFlappy();
                else birdV = jump;
            });
            
            resetFlappy();
            requestAnimationFrame(flappyLoop);
        }

        function resetFlappy() {
            birdY = 150; birdV = 0; pipes = []; flappyScore = 0; flappyGameOver = false;
        }

        function updateFlappy() {
            if(flappyGameOver) return;
            birdV += gravity;
            birdY += birdV;
            
            if(birdY > flappyCanvas.height - 10 || birdY < 0) flappyGameOver = true;

            if(pipes.length === 0 || pipes[pipes.length - 1].x < flappyCanvas.width - 90) {
                let topH = Math.floor(Math.random() * (flappyCanvas.height - 130)) + 20;
                pipes.push({ x: flappyCanvas.width, top: topH, gap: 75, passed: false });
            }

            pipes.forEach(p => {
                p.x -= 1.5;
                if(p.x < 30 && p.x + 25 > 10) {
                    if(birdY < p.top || birdY > p.top + p.gap) flappyGameOver = true;
                }
                if(!p.passed && p.x + 25 < 10) {
                    flappyScore++;
                    p.passed = true;
                }
            });

            if(pipes.length > 0 && pipes[0].x < -30) pipes.shift();
        }

        function drawFlappy() {
            if(!fCtx) return;
            fCtx.fillStyle = '#70c5ce';
            fCtx.fillRect(0, 0, flappyCanvas.width, flappyCanvas.height);
            
            fCtx.fillStyle = '#ffeb3b';
            fCtx.beginPath();
            fCtx.arc(20, birdY, 8, 0, Math.PI * 2);
            fCtx.fill();
            
            fCtx.fillStyle = '#4caf50';
            pipes.forEach(p => {
                fCtx.fillRect(p.x, 0, 25, p.top);
                fCtx.fillRect(p.x, p.top + p.gap, 25, flappyCanvas.height - (p.top + p.gap));
            });
            
            fCtx.fillStyle = '#ffffff';
            fCtx.font = 'bold 14px sans-serif';
            fCtx.fillText(`Score: ${flappyScore}`, 10, 20);

            if(flappyGameOver) {
                fCtx.fillStyle = 'rgba(0,0,0,0.5)';
                fCtx.fillRect(0, 0, flappyCanvas.width, flappyCanvas.height);
                fCtx.fillStyle = '#fff';
                fCtx.font = '14px sans-serif';
                fCtx.fillText('Game Over!', 70, 150);
                fCtx.fillText('Click to Restart', 60, 175);
            }
        }

        function flappyLoop() {
            updateFlappy();
            drawFlappy();
            requestAnimationFrame(flappyLoop);
        }

        // GAME SOCKET EVENTS
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
        function buyShield() { socket.emit('buyShield'); }
        function stealSprite() { socket.emit('stealSprite'); }
        
        function sendTrade() {
            const targetUsername = document.getElementById('trade-target').value.trim();
            const offeredSprite = document.getElementById('trade-offer').value.trim();
            const requestedSprite = document.getElementById('trade-request').value.trim();
            
            if(!targetUsername || !offeredSprite || !requestedSprite) {
                alert("Fill out all trade fields!");
                return;
            }
            socket.emit('sendTradeRequest', { targetUsername, offeredSprite, requestedSprite });
        }

        socket.on('receiveTradeOffer', data => {
            const notif = document.getElementById('trade-notification');
            notif.innerHTML = `
                <p><b>${data.sender}</b> wants your <b>${data.requested}</b> for their <b>${data.offered}</b>!</p>
                <button onclick="respondTrade(true)" style="background:#4CAF50;">Accept</button>
                <button onclick="respondTrade(false)" style="background:#e53935;">Decline</button>
            `;
        });

        function respondTrade(accept) {
            socket.emit('respondTrade', { accept });
            document.getElementById('trade-notification').innerHTML = '';
        }

        function triggerBoost(multiplier, minutes) {
            socket.emit('adminServerBoost', { multiplier: multiplier, minutes: minutes });
        }

        function triggerGiveawayTime() {
            socket.emit('adminGiveawayTime');
        }

        function giveAllSprite() {
            const spriteKey = document.getElementById('admin-sprite-select').value;
            socket.emit('adminGiveAllSprite', { spriteKey: spriteKey });
        }

        function adminGiveCoinsAmount(amount) {
            socket.emit('adminGiveCoins', { target: '', amount: amount });
        }

        function adminGiveCoins() {
            const target = document.getElementById('admin-coin-target').value;
            const amount = parseInt(document.getElementById('admin-coin-amount').value);
            if(isNaN(amount) || amount <= 0) {
                alert("Please enter a valid coin amount!");
                return;
            }
            socket.emit('adminGiveCoins', { target: target, amount: amount });
        }

        function sendChatMessage() {
            const text = document.getElementById('chat-input').value;
            if(!text.trim()) return;
            socket.emit('sendChatMessage', text);
            document.getElementById('chat-input').value = '';
        }

        function checkChatEnter(e) {
            if(e.key === 'Enter') sendChatMessage();
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

        socket.on('receiveChatMessage', data => {
            const chatBox = document.getElementById('chat-box');
            chatBox.innerHTML += `<div class="chat-msg"><b>${data.username}</b>: ${data.message}</div>`;
            chatBox.scrollTop = chatBox.scrollHeight;
        });

        function formatSpritesWithCounts(spritesArray) {
            if (!spritesArray || spritesArray.length === 0) return 'None';
            let counts = {};
            spritesArray.forEach(s => {
                if (s) counts[s] = (counts[s] || 0) + 1;
            });
            return Object.entries(counts)
                .map(([name, count]) => {
                    let displayName = count > 1 ? `${name} (x${count})` : name;
                    if (name.startsWith('Shiny ')) return `<span style="color: #00acc1; font-weight: bold;">${displayName}</span>`;
                    if (name.startsWith('Golden ')) return `<span style="color: #d4af37; font-weight: bold;">${displayName}</span>`;
                    if (name.startsWith('Corrupted ')) return `<span style="color: #8e24aa; font-weight: bold;">${displayName}</span>`;
                    return displayName;
                })
                .join(', ');
        }

        socket.on('updatePlayers', players => {
            let sortedPlayers = Object.values(players).sort((a, b) => b.coins - a.coins);

            let lbHtml = '';
            let rawHtml = '';
            
            sortedPlayers.forEach((p, index) => {
                const adminText = p.is_admin ? '<span class="admin-tag">[ADMIN]</span> ' : '';
                const shieldText = p.is_shielded ? '<span class="shield-tag">[🛡️ SHIELDED]</span> ' : '';
                const rankClass = index === 0 ? 'top-1' : (index === 1 ? 'top-2' : (index === 2 ? 'top-3' : ''));
                
                lbHtml += `
                    <div class="leaderboard-row ${rankClass}">
                        <span>#${index + 1} ${adminText}${shieldText}<b>${p.name}</b></span>
                        <span>💰 ${p.coins}c | ⚡ ${p.multiplier}x</span>
                    </div>`;
                
                const formattedSprites = formatSpritesWithCounts(p.sprites);
                rawHtml += `<p>${adminText}${shieldText}<b>${p.name}</b> | Coins: ${p.coins} | Mult: ${p.multiplier}x | Sprites: ${formattedSprites}</p>`;
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

    c.execute("INSERT INTO users (username, password, coins, multiplier, sprites, shield_until) VALUES (?, ?, 0, 1, '', 0)", (username, password))
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
    if not session_info or key not in SPRITE_CATALOG or key == 'shield': return
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
        
        # Roll for variant
        variant_name, variant_mult = roll_sprite_variant()
        final_mult_boost = sprite['mult_boost'] * variant_mult
        multiplier += final_mult_boost
        
        item_full_name = f"{variant_name} {sprite['name']}" if variant_name != 'Normal' else sprite['name']
        
        current_sprites = sprites_str.split(',') if sprites_str else []
        current_sprites.append(item_full_name)
        new_sprites_str = ','.join(current_sprites)

        c.execute("UPDATE users SET coins = ?, multiplier = ?, sprites = ? WHERE username = ?", (coins, multiplier, new_sprites_str, uname))
        conn.commit()
        conn.close()

        emit('alertMessage', f"Bought {item_full_name}! Multiplier is now {multiplier}x!", room=request.sid)
        emit('updatePlayers', get_all_online_players(), broadcast=True)
    else:
        conn.close()
        emit('alertMessage', "Not enough coins!", room=request.sid)

@socketio.on('buyShield')
def handle_buy_shield():
    session_info = active_sessions.get(request.sid)
    if not session_info: return
    uname = session_info['username']

    shield_cost = 250
    shield_duration = 300  # 5 minutes

    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute("SELECT coins, shield_until FROM users WHERE username = ?", (uname,))
    row = c.fetchone()
    if not row:
        conn.close()
        return
    coins, shield_until = row

    if coins >= shield_cost:
        current_time = time.time()
        new_shield_time = max(current_time, shield_until or 0) + shield_duration
        coins -= shield_cost

        c.execute("UPDATE users SET coins = ?, shield_until = ? WHERE username = ?", (coins, new_shield_time, uname))
        conn.commit()
        conn.close()

        emit('alertMessage', "🛡️ Shield activated for 5 minutes! You are safe from heists.", room=request.sid)
        emit('updatePlayers', get_all_online_players(), broadcast=True)
    else:
        conn.close()
        emit('alertMessage', "Not enough coins for a Shield! (Cost: 250c)", room=request.sid)

@socketio.on('stealSprite')
def handle_steal_sprite():
    session_info = active_sessions.get(request.sid)
    if not session_info: return
    uname = session_info['username']

    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    c.execute("SELECT coins, multiplier, sprites FROM users WHERE username = ?", (uname,))
    row = c.fetchone()
    if not row or row[0] < 100:
        conn.close()
        emit('alertMessage', "Need 100 coins to attempt stealing a sprite!", room=request.sid)
        return

    c.execute("UPDATE users SET coins = coins - 100 WHERE username = ?", (uname,))
    my_coins, my_mult, my_sprites_str = row

    other_sids = [sid for sid, data in active_sessions.items() if sid != request.sid]
    if not other_sids:
        conn.commit()
        conn.close()
        emit('alertMessage', "No one else online to steal from!", room=request.sid)
        emit('updatePlayers', get_all_online_players(), broadcast=True)
        return

    target_sid = random.choice(other_sids)
    target_uname = active_sessions[target_sid]['username']

    c.execute("SELECT multiplier, sprites, shield_until FROM users WHERE username = ?", (target_uname,))
    target_row = c.fetchone()
    if not target_row:
        conn.commit()
        conn.close()
        return
    
    target_mult, target_sprites_str, shield_until = target_row
    
    if shield_until and time.time() < shield_until:
        conn.commit()
        conn.close()
        emit('alertMessage', f"{target_uname} is protected by a Shield! Heist failed.", room=request.sid)
        return

    target_sprites = [s for s in target_sprites_str.split(',') if s]

    if not target_sprites:
        conn.commit()
        conn.close()
        emit('alertMessage', f"{target_uname} has no sprites to steal!", room=request.sid)
        emit('updatePlayers', get_all_online_players(), broadcast=True)
        return

    stolen_sprite = random.choice(target_sprites)
    target_sprites.remove(stolen_sprite)
    new_target_sprites_str = ','.join(target_sprites)
    
    mult_value = get_sprite_multiplier_value(stolen_sprite)
    new_target_mult = max(1, target_mult - mult_value)
    new_my_mult = my_mult + mult_value

    c.execute("UPDATE users SET multiplier = ?, sprites = ? WHERE username = ?", (new_target_mult, new_target_sprites_str, target_uname))

    my_sprites = [s for s in my_sprites_str.split(',') if s]
    my_sprites.append(stolen_sprite)
    new_my_sprites_str = ','.join(my_sprites)
    c.execute("UPDATE users SET multiplier = ?, sprites = ? WHERE username = ?", (new_my_mult, new_my_sprites_str, uname))

    conn.commit()
    conn.close()

    emit('alertMessage', f"Successful heist! You stole {stolen_sprite} from {target_uname}!", room=request.sid)
    emit('alertMessage', f"Oh no! {uname} stole your {stolen_sprite}!", room=target_sid)
    emit('updatePlayers', get_all_online_players(), broadcast=True)

@socketio.on('sendTradeRequest')
def handle_trade_request(data):
    session_info = active_sessions.get(request.sid)
    if not session_info: return
    sender_uname = session_info['username']
    
    target_uname = data.get('targetUsername')
    offered_sprite = data.get('offeredSprite')
    requested_sprite = data.get('requestedSprite')

    target_sid = None
    for sid, sinfo in active_sessions.items():
        if sinfo['username'] == target_uname:
            target_sid = sid
            break

    if not target_sid:
        emit('alertMessage', "Target player is not online!", room=request.sid)
        return

    active_trades[target_sid] = {
        'sender_sid': request.sid,
        'sender_uname': sender_uname,
        'offered_sprite': offered_sprite,
        'requested_sprite': requested_sprite
    }

    emit('receiveTradeOffer', {
        'sender': sender_uname,
        'offered': offered_sprite,
        'requested': requested_sprite
    }, room=target_sid)
    emit('alertMessage', f"Trade offer sent to {target_uname}!", room=request.sid)

@socketio.on('respondTrade')
def handle_trade_response(data):
    accept = data.get('accept', False)
    target_sid = request.sid
    trade = active_trades.get(target_sid)

    if not trade:
        emit('alertMessage', "No active trade offer found.", room=request.sid)
        return

    if not accept:
        emit('alertMessage', "Trade declined.", room=trade['sender_sid'])
        del active_trades[target_sid]
        return

    sender_sid = trade['sender_sid']
    sender_uname = trade['sender_uname']
    receiver_uname = active_sessions[target_sid]['username']
    offered_sprite = trade['offered_sprite']
    requested_sprite = trade['requested_sprite']

    conn = sqlite3.connect('game.db')
    c = conn.cursor()

    c.execute("SELECT multiplier, sprites FROM users WHERE username = ?", (sender_uname,))
    s_row = c.fetchone()
    c.execute("SELECT multiplier, sprites FROM users WHERE username = ?", (receiver_uname,))
    r_row = c.fetchone()

    if not s_row or not r_row:
        conn.close()
        emit('alertMessage', "Trade failed: User data missing.", room=request.sid)
        return

    s_mult, s_sprites_str = s_row
    r_mult, r_sprites_str = r_row

    s_sprites = [s for s in s_sprites_str.split(',') if s]
    r_sprites = [s for s in r_sprites_str.split(',') if s]

    if offered_sprite not in s_sprites or requested_sprite not in r_sprites:
        conn.close()
        emit('alertMessage', "Trade failed: Missing required sprites in inventories.", room=request.sid)
        emit('alertMessage', "Trade failed: Items no longer available.", room=sender_sid)
        del active_trades[target_sid]
        return

    s_sprites.remove(offered_sprite)
    s_sprites.append(requested_sprite)
    r_sprites.remove(requested_sprite)
    r_sprites.append(offered_sprite)

    offered_val = get_sprite_multiplier_value(offered_sprite)
    requested_val = get_sprite_multiplier_value(requested_sprite)

    new_s_mult = s_mult - offered_val + requested_val
    new_r_mult = r_mult - requested_val + offered_val

    c.execute("UPDATE users SET multiplier = ?, sprites = ? WHERE username = ?", (new_s_mult, ','.join(s_sprites), sender_uname))
    c.execute("UPDATE users SET multiplier = ?, sprites = ? WHERE username = ?", (new_r_mult, ','.join(r_sprites), receiver_uname))
    conn.commit()
    conn.close()

    del active_trades[target_sid]
    emit('alertMessage', f"Successful trade with {receiver_uname}!", room=sender_sid)
    emit('alertMessage', f"Successful trade with {sender_uname}!", room=target_sid)
    emit('updatePlayers', get_all_online_players(), broadcast=True)

@socketio.on('sendChatMessage')
def handle_chat_message(message):
    session_info = active_sessions.get(request.sid)
    if not session_info: return
    uname = session_info['username']
    
    clean_msg = message.strip()[:200]
    if not clean_msg: return

    emit('receiveChatMessage', {'username': uname, 'message': clean_msg}, broadcast=True)

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
        c.execute("UPDATE users SET coins = coins + 99999, multiplier = multiplier + 100 WHERE username = ?", (uname,))
        conn.commit()
        active_sessions[request.sid]['is_admin'] = True
        conn.close()
        emit('alertMessage', "👑 ADMIN PRIVILEGES GRANTED (+100x Multiplier Bonus)!", room=request.sid)
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

@socketio.on('adminGiveawayTime')
def handle_admin_giveaway_time():
    global giveaway_task_active
    session_info = active_sessions.get(request.sid)
    if not session_info or not session_info.get('is_admin'): return

    def run_giveaway_cycle():
        global giveaway_task_active
        while giveaway_task_active:
            online_sids = list(active_sessions.keys())
            if online_sids:
                lucky_sid = random.choice(online_sids)
                lucky_uname = active_sessions[lucky_sid]['username']
                
                conn = sqlite3.connect('game.db')
                c = conn.cursor()
                c.execute("UPDATE users SET coins = coins + 10000000000 WHERE username = ?", (lucky_uname,))
                conn.commit()
                conn.close()

                emit('alertMessage', f"🎉 LUCKY GIVEAWAY! {lucky_uname} just won 10,000,000,000 coins!", broadcast=True)
                emit('updatePlayers', get_all_online_players(), broadcast=True)
            
            for _ in range(600):
                if not giveaway_task_active:
                    break
                socketio.sleep(1)

    if not giveaway_task_active:
        giveaway_task_active = True
        socketio.start_background_task(run_giveaway_cycle)
        emit('alertMessage', "🎉 Lucky Giveaway Time started! Every 10 minutes, a random player will win 10,000,000,000 coins.", broadcast=True)
    else:
        giveaway_task_active = False
        emit('alertMessage', "🛑 Lucky Giveaway Time stopped.", broadcast=True)

@socketio.on('adminGiveAllSprite')
def handle_admin_give_all(data):
    session_info = active_sessions.get(request.sid)
    if not session_info or not session_info.get('is_admin'): return

    sprite_key = data.get('spriteKey')
    if sprite_key not in SPRITE_CATALOG or sprite_key == 'shield': return

    sprite = SPRITE_CATALOG[sprite_key]
    
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
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

@socketio.on('adminGiveCoins')
def handle_admin_give_coins(data):
    session_info = active_sessions.get(request.sid)
    if not session_info or not session_info.get('is_admin'): return

    target = data.get('target', '').strip()
    amount = int(data.get('amount', 0))
    if amount <= 0: return

    conn = sqlite3.connect('game.db')
    c = conn.cursor()

    if not target or target.upper() == "ALL":
        c.execute("UPDATE users SET coins = coins + ?", (amount,))
        conn.commit()
        conn.close()
        emit('alertMessage', f"🎁 ADMIN COMMAND: Gave {amount} coins to all players!", broadcast=True)
    else:
        c.execute("SELECT username FROM users WHERE username = ?", (target,))
        if c.fetchone():
            c.execute("UPDATE users SET coins = coins + ? WHERE username = ?", (amount, target))
            conn.commit()
            conn.close()
            emit('alertMessage', f"🎁 ADMIN COMMAND: Gave {amount} coins to {target}!", broadcast=True)
        else:
            conn.close()
            emit('alertMessage', f"User '{target}' not found!", room=request.sid)
            return

    emit('updatePlayers', get_all_online_players(), broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in active_sessions:
        del active_sessions[request.sid]
        emit('updatePlayers', get_all_online_players(), broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.fget('PORT', 5000) if hasattr(os.environ, 'fget') else os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
