from flask import Flask, render_template, request, redirect, session, send_file
from flask_mysqldb import MySQL
import bcrypt
import matplotlib.pyplot as plt
import os
import statistics
import numpy as np
import io
from sklearn.linear_model import LinearRegression
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import requests

app = Flask(__name__)
app.secret_key = "supersecretkey"

# MySQL Configuration
app.config['MYSQL_HOST'] = '127.0.0.1'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'your_password' 
app.config['MYSQL_DB'] = 'pfm'

mysql = MySQL(app)

# --- Helper Functions ---
def fetch_fund_name_from_amfi(mf_code):
    """Fetches the official fund name from AMFI using the scheme code."""
    url = "https://www.amfiindia.com/spages/NAVAll.txt"
    try:
        # We use a timeout to ensure the app doesn't hang if the site is slow
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            lines = response.text.split("\n")
            for line in lines:
                parts = line.split(";")
                # The format is typically: SchemeCode;ISIN;ISIN2;SchemeName;NAV;Date
                if len(parts) > 3 and parts[0].strip() == str(mf_code):
                    return parts[3].strip() 
        return "Fund " + str(mf_code)
    except:
        return "Fund " + str(mf_code)
def fetch_fund_name_from_amfi(mf_code):
    """Fetches the official fund name from AMFI using the scheme code."""
    url = "https://www.amfiindia.com/spages/NAVAll.txt"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            lines = response.text.split("\n")
            for line in lines:
                # AMFI text format: SchemeCode;ISIN;ISIN2;SchemeName;NAV;Date
                parts = line.split(";")
                if len(parts) > 3 and parts[0].strip() == str(mf_code):
                    return parts[3].strip() # The 4th element is the Scheme Name
        return "Unknown Fund"
    except Exception as e:
        print(f"Scraping Error: {e}")
        return "Fund " + str(mf_code)

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
    if not data: return [], []
    labels = [f"{row[0]}-{row[1]}" for row in data]
    values = [float(row[2]) for row in data]
    return labels, values

def calculate_cagr(mf_code, years):
    cur = mysql.connection.cursor()
    cur.execute("SELECT mf_nav_year, mf_nav_month, mf_max_Net_Asset_Value FROM mf_monthly_nav WHERE mf_Code = %s ORDER BY mf_nav_year DESC, mf_nav_month DESC LIMIT 1", [mf_code])
    latest = cur.fetchone()
    if not latest: return None
    ly, lm, lv = int(latest[0]), int(latest[1]), float(latest[2])
    cur.execute("SELECT mf_max_Net_Asset_Value FROM mf_monthly_nav WHERE mf_Code = %s AND mf_nav_year = %s AND mf_nav_month = %s", [mf_code, ly - years, lm])
    old = cur.fetchone()
    cur.close()
    if not old or float(old[0]) == 0: return None
    return round(((lv / float(old[0])) ** (1/years) - 1) * 100, 2)

def calculate_volatility(mf_code):
    _, values = get_nav_history(mf_code)
    if len(values) < 2: return 0, "N/A"
    returns = [(values[i] - values[i-1])/values[i-1] for i in range(1, len(values))]
    vol = statistics.stdev(returns) * 100
    risk = "Low" if vol < 2 else "Moderate" if vol < 5 else "High"
    return round(vol, 2), risk

def predict_future_nav(mf_code):
    _, values = get_nav_history(mf_code)
    if len(values) < 5: return 0
    X = np.array(range(len(values))).reshape(-1, 1)
    model = LinearRegression().fit(X, np.array(values))
    return round(float(model.predict([[len(values)]])[0]), 2)

# --- Routes ---

