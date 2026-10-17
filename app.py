from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime
import hashlib
import os
import requests

app = Flask(__name__)
app.secret_key = 'super_secret_admin_key_multi_user_123'

DB_PATH = 'data_store.db'
DB_DOWNLOAD_URL = 'https://drive.google.com/uc?export=download&id=1YrBMVpTyXpuC1FQumhY5Mz4EjwE_TFgx'

# تحميل قاعدة البيانات تلقائياً من جوجل درايف عند الإقلاع لأول مرة إذا لم تكن موجودة
if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1024:
    print("جاري تحميل قاعدة البيانات من جوجل درايف (قد يستغرق بضع دقائق)...")
    try:
        response = requests.get(DB_DOWNLOAD_URL, stream=True)
        with open(DB_PATH, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print("تم تحميل قاعدة البيانات بنجاح!")
    except Exception as e:
        print(f"حدث خطأ أثناء تحميل قاعدة البيانات: {e}")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# إنشاء جداول المستخدمين وسجل الأنشطة إذا لم تكن موجودة وتوليد حساب المدير الافتراضي
def init_db_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # جدول المستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user'
        )
    ''')
    
    # جدول السجلات ليرتبط باسم المستخدم
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS search_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            user_ip TEXT,
            search_query TEXT,
            results_count INTEGER,
            timestamp TEXT
        )
    ''')
    
    # إنشاء حساب مدير افتراضي (Admin) إذا لم يكن موجوداً (Username: admin, Password: 123)
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        hashed_pw = hashlib.sha256('123'.encode()).hexdigest()
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ('admin', hashed_pw, 'admin'))
        
    conn.commit()
    conn.close()

init_db_tables()

# صفحة تسجيل الدخول
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        hashed_pw = hashlib.sha256(password.encode()).hexdigest()
        
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hashed_pw)).fetchone()
        conn.close()
        
        if user:
            session['logged_in'] = True
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('index'))
        else:
            error = 'اسم المستخدم أو كلمة السر غير صحيحة.'
            
    return render_template('login.html', error=error)

# تسجيل الخروج
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# صفحة إدارة المستخدمين (للمدير فقط)
@app.route('/users', methods=['GET', 'POST'])
def manage_users():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('index'))
        
    message = None
    error = None
    
    if request.method == 'POST':
        new_username = request.form.get('username', '').strip()
        new_password = request.form.get('password', '').strip()
        role = request.form.get('role', 'user')
        
        if new_username and new_password:
            try:
                conn = get_db_connection()
                hashed_pw = hashlib.sha256(new_password.encode()).hexdigest()
                conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (new_username, hashed_pw, role))
                conn.commit()
                conn.close()
                message = f"تم إضافة المستخدم {new_username} بنجاح!"
            except Exception as e:
                error = "اسم المستخدم موجود مسبقاً أو حدث خطأ."
        else:
            error = "يرجى ملء جميع الحقول."
            
    conn = get_db_connection()
    users_list = conn.execute("SELECT id, username, role FROM users").fetchall()
    conn.close()
    
    return render_template('users.html', users=users_list, message=message, error=error)

# حذف مستخدم
@app.route('/delete_user/<int:user_id>')
def delete_user(user_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('index'))
        
    conn = get_db_connection()
    # منع حذف المدير الرئيسي admin
    user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    if user and user['username'] != 'admin':
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    conn.close()
    return redirect(url_for('manage_users'))

# الصفحة الرئيسية للبحث
@app.route('/', methods=['GET', 'POST'])
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    query = ""
    results = []
    
    if request.method == 'POST':
        query = request.form.get('query', '').strip()
        if query:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # جلب أسماء الأعمدة الديناميكية
            cursor.execute("PRAGMA table_info(search_data)")
            columns = [row['name'] for row in cursor.fetchall() if row['name'] != 'source_file']
            
            if columns:
                where_clauses = [f'"{col}" LIKE ?' for col in columns]
                sql = f"SELECT * FROM search_data WHERE {' OR '.join(where_clauses)} LIMIT 100"
                params = [f"%{query}%"] * len(columns)
                
                rows = cursor.execute(sql, params).fetchall()
                
                for row in rows:
                    item = {
                        'source_file': row['source_file'],
                        'fields': []
                    }
                    for col in columns:
                        val = str(row[col]).strip() if row[col] is not None else ''
                        if val and val.lower() not in ['none', 'nan', '']:
                            item['fields'].append(val)
                    results.append(item)
                    
            # تسجيل البحث في السجل مع اسم المستخدم الحالي
            current_user = session.get('username', 'Unknown')
            user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            cursor.execute(
                "INSERT INTO search_logs (username, user_ip, search_query, results_count, timestamp) VALUES (?, ?, ?, ?, ?)",
                (current_user, user_ip, query, len(results), current_time)
            )
            conn.commit()
            conn.close()

    return render_template('index.html', query=query, results=results, username=session.get('username'), role=session.get('role'))

# صفحة السجلات المحدثة لتظهر اسم المستخدم
@app.route('/logs')
def view_logs():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    logs = conn.execute("SELECT * FROM search_logs ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()
    
    return render_template('logs.html', logs=logs, role=session.get('role'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)