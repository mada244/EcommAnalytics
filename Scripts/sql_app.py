import streamlit as st
import pymssql
import time
import pandas as pd
import re
import os
import csv
from datetime import datetime
from openai import OpenAI
import google.generativeai as genai

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG — store keys in .streamlit/secrets.toml
# ══════════════════════════════════════════════════════════════════════════════
def get_secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, "")

GPT_API_KEY    = get_secret("GPT_API_KEY")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
LLAMA_API_KEY  = get_secret("LLAMA_API_KEY")
LLAMA_BASE_URL = "https://api.groq.com/openai/v1"

RESULTS_FILE = "benchmark_results.csv"

# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA CONTEXT
# ══════════════════════════════════════════════════════════════════════════════
SCHEMA_CONTEXT = """
-- Database: EcommAnalytics (MS SQL Server)
-- Use ONLY the tables and columns defined below. Do NOT invent columns.
-- Do NOT use GO in your output.

CREATE TABLE Categories (
    CategoryID   INT IDENTITY(1,1) PRIMARY KEY,
    CategoryName NVARCHAR(100) NOT NULL,
    Description  NVARCHAR(500)
);

CREATE TABLE Products (
    ProductID     INT IDENTITY(1,1) PRIMARY KEY,
    CategoryID    INT NOT NULL,           -- FK → Categories.CategoryID
    ProductName   NVARCHAR(200) NOT NULL,
    UnitPrice     DECIMAL(10,2) NOT NULL,
    StockQuantity INT NOT NULL DEFAULT 0,
    IsActive      BIT DEFAULT 1,
    CreatedAt     DATETIME DEFAULT GETDATE()
);

CREATE TABLE Customers (
    CustomerID       INT IDENTITY(1,1) PRIMARY KEY,
    FirstName        NVARCHAR(100) NOT NULL,
    LastName         NVARCHAR(100) NOT NULL,
    Email            NVARCHAR(255) UNIQUE NOT NULL,
    Country          NVARCHAR(50)  NOT NULL,
    RegistrationDate DATETIME DEFAULT GETDATE(),
    LoyaltyScore     INT DEFAULT 0
);

CREATE TABLE Orders (
    OrderID      BIGINT IDENTITY(1,1) PRIMARY KEY,
    CustomerID   INT NOT NULL,            -- FK → Customers.CustomerID
    OrderDate    DATETIME NOT NULL,
    TotalAmount  DECIMAL(12,2) NOT NULL,
    Status       NVARCHAR(50) NOT NULL,
    ShippingCity NVARCHAR(100)
);

CREATE TABLE OrderDetails (
    OrderDetailID BIGINT IDENTITY(1,1) PRIMARY KEY,
    OrderID       BIGINT NOT NULL,        -- FK → Orders.OrderID
    ProductID     INT NOT NULL,           -- FK → Products.ProductID
    Quantity      INT NOT NULL,
    UnitPrice     DECIMAL(10,2) NOT NULL,
    Discount      DECIMAL(5,2) DEFAULT 0.00
);
"""

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG & CSS
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="SQL LLM Benchmark", page_icon="⚡", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=DM+Sans:wght@400;500;600&display=swap');

html, body, [class*="css"]   { font-family: 'DM Sans', sans-serif; }
code, .stTextArea textarea   { font-family: 'JetBrains Mono', monospace !important; font-size: 12px !important; }

.llm-header { font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 700;
  padding: 5px 12px; border-radius: 6px; display: inline-block; margin-bottom: 8px; }
