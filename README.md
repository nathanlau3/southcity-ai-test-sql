# SouthCity Text-to-SQL

Chatbot untuk bertanya data penjualan dan penagihan properti SouthCity dalam Bahasa Indonesia.
Pertanyaan diubah menjadi query SQL read-only, dibatasi sesuai role user, lalu dijawab dalam
bahasa natural.

Stack: LangGraph, OpenAI, sqlglot, SQLite, Streamlit.

Demo: https://southcity.text-2-sql.nathan-dev.online

## Menjalankan

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # isi OPENAI_API_KEY
streamlit run streamlit_app.py
```

Database dibuat otomatis dari `schema.sql` saat aplikasi pertama kali jalan.

Atau dengan Docker: `docker compose up -d --build`, lalu buka http://localhost:8501.

## Test

```bash
pytest -m "not llm"   # tanpa API key
pytest -m llm         # memanggil LLM
```

## Akun

| Username | Role | Akses |
|---|---|---|
| sales_bambang | Sales (AgentID 101) | kontrak sendiri |
| sales_dewi | Sales (AgentID 102) | kontrak sendiri |
| sales_reza | Sales (AgentID 103) | kontrak sendiri |
| finance_hendra | Finance | semua data |
| auditor_maya | Auditor | semua data |

Arsitektur, keamanan, dan RBAC dijelaskan di [ARCHITECTURE.md](ARCHITECTURE.md).
