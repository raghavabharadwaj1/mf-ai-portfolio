from flask import Flask, render_template, request, redirect, session
from flask_mysqldb import MySQL
import bcrypt
import matplotlib.pyplot as plt
import os

app = Flask(__name__)
app.secret_key = "supersecretkey"

# MySQL Configuration
app.config['MYSQL_HOST'] = '127.0.0.1'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'your_password'  # Put your MySQL password
app.config['MYSQL_DB'] = 'pfm'

mysql = MySQL(app)


# -----------------------------
# CAGR FUNCTION
# -----------------------------
def calculate_cagr(mf_code, years):
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT mf_nav_year, mf_nav_month, mf_max_Net_Asset_Value
        FROM mf_monthly_nav
        WHERE mf_Code = %s
        ORDER BY mf_nav_year DESC, mf_nav_month DESC
        LIMIT 1
    """, [mf_code])

    latest = cur.fetchone()

    if not latest:
        cur.close()
        return None

    latest_year = int(latest[0])
    latest_month = int(latest[1])
    latest_nav = float(latest[2])

    target_year = latest_year - years

    cur.execute("""
        SELECT mf_max_Net_Asset_Value
        FROM mf_monthly_nav
        WHERE mf_Code = %s
        AND mf_nav_year = %s
        AND mf_nav_month = %s
    """, [mf_code, target_year, latest_month])

    old = cur.fetchone()
    cur.close()

    if not old:
        return None

    old_nav = float(old[0])

    if old_nav == 0:
        return None

    cagr = ((latest_nav / old_nav) ** (1/years) - 1) * 100
    return round(cagr, 2)
# -----------------------------
# CALCULATION FUNCTIONS
# -----------------------------
def generate_nav_chart(mf_code):
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT mf_nav_year, mf_nav_month, mf_max_Net_Asset_Value
        FROM mf_monthly_nav
        WHERE mf_Code = %s
        ORDER BY mf_nav_year, mf_nav_month
    """, [mf_code])

    data = cur.fetchall()
    cur.close()

    labels = []
    nav_values = []

    for row in data:
        year = row[0]
        month = row[1]
        nav = float(row[2])

        labels.append(f"{year}-{month}")
        nav_values.append(nav)

    plt.figure(figsize=(10, 4))
    plt.plot(nav_values)
    plt.title("NAV Growth Trend")
    plt.xlabel("Time")
    plt.ylabel("NAV")
    plt.tight_layout()

    chart_path = "nav_chart.png"
    plt.savefig(chart_path)
    plt.close()

    return chart_path
import statistics

def calculate_volatility(mf_code):
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT mf_nav_year, mf_nav_month, mf_max_Net_Asset_Value
        FROM mf_monthly_nav
        WHERE mf_Code = %s
        ORDER BY mf_nav_year ASC, mf_nav_month ASC
    """, [mf_code])

    data = cur.fetchall()
    cur.close()

    if len(data) < 2:
        return None, None

    nav_values = [float(row[2]) for row in data]

    returns = []

    for i in range(1, len(nav_values)):
        if nav_values[i-1] != 0:
            monthly_return = (nav_values[i] - nav_values[i-1]) / nav_values[i-1]
            returns.append(monthly_return)

    if len(returns) < 2:
        return None, None

    volatility = statistics.stdev(returns) * 100

    # Risk Classification
    if volatility < 2:
        risk_level = "Low"
    elif volatility < 5:
        risk_level = "Moderate"
    else:
        risk_level = "High"

    return round(volatility, 2), risk_level
def calculate_max_drawdown(mf_code):
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT mf_max_Net_Asset_Value
        FROM mf_monthly_nav
        WHERE mf_Code = %s
        ORDER BY mf_nav_year ASC, mf_nav_month ASC
    """, [mf_code])

    data = cur.fetchall()
    cur.close()

    if not data:
        return None

    nav_values = [float(row[0]) for row in data]

    peak = nav_values[0]
    max_drawdown = 0

    for nav in nav_values:
        if nav > peak:
            peak = nav

        drawdown = (nav - peak) / peak

        if drawdown < max_drawdown:
            max_drawdown = drawdown

    return round(max_drawdown * 100, 2)