.llm-gpt    { background:#10a37f22; color:#10a37f; border:1px solid #10a37f55; }
.llm-gemini { background:#4285f422; color:#4285f4; border:1px solid #4285f455; }
.llm-llama  { background:#7c3aed22; color:#a78bfa; border:1px solid #7c3aed55; }

.prompt-badge { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:1px;
  padding:3px 9px; border-radius:4px; display:inline-block; margin-bottom:6px; }
.zs  { background:#f59e0b22; color:#f59e0b; border:1px solid #f59e0b55; }
.fs  { background:#06b6d422; color:#06b6d4; border:1px solid #06b6d455; }
.cot { background:#ec489922; color:#ec4899; border:1px solid #ec489955; }

.winner-box { background:linear-gradient(135deg,#22c55e18,#16a34a18);
  border:1px solid #22c55e55; border-radius:10px; padding:12px 20px;
  color:#22c55e; font-weight:700; font-size:15px; text-align:center; margin-top:12px; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# PROMPT
# ══════════════════════════════════════════════════════════════════════════════
def prompt_zero_shot(sql):
    return f"""You are an expert MS SQL Server DBA.
Use ONLY the schema below — do not invent tables or columns. Do NOT use GO.

{SCHEMA_CONTEXT}

Rewrite the query below to be highly optimized — minimize logical reads and CPU time.
Output ONLY the final T-SQL. No explanation.

{sql}"""

def prompt_few_shot(sql):
    return f"""You are an expert MS SQL Server DBA.
Use ONLY the schema below — do not invent tables or columns. Do NOT use GO.

{SCHEMA_CONTEXT}

Here are two optimization examples:

EXAMPLE 1 — Non-SARGable → SARGable:
  Bad:  WHERE YEAR(OrderDate) = 2023
  Good: WHERE OrderDate >= '2023-01-01' AND OrderDate < '2024-01-01'

EXAMPLE 2 — Correlated subquery → JOIN:
  Bad:  SELECT (SELECT COUNT(*) FROM Orders WHERE CustomerID = c.CustomerID) FROM Customers c
  Good: SELECT COUNT(o.OrderID) FROM Customers c
        LEFT JOIN Orders o ON c.CustomerID = o.CustomerID
        GROUP BY c.CustomerID

Now apply the same principles to optimize this query.
Output ONLY the final T-SQL. No explanation.

{sql}"""

def prompt_cot(sql):
    return f"""You are an expert MS SQL Server DBA.
Use ONLY the schema below — do not invent tables or columns. Do NOT use GO.

{SCHEMA_CONTEXT}

Think step by step:
1. Identify every performance anti-pattern (non-SARGable predicates, correlated subqueries,
   SELECT *, inefficient JOINs, bad aggregations, nested CTEs).
2. For each anti-pattern found, describe the fix.
3. Write the fully optimized T-SQL using only real columns from the schema above.

Wrap the final SQL in a ```sql block.

Query to optimize:
{sql}"""

PROMPT_STRATEGIES = {
    "Zero-Shot":        (prompt_zero_shot,  "zs",  "ZS"),
    "Few-Shot":         (prompt_few_shot,   "fs",  "FS"),
    "Chain-of-Thought": (prompt_cot,        "cot", "CoT"),
}

# ══════════════════════════════════════════════════════════════════════════════
#  22 SCENARIOS
# ══════════════════════════════════════════════════════════════════════════════
SCENARIOS = {
    "✏️  Free mode (paste your own query)": "",

    # 1 · SELECT *
    "Q1-A · SELECT * — full Customers scan":
        "SELECT *\nFROM Customers;",

    "Q1-B · SELECT * — Orders x OrderDetails":
        "SELECT *\nFROM Orders o, OrderDetails od\nWHERE o.OrderID = od.OrderID;",

    "Q1-C · SELECT * — subquery wrapper on Products":
        "SELECT *\nFROM (SELECT * FROM Products) AS AllProducts\nWHERE CategoryID = 1;",

    # 2 · Inefficient JOINs
    "Q2-A · Implicit CROSS JOIN (comma syntax)":
        "SELECT o.OrderID, c.FirstName, c.LastName\nFROM Orders o, Customers c\nWHERE o.CustomerID = c.CustomerID\n  AND o.Status = \'Completed\';",

    "Q2-B · Function on JOIN key (YEAR/MONTH)":
        "SELECT o.OrderID, o.TotalAmount, c.Email\nFROM Orders o\nINNER JOIN Customers c ON o.CustomerID = c.CustomerID\nWHERE YEAR(o.OrderDate) = 2023\n  AND MONTH(o.OrderDate) = 6;",

    "Q2-C · Unnecessary LEFT JOIN chain":
        "SELECT p.ProductName, od.Quantity, o.TotalAmount\nFROM Products p\nLEFT JOIN OrderDetails od ON p.ProductID = od.ProductID\nLEFT JOIN Orders o ON od.OrderID = o.OrderID\nWHERE p.IsActive = 1;",

    "Q2-D · OUTER JOIN where INNER is correct":
        "SELECT o.OrderID, c.FirstName, c.Country\nFROM Orders o\nLEFT JOIN Customers c ON o.CustomerID = c.CustomerID\nWHERE c.Country = \'Romania\';",

    # 3 · Correlated subqueries
    "Q3-A · Correlated subquery in SELECT (order count)":
        "SELECT\n    c.CustomerID, c.FirstName, c.LastName,\n    (SELECT COUNT(*) FROM Orders o WHERE o.CustomerID = c.CustomerID) AS TotalOrders\nFROM Customers c;",

    "Q3-B · Triple-nested EXISTS":
        "SELECT c.CustomerID, c.Email\nFROM Customers c\nWHERE EXISTS (\n    SELECT 1 FROM Orders o WHERE o.CustomerID = c.CustomerID AND EXISTS (\n        SELECT 1 FROM OrderDetails od WHERE od.OrderID = o.OrderID AND EXISTS (\n            SELECT 1 FROM Products p\n            WHERE p.ProductID = od.ProductID AND p.IsActive = 1\n        )\n    )\n);",

    "Q3-C · Two correlated subqueries per row (MAX + SUM)":
        "SELECT\n    c.CustomerID, c.FirstName,\n    (SELECT MAX(o.OrderDate) FROM Orders o WHERE o.CustomerID = c.CustomerID) AS LastOrderDate,\n    (SELECT SUM(o.TotalAmount) FROM Orders o WHERE o.CustomerID = c.CustomerID) AS LifetimeValue\nFROM Customers c;",

    "Q3-D · Correlated subquery vs per-customer average":
        "SELECT OrderID, CustomerID, TotalAmount\nFROM Orders o\nWHERE TotalAmount > (\n    SELECT AVG(TotalAmount) FROM Orders WHERE CustomerID = o.CustomerID\n);",

    # 4 · Non-SARGable WHERE
    "Q4-A · CONVERT on OrderDate column":
        "SELECT OrderID, CustomerID, TotalAmount\nFROM Orders\nWHERE CONVERT(VARCHAR(10), OrderDate, 120) = \'2023-11-24\';",

    "Q4-B · SUBSTRING on primary key":
        "SELECT CustomerID, FirstName, LastName, Email\nFROM Customers\nWHERE SUBSTRING(CAST(CustomerID AS VARCHAR), 1, 1) = \'1\';",

    "Q4-C · Arithmetic on UnitPrice column":
        "SELECT ProductID, ProductName, UnitPrice\nFROM Products\nWHERE UnitPrice * 1.2 > 100;",

    "Q4-D · UPPER() on Email column":
        "SELECT CustomerID, FirstName, Email\nFROM Customers\nWHERE UPPER(Email) LIKE \'TEST%\';",

    "Q4-E · ISNULL on foreign key":
        "SELECT od.OrderDetailID, od.Quantity, od.UnitPrice\nFROM OrderDetails od\nWHERE ISNULL(od.ProductID, 0) = 42;",

    # 5 · Inefficient GROUP BY
    "Q5-A · HAVING instead of WHERE":
        "SELECT CustomerID, COUNT(*) AS OrderCount, SUM(TotalAmount) AS Revenue\nFROM Orders\nGROUP BY CustomerID\nHAVING SUM(TotalAmount) > 500\n   AND COUNT(*) > 2\n   AND MAX(Status) = \'Completed\';",

    "Q5-B · GROUP BY on computed expression":
        "SELECT DATENAME(MONTH, OrderDate) AS MonthName, YEAR(OrderDate) AS OrderYear,\n       COUNT(*) AS Orders, SUM(TotalAmount) AS Revenue\nFROM Orders\nGROUP BY DATENAME(MONTH, OrderDate), YEAR(OrderDate)\nORDER BY YEAR(OrderDate), DATENAME(MONTH, OrderDate);",

    "Q5-C · COUNT(DISTINCT) double dedup":
        "SELECT cat.CategoryName,\n       COUNT(DISTINCT od.OrderID) AS UniqueOrders,\n       COUNT(DISTINCT od.ProductID) AS UniqueProducts,\n       SUM(od.Quantity * od.UnitPrice) AS GrossRevenue\nFROM OrderDetails od\nINNER JOIN Products p ON od.ProductID = p.ProductID\nINNER JOIN Categories cat ON p.CategoryID = cat.CategoryID\nGROUP BY cat.CategoryName;",

    "Q5-D · Double aggregation (derived + outer)":
        "SELECT outer_q.Country,\n       SUM(outer_q.CustomerRevenue) AS TotalCountryRevenue,\n       AVG(outer_q.CustomerRevenue) AS AvgCustomerRevenue\nFROM (\n    SELECT c.Country, c.CustomerID, SUM(o.TotalAmount) AS CustomerRevenue\n    FROM Customers c\n    INNER JOIN Orders o ON c.CustomerID = o.CustomerID\n    GROUP BY c.Country, c.CustomerID\n) AS outer_q\nGROUP BY outer_q.Country\nORDER BY TotalCountryRevenue DESC;",

    # 6 · Nested subqueries / CTEs
    "Q6-A · 4-level nested subquery":
        "SELECT CustomerID, FirstName, LastName\nFROM Customers\nWHERE CustomerID IN (\n    SELECT CustomerID FROM Orders\n    WHERE TotalAmount > (\n        SELECT AVG(TotalAmount) FROM Orders\n        WHERE CustomerID IN (\n            SELECT CustomerID FROM Customers WHERE Country = \'Romania\'\n        )\n    )\n);",

    "Q6-B · Redundant CTE evaluated twice":
        "WITH ProductSales AS (\n    SELECT od.ProductID, SUM(od.Quantity * od.UnitPrice) AS TotalSales\n    FROM OrderDetails od GROUP BY od.ProductID\n),\nTopProducts AS (\n    SELECT ProductID FROM ProductSales WHERE TotalSales > 10000\n),\nProductSalesAgain AS (\n    SELECT od.ProductID, MONTH(o.OrderDate) AS OrderMonth,\n           SUM(od.Quantity * od.UnitPrice) AS MonthlySales\n    FROM OrderDetails od INNER JOIN Orders o ON od.OrderID = o.OrderID\n    GROUP BY od.ProductID, MONTH(o.OrderDate)\n)\nSELECT p.ProductName, psa.OrderMonth, psa.MonthlySales\nFROM ProductSalesAgain psa\nINNER JOIN TopProducts tp ON psa.ProductID = tp.ProductID\nINNER JOIN Products p ON psa.ProductID = p.ProductID\nORDER BY p.ProductName, psa.OrderMonth;",

    "Q6-C · IN with large subquery (vs EXISTS)":
        "SELECT c.CustomerID, c.Email, c.Country\nFROM Customers c\nWHERE c.CustomerID IN (\n    SELECT o.CustomerID FROM Orders o\n    INNER JOIN OrderDetails od ON o.OrderID = od.OrderID\n    INNER JOIN Products p ON od.ProductID = p.ProductID\n    INNER JOIN Categories cat ON p.CategoryID = cat.CategoryID\n    WHERE cat.CategoryName = \'Electronics\' AND o.OrderDate >= \'2023-01-01\'\n);",

    "Q6-E · Mixed: SELECT * + non-SARGable + nested":
        "SELECT *\nFROM (\n    SELECT * FROM Orders\n    WHERE CONVERT(VARCHAR(7), OrderDate, 120) = \'2023-11\'\n) AS NovemberOrders\nWHERE CustomerID IN (\n    SELECT CustomerID FROM Customers WHERE UPPER(Country) = \'ROMANIA\'\n);",
}


# ══════════════════════════════════════════════════════════════════════════════
# LLM CALLERS
# ══════════════════════════════════════════════════════════════════════════════
def extract_sql(text):
    m = re.search(r"```sql\s*(.*?)\s*```", text, re.DOTALL)
    return m.group(1).strip() if m else text.replace("```", "").strip()

def call_gpt(prompt):
    try:
        client = OpenAI(api_key=GPT_API_KEY, base_url="https://models.inference.ai.azure.com")
        r = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return extract_sql(r.choices[0].message.content)
    except Exception as e:
        return f"-- GPT Error: {e}"

def call_gemini(prompt):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-3-flash-preview")  
        r = model.generate_content(prompt)
        return extract_sql(r.text)
    except Exception as e:
        return f"-- Gemini Error: {e}"

def call_llama(prompt):
    try:
        client = OpenAI(api_key=LLAMA_API_KEY, base_url=LLAMA_BASE_URL)
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return extract_sql(r.choices[0].message.content)
    except Exception as e:
        return f"-- Llama Error: {e}"

LLM_CALLERS = {
    "GPT-4o":  (call_gpt,    "llm-gpt"),
    "Gemini":  (call_gemini, "llm-gemini"),
    "Llama 3": (call_llama,  "llm-llama"),
}

# ══════════════════════════════════════════════════════════════════════════════
# DB CONNECTION & MEASUREMENT
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_resource
def init_connection():
    return pymssql.connect(
        server="127.0.0.1", port=1436,
        user="sa", password="Disertatie__2026!",
        database="EcommAnalytics",
    )

def measure_query(conn, sql):
    res = {"elapsed_ms": 0, "logical_reads": None, "cpu_ms": None, "error": None}
    try:
        cursor = conn.cursor()
        cursor.execute("DBCC DROPCLEANBUFFERS; DBCC FREEPROCCACHE;")
        t0 = time.perf_counter()
        cursor.execute(sql)
        cursor.fetchall()
        res["elapsed_ms"] = (time.perf_counter() - t0) * 1000
        cursor.execute("""
            SELECT TOP 1 qs.total_logical_reads, qs.total_worker_time / 1000
            FROM sys.dm_exec_query_stats qs
            CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
            WHERE st.text NOT LIKE '%dm_exec_query_stats%'
            ORDER BY qs.last_execution_time DESC;
        """)
        row = cursor.fetchone()
        if row:
            res["logical_reads"] = row[0]
            res["cpu_ms"]        = row[1]
    except Exception as e:
        res["error"] = str(e)
    return res

# ══════════════════════════════════════════════════════════════════════════════
# RESULTS PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════
def save_result(row: dict):
    exists = os.path.isfile(RESULTS_FILE)
    with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=row.keys())
        if not exists:
            w.writeheader()
        w.writerow(row)

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## ⚡ SQL LLM Benchmark")
    st.caption("LLM performance on T-SQL optimisation")
    st.divider()

    scenario_name   = st.selectbox("📌 Query scenario", list(SCENARIOS.keys()),
                                    key="scenario_select")
    selected_llms   = st.multiselect("🤖 LLMs to test",
                                     options=list(LLM_CALLERS.keys()),
                                     default=["GPT-4o"])
    prompt_strategy = st.radio("📐 Prompt strategy",
                               options=list(PROMPT_STRATEGIES.keys()),
                               key="prompt_radio")
    run_btn = st.button("🚀 Run benchmark", type="primary", use_container_width=True)

    # Sync into session_state so main area always reads the latest values
    st.session_state["active_scenario"] = scenario_name
    st.session_state["active_prompt"]   = prompt_strategy

    st.divider()
    st.markdown("### 📁 Export results")
    if os.path.isfile(RESULTS_FILE):
        df_log = pd.read_csv(RESULTS_FILE)
        st.download_button("⬇️ Download CSV",
                           data=df_log.to_csv(index=False),
                           file_name="benchmark_results.csv",
                           mime="text/csv",
                           use_container_width=True)
        st.caption(f"{len(df_log)} runs saved")
    else:
        st.caption("No results yet.")

    st.divider()
    st.markdown("### 🔑 API key status")
    for label, key in [("GPT-4o", GPT_API_KEY),
                       ("Gemini", GEMINI_API_KEY),
                       ("Llama 3 (Groq)", LLAMA_API_KEY)]:
        ok = bool(key and len(key) > 10)
        st.markdown(f"{'🟢' if ok else '🔴'} {label}")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN — QUERY EDITOR
# ══════════════════════════════════════════════════════════════════════════════
# Read latest values from session_state (fixes prompt strategy not updatin)

active_scenario  = st.session_state.get("active_scenario", list(SCENARIOS.keys())[0])
active_prompt    = st.session_state.get("active_prompt",   list(PROMPT_STRATEGIES.keys())[0])

fn, badge_cls, badge_label = PROMPT_STRATEGIES[active_prompt]

st.markdown(f"### {active_scenario}")
st.markdown(f'<span class="prompt-badge {badge_cls}">{badge_label} · {active_prompt}</span>',
            unsafe_allow_html=True)

# Dynamic key forces Streamlit to re-render the text_area when scenario changes
anti_sql = st.text_area(
    "❌ Anti-pattern query (editable):",
    value=SCENARIOS[active_scenario],
    height=220,
    key=f"anti_sql_{active_scenario}",
)

with st.expander("👁 Preview prompt sent to LLMs"):
    if anti_sql.strip():
        st.code(fn(anti_sql), language="text")
    else:
        st.info("Enter a query above to preview the prompt.")

# ══════════════════════════════════════════════════════════════════════════════
# RUN BENCHMARK
# ══════════════════════════════════════════════════════════════════════════════
if run_btn:
    if not anti_sql.strip():
        st.warning("Please enter a query first.")
        st.stop()
    if not selected_llms:
        st.warning("Select at least one LLM in the sidebar.")
        st.stop()

    try:
        conn = init_connection()
    except Exception as e:
        st.error(f"DB connection failed: {e}")
        st.stop()

    full_prompt = fn(anti_sql)

    st.divider()
    st.markdown("### 📊 Benchmark results")

    # Baseline
    with st.spinner("Measuring baseline…"):
        baseline = measure_query(conn, anti_sql)

    if baseline["error"]:
        st.error(f"Baseline query failed: {baseline['error']}")
        st.stop()

    st.markdown("**Baseline (anti-pattern)**")
    b1, b2, b3 = st.columns(3)
    b1.metric("Elapsed time",  f"{baseline['elapsed_ms']:.1f} ms")
    b2.metric("Logical reads", str(baseline["logical_reads"] or "N/A"))
    b3.metric("CPU time",      f"{baseline['cpu_ms']} ms" if baseline["cpu_ms"] else "N/A")
    st.divider()

    # LLM results
    cols = st.columns(len(selected_llms))
    winner_llm, winner_speedup = None, 0.0
    table_rows = []

    for i, llm in enumerate(selected_llms):
        caller, css_cls = LLM_CALLERS[llm]
        with cols[i]:
            st.markdown(f'<span class="llm-header {css_cls}">{llm}</span>', unsafe_allow_html=True)
            st.markdown(f'<span class="prompt-badge {badge_cls}">{badge_label}</span>', unsafe_allow_html=True)

            with st.spinner(f"{llm} optimising…"):
                opt_sql = caller(full_prompt)
            st.code(opt_sql, language="sql")

            with st.spinner("Measuring…"):
                m = measure_query(conn, opt_sql)

            if m["error"]:
                st.error(f"SQL error: {m['error']}")
                continue

            delta_ms = m["elapsed_ms"] - baseline["elapsed_ms"]
            speedup  = baseline["elapsed_ms"] / m["elapsed_ms"] if m["elapsed_ms"] > 0 else 0

            st.metric("Elapsed time",  f"{m['elapsed_ms']:.1f} ms",
                      delta=f"{delta_ms:+.1f} ms", delta_color="inverse")
            st.metric("Logical reads", str(m["logical_reads"] or "N/A"))
            st.metric("CPU time",      f"{m['cpu_ms']} ms" if m["cpu_ms"] else "N/A")

            if speedup > 1.05:
                st.success(f"🔥 {speedup:.2f}× faster")
                if speedup > winner_speedup:
                    winner_speedup, winner_llm = speedup, llm
            elif speedup < 0.95:
                st.error(f"🐌 {1/speedup:.2f}× slower")
            else:
                st.warning("⚖️ Similar performance")

            save_result({
                "timestamp":              datetime.now().isoformat(timespec="seconds"),
                "scenario":               scenario_name,
                "prompt_strategy":        prompt_strategy,
                "llm":                    llm,
                "baseline_elapsed_ms":    round(baseline["elapsed_ms"], 2),
                "optimized_elapsed_ms":   round(m["elapsed_ms"], 2),
                "speedup":                round(speedup, 3),
                "baseline_logical_reads": baseline["logical_reads"],
                "opt_logical_reads":      m["logical_reads"],
                "baseline_cpu_ms":        baseline["cpu_ms"],
                "opt_cpu_ms":             m["cpu_ms"],
            })

            table_rows.append({
                "LLM":           llm,
                "Prompt":        prompt_strategy,
                "Elapsed (ms)":  round(m["elapsed_ms"], 1),
                "Speedup":       f"{speedup:.2f}×",
                "Logical reads": m["logical_reads"] or "N/A",
                "CPU (ms)":      m["cpu_ms"] or "N/A",
            })

    if winner_llm:
        st.markdown(
            f'<div class="winner-box">🏆 Best: {winner_llm} ({prompt_strategy}) — {winner_speedup:.2f}× faster</div>',
            unsafe_allow_html=True,
        )

    if table_rows:
        st.divider()
        st.markdown("#### ⏱ Elapsed time comparison")
        chart_df = pd.DataFrame(
            [{"Query": "Anti-pattern", "ms": round(baseline["elapsed_ms"], 1)}]
            + [{"Query": r["LLM"], "ms": float(r["Elapsed (ms)"])} for r in table_rows]
        ).set_index("Query")
        st.bar_chart(chart_df, color="#10a37f")

        st.markdown("#### 📋 Full metrics table")
        st.dataframe(pd.DataFrame(table_rows).set_index("LLM"), use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# RESULTS HISTORY
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
with st.expander("📈 All recorded results + summary", expanded=False):
    if os.path.isfile(RESULTS_FILE):
        df_all = pd.read_csv(RESULTS_FILE)
        st.dataframe(df_all, use_container_width=True)

        st.markdown("#### Average speedup — LLM × Prompt strategy")
        pivot = (
            df_all.groupby(["llm", "prompt_strategy"])["speedup"]
            .mean().round(3).unstack(fill_value=0)
        )
        st.dataframe(pivot, use_container_width=True)

        st.markdown("#### Best result per scenario")
        best = (
            df_all.sort_values("speedup", ascending=False)
            .groupby("scenario").first()
            [["llm", "prompt_strategy", "speedup"]].reset_index()
        )
        st.dataframe(best, use_container_width=True)
    else:
        st.info("Run some benchmarks — results will appear here.")