@app.route('/')
def home(): return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email, pw = request.form['email'], request.form['password'].encode('utf-8')
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", [email])
        user = cur.fetchone()
        cur.close()
        if user and bcrypt.checkpw(pw, user[3].encode('utf-8')):
            session['user'] = user[1]
            return redirect('/dashboard')
        return "Invalid Credentials"
    return render_template('login.html')
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user' not in session: return redirect('/login')
    cur = mysql.connection.cursor()
    cur.execute("SELECT DISTINCT mf_Code FROM mf_monthly_nav")
    funds = cur.fetchall()
    cur.close()
    
    # Initialize dictionary with default values
    d = {'user': session['user'], 'funds': funds, 'code': None, 'history': [[], []], 'fund_name': ""}

    if request.method == 'POST':
        c = request.form['fund_code']
        
        # New: Fetch the name from the web
        name = fetch_fund_name_from_amfi(c)
        
        v, r = calculate_volatility(c)
        c3 = calculate_cagr(c, 3)
        rec = "Strong Buy" if c3 and c3 > 12 and v < 5 else "Buy" if c3 and c3 > 8 else "Hold"
        
        d.update({
            'code': c, 
            'fund_name': name,  # Passing the name to HTML
            'cagr_3': c3, 
            'volatility': (v, r), 
            'prediction': predict_future_nav(c), 
            'history': get_nav_history(c), 
            'rec': rec
        })
    return render_template('dashboard.html', **d)
def generate_pdf_chart(mf_code):
    """Generates a specialized chart for the PDF report."""
    labels, values = get_nav_history(mf_code)
    if not values:
        return None

    plt.figure(figsize=(6, 3))
    plt.plot(values, color='#16a34a', linewidth=2) # Matching the Green theme
    plt.fill_between(range(len(values)), values, color='#16a34a', alpha=0.1)
    plt.title(f"NAV Growth Trend: {mf_code}", fontsize=12, pad=10)
    plt.ylabel("NAV Value")
    plt.xticks([]) # Hide x-axis labels to keep the PDF clean
    plt.grid(True, linestyle='--', alpha=0.3)
    plt.tight_layout()

    # Save to a bytes buffer
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', dpi=150)
    plt.close()
    img_buffer.seek(0)
    return img_buffer

@app.route('/export_pdf/<mf_code>')
def export_pdf(mf_code):
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT mf_Scheme_Name FROM mf_mst_scheme WHERE mf_Code = %s", [mf_code])
        res = cur.fetchone()
        cur.close()
        name = res[0] if res else "Fund " + mf_code
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=(612, 792))
        styles = getSampleStyleSheet()
        elements = []

        # 1. Header
        elements.append(Paragraph(f"AI Portfolio Analysis: {name}", styles['Heading1']))
        elements.append(Spacer(1, 0.1 * inch))
        elements.append(Paragraph(f"Generated for Mutual Fund Code: {mf_code}", styles['Normal']))
        elements.append(Spacer(1, 0.3 * inch))

        # 2. THE GRAPH (The Missing Part)
        chart_io = generate_pdf_chart(mf_code)
        if chart_io:
            img = RLImage(chart_io, width=5.5 * inch, height=2.5 * inch)
            elements.append(img)
            elements.append(Spacer(1, 0.3 * inch))

        # 3. Stats Table
        v, r = calculate_volatility(mf_code)
        c3 = calculate_cagr(mf_code, 3)
        pred = predict_future_nav(mf_code)
        
        data = [
            ["Metric", "Value Analysis"],
            ["Current Risk Level", r],
            ["3-Year CAGR (%)", f"{c3}%" if c3 else "Data N/A"],
            ["Volatility Score", f"{v}%"],
            ["AI Predicted NAV", f"Rs. {pred}"]
        ]
        
        t = Table(data, colWidths=[2.5 * inch, 3 * inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.green),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(t)

        # 4. Final Build
        doc.build(elements)
        buffer.seek(0)
        return send_file(
            buffer, 
            as_attachment=True, 
            download_name=f"Report_{mf_code}.pdf", 
            mimetype='application/pdf'
        )
    except Exception as e:
        return f"PDF Error: {str(e)}"
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')

if __name__ == '__main__':
    app.run(debug=True)