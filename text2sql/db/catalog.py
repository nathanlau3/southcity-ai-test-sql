"""Katalog skema dan aturan bisnis yang dikirim ke LLM."""

from __future__ import annotations

import sqlite3

QUERYABLE_TABLES: tuple[str, ...] = (
    "Units",
    "Sales_Contracts",
    "Payment_Schedules",
    "Payments_Received",
    "Late_Fee_Penalties",
)

TABLE_NOTES: dict[str, str] = {
    "Units": (
        "Master unit properti fisik. Satu baris = satu unit apartemen. "
        "Tower: 'Tower A' | 'Tower B'. UnitType: 'Studio' | '2BR' | '3BR'. "
        "Status ketersediaan: 'Vacant' (tersedia) | 'Reserved' | 'Sold'. "
        "JOIN ke Sales_Contracts lewat UnitID. Tidak ada kolom harga di tabel ini "
        "(harga ada di Sales_Contracts)."
    ),
    "Sales_Contracts": (
        "Kontrak jual-beli (PPJB). Satu baris = satu kontrak untuk satu unit. "
        "Berisi data customer (CustomerName, CustomerNIK) dan harga: "
        "BasePrice (sebelum PPN), VAT_Amount (PPN 11%), TotalPrice (= BasePrice + VAT_Amount). "
        "SalesAgentID = ID sales pemilik kontrak. "
        "PaymentScheme: 'Hard Cash' | 'Installment 24x' | 'KPR Express'. "
        "ContractStatus: 'Active' | 'Cancelled' | 'Completed'. "
        "Kunci JOIN: UnitID -> Units.UnitID; ContractID dipakai oleh Payment_Schedules, "
        "Payments_Received, dan Late_Fee_Penalties. "
        "TIDAK ADA kolom nomor telepon, email, atau alamat customer."
    ),
    "Payment_Schedules": (
        "Jadwal termin tagihan (apa yang HARUS dibayar). Satu baris = satu termin. "
        "InstallmentNo = cicilan ke-n. DueDate = tanggal jatuh tempo (teks 'YYYY-MM-DD'). "
        "BillingAmount = nominal tagihan termin. "
        "BillingType: 'Booking Fee' | 'Down Payment' | 'Monthly Installment' | "
        "'Bank Disbursement' | 'Hard Cash Settlement'. "
        "Status: 'Unpaid' | 'Partially Paid' | 'Paid'. "
        "JOIN ke Sales_Contracts lewat ContractID."
    ),
    "Payments_Received": (
        "Realisasi kas masuk / kwitansi (apa yang SUDAH dibayar). Satu baris = satu pembayaran. "
        "PaidAmount = uang yang masuk. PaymentDate = tanggal bayar. "
        "PaymentMethod: 'Virtual Account BCA' | 'Bank Transfer Mandiri' | 'Cheque/Giro'. "
        "ScheduleID -> Payment_Schedules.ScheduleID (termin yang dibayar). "
        "ContractID -> Sales_Contracts.ContractID (denormalisasi, bisa langsung SUM per kontrak)."
    ),
    "Late_Fee_Penalties": (
        "Denda keterlambatan per termin (standar 1 per mil per hari). Satu baris = satu denda. "
        "PenaltyAmount = BaseOverdueAmount * DaysOverdue * DailyRatePermil. "
        "WaiverAmount = keringanan dari manajemen (nullable). "
        "PaidPenalty = denda yang sudah dibayar (nullable). "
        "PenaltyStatus: 'Outstanding' (belum lunas) | 'Settled' (lunas) | 'Waived' (dihapuskan). "
        "ScheduleID -> Payment_Schedules.ScheduleID; ContractID -> Sales_Contracts.ContractID. "
        "Untuk mengaitkan denda ke unit: Late_Fee_Penalties -> Sales_Contracts -> Units."
    ),
}

BUSINESS_RULES: list[str] = [
    (
        "Outstanding Principal (sisa pokok piutang) per kontrak = "
        "SUM(Payment_Schedules.BillingAmount) - SUM(Payments_Received.PaidAmount). "
        "Hitung kedua SUM di subquery terpisah per ContractID; JANGAN JOIN kedua "
        "tabel lalu SUM, karena baris akan terduplikasi (fan-out)."
    ),
    (
        "Net Outstanding Penalty (denda bersih yang belum dilunasi) = "
        "SUM(PenaltyAmount - COALESCE(WaiverAmount, 0) - COALESCE(PaidPenalty, 0)) "
        "untuk baris dengan PenaltyStatus = 'Outstanding'."
    ),
    (
        "Termin menunggak (overdue) = Payment_Schedules dengan DueDate < tanggal hari ini "
        "DAN Status IN ('Unpaid', 'Partially Paid')."
    ),
    (
        "Denda aktif (penghalang serah terima unit / BAST) = Late_Fee_Penalties dengan "
        "PenaltyStatus = 'Outstanding' dan nilai bersih > 0."
    ),
    (
        "Tanggal disimpan sebagai teks ISO 'YYYY-MM-DD', jadi bisa dibandingkan langsung "
        "dengan literal tanggal, mis. DueDate < '2026-11-07'."
    ),
    "Untuk filter bulan pakai strftime('%Y-%m', BookingDate) = '2026-01'.",
    (
        "Semua nominal uang dalam Rupiah. Nama customer ditulis lengkap, mis. 'Budi Santoso'; "
        "untuk pencarian nama yang tidak lengkap boleh pakai LIKE '%nama%'."
    ),
]

CATEGORY_COLUMNS: dict[str, tuple[str, ...]] = {
    "Units": ("Tower", "UnitType", "Status"),
    "Sales_Contracts": ("PaymentScheme", "ContractStatus"),
    "Payment_Schedules": ("BillingType", "Status"),
    "Payments_Received": ("PaymentMethod",),
    "Late_Fee_Penalties": ("PenaltyStatus",),
}


def get_table_ddl(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Tabel {table} tidak ada")
    return row[0]


def sample_values(conn: sqlite3.Connection, table: str, column: str, limit: int = 5) -> list:
    # Nama tabel/kolom tidak bisa lewat parameter "?", jadi divalidasi ke allowlist dulu.
    if column not in CATEGORY_COLUMNS.get(table, ()):
        raise ValueError(f"Kolom {table}.{column} bukan kolom kategori yang diizinkan")
    rows = conn.execute(
        f'SELECT DISTINCT "{column}" FROM "{table}" ORDER BY 1 LIMIT ?', (limit,)
    ).fetchall()
    return [r[0] for r in rows]


def render_schema_context(conn: sqlite3.Connection, tables: list[str]) -> str:
    requested = {t.strip().lower() for t in tables}
    selected = [t for t in QUERYABLE_TABLES if t.lower() in requested]

    parts: list[str] = []
    for table in selected:
        block = f"### {table}\n{TABLE_NOTES[table]}\n```sql\n{get_table_ddl(conn, table)}\n```"
        examples = [
            f"{col}: {', '.join(repr(v) for v in sample_values(conn, table, col))}"
            for col in CATEGORY_COLUMNS.get(table, ())
        ]
        if examples:
            block += "\nContoh nilai aktual: " + "; ".join(examples)
        parts.append(block)

    rules = "\n".join(f"- {rule}" for rule in BUSINESS_RULES)
    parts.append(f"### Aturan bisnis\n{rules}")
    return "\n\n".join(parts)