def get_nav_history(mf_code):
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT mf_nav_year, mf_nav_month, mf_max_Net_Asset_Value
        FROM mf_monthly_nav
        WHERE mf_Code = %s
        ORDER BY mf_nav_year ASC, mf_nav_month ASC
    """, [mf_code])

    data = cur.fetchall()
    cur.close()

    if not data:
        return [], []

    labels = []
    values = []

    for row in data:
        year = row[0]
        month = row[1]
        nav = float(row[2])

        labels.append(f"{year}-{month}")
        values.append(nav)

    return labels, values
# -----------------------------
# ROUTES
# -----------------------------
@app.route('/')
def home():
    return redirect('/login')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password'].encode('utf-8')

        hashed = bcrypt.hashpw(password, bcrypt.gensalt())

        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO users (name, email, password) VALUES (%s, %s, %s)",
            (name, email, hashed)
        )
        mysql.connection.commit()
        cur.close()

        return redirect('/login')

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password'].encode('utf-8')

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", [email])
        user = cur.fetchone()
        cur.close()

        if user:
            stored_password = user[3]
            if bcrypt.checkpw(password, stored_password.encode('utf-8')):
                session['user'] = user[1]
                return redirect('/dashboard')

        return "Invalid Credentials"

    return render_template('login.html')


@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()
    cur.execute("SELECT DISTINCT mf_Code FROM mf_monthly_nav LIMIT 200")
    funds = cur.fetchall()

    selected_code = None
    cagr_1 = None
    cagr_3 = None
    cagr_5 = None
    recommendation = None
    volatility = None
    risk_level = None
    drawdown = None
    labels = None
    nav_values = None

    if request.method == 'POST':
        selected_code = request.form['fund_code']
        cagr_1 = calculate_cagr(selected_code, 1)
        cagr_3 = calculate_cagr(selected_code, 3)
        cagr_5 = calculate_cagr(selected_code, 5)
        volatility, risk_level = calculate_volatility(selected_code)
        drawdown = calculate_max_drawdown(selected_code)
        labels, nav_values = get_nav_history(selected_code)
       # AI Recommendation Logic
        if cagr_3 and volatility and drawdown:
             if cagr_3 > 12 and volatility < 5 and drawdown > -20:
                  recommendation = "Strong Buy"
             elif cagr_3 > 8:
                  recommendation = "Buy"
             elif cagr_3 > 4:
                  recommendation = "Hold"
             else:
                  recommendation = "Avoid"
    cur.close()

    return render_template(
       'dashboard.html',
        user=session['user'],
        funds=funds,
        code=selected_code,
        cagr_1=cagr_1,
        cagr_3=cagr_3,
        cagr_5=cagr_5,
        volatility=volatility,
        risk_level=risk_level,
        drawdown=drawdown,
        labels=labels,
        nav_values=nav_values,
        recommendation=recommendation,
        
    )
from flask import send_file
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

@app.route('/export_pdf/<mf_code>')
def export_pdf(mf_code):

    cagr = calculate_cagr(mf_code,1)

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT mf_Scheme_Name
        FROM mf_mst_scheme
        WHERE mf_Code = %s
    """, [mf_code])

    result = cur.fetchone()
    cur.close()

    fund_name = result[0] if result else "Unknown Fund"

    file_path = "MF_Report.pdf"
    doc = SimpleDocTemplate(file_path)
    elements = []

    styles = getSampleStyleSheet()

    elements.append(Paragraph("MF AI Portfolio Report", styles["Heading1"]))
    elements.append(Spacer(1, 0.3 * inch))
    chart_path = generate_nav_chart(mf_code)
    data = [
        ["Fund Name", fund_name],
        ["Fund Code", mf_code],
        ["1-Year CAGR", f"{cagr} %"]
    ]

    table = Table(data, colWidths=[2.5 * inch, 3 * inch])
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
    ]))

    elements.append(table)
    doc.build(elements)

    return send_file(file_path, as_attachment=True)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')


if __name__ == '__main__':
    app.run(debug=True)