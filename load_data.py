"""
load_data.py — Carrega os JSONs normalizados no SQL Server.

Uso:
    python load_data.py [--estado ES] [--batch 500]

Conexão configurada em settings.py (arquivo .env / variáveis DB_SERVER, DB_NAME,
DB_USER, DB_PASSWORD; DB_USER vazio usa autenticação do Windows).
"""

import json
import argparse
import csv
from pathlib import Path
from typing import Optional

import pyodbc

from settings import get_database_settings

NORMALIZED_DIR = Path(__file__).parent / "Dados_Normalizados"
MG_CSV_PATH    = Path(__file__).parent / "Scrapers" / "Remuneracao_mg.csv"


def get_connection() -> pyodbc.Connection:
    return pyodbc.connect(get_database_settings().connection_string(), autocommit=False)


def get_estado_map(cur: pyodbc.Cursor) -> dict[str, int]:
    cur.execute("SELECT sigla, estado_id FROM dbo.dim_estado")
    return {row[0]: row[1] for row in cur.fetchall()}


def upsert_cargos(cur: pyodbc.Cursor, descricoes: set[str]) -> dict[str, int]:
    if not descricoes:
        return {}

    existing: dict[str, int] = {}
    cur.execute("SELECT descricao, cargo_id FROM dbo.dim_cargo")
    for row in cur.fetchall():
        existing[row[0]] = row[1]

    novos = [d for d in descricoes if d not in existing]
    if novos:
        cur.executemany(
            "INSERT INTO dbo.dim_cargo (descricao) VALUES (?)",
            [(d,) for d in novos],
        )
        cur.connection.commit()
        cur.execute("SELECT descricao, cargo_id FROM dbo.dim_cargo")
        existing = {row[0]: row[1] for row in cur.fetchall()}

    return existing


def get_existing_keys(cur: pyodbc.Cursor, estado_id: int) -> set[tuple]:
    cur.execute(
        "SELECT matricula, mes, ano FROM dbo.fato_remuneracao WITH (NOLOCK) WHERE estado_id = ? AND matricula IS NOT NULL",
        estado_id,
    )
    return {(r[0], r[1], r[2]) for r in cur.fetchall()}


def load_records(records: list[dict], conn: pyodbc.Connection, estado_id_map: dict, batch_size: int = 5000) -> tuple[int, int]:
    cur = conn.cursor()

    descricoes = {r.get("cargo") for r in records if r.get("cargo")}
    cargo_map = upsert_cargos(cur, descricoes)

    estado_id = None
    if records:
        sigla = records[0].get("estado", "")
        estado_id = estado_id_map.get(sigla)

    existing_keys: set[tuple] = set()
    if estado_id is not None:
        existing_keys = get_existing_keys(cur, estado_id)

    rows_to_insert = []
    skipped = 0

    for rec in records:
        sigla    = rec.get("estado", "")
        est_id   = estado_id_map.get(sigla)
        if est_id is None:
            skipped += 1
            continue

        cargo_desc = rec.get("cargo")
        cargo_id   = cargo_map.get(cargo_desc) if cargo_desc else None

        matricula = rec.get("matricula") or None
        if matricula == "":
            matricula = None

        mes = rec.get("mes")
        ano = rec.get("ano")

        if matricula and (matricula, mes, ano) in existing_keys:
            skipped += 1
            continue

        rows_to_insert.append((
            est_id,
            cargo_id,
            matricula,
            rec.get("nome"),
            rec.get("lotacao"),
            rec.get("situacao"),
            mes,
            ano,
            float(rec.get("salario_base") or 0),
            float(rec.get("beneficios")   or 0),
            float(rec.get("descontos")    or 0),
        ))

        if matricula:
            existing_keys.add((matricula, mes, ano))

    sql = """
        INSERT INTO dbo.fato_remuneracao
            (estado_id, cargo_id, matricula, nome, lotacao, situacao,
             mes, ano, salario_base, beneficios, descontos)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """

    ok = 0
    erros = 0
    for i in range(0, len(rows_to_insert), batch_size):
        lote = rows_to_insert[i: i + batch_size]
        try:
            cur.fast_executemany = True
            cur.executemany(sql, lote)
            conn.commit()
            ok += len(lote)
        except pyodbc.Error as exc:
            conn.rollback()
            erros += len(lote)
            print(f"  [ERRO lote {i // batch_size + 1}] {exc}")

        done = min(i + batch_size, len(rows_to_insert))
        print(f"  Lote {i // batch_size + 1}: {done}/{len(rows_to_insert)} inseridos")

    if skipped:
        print(f"  Pulados (duplicatas/estado inválido): {skipped:,}")

    return ok, erros


def load_mg_csv(csv_path: Path, conn: pyodbc.Connection, estado_id_map: dict, batch_size: int = 5000) -> tuple[int, int]:
    estado_id = estado_id_map.get("MG")
    if estado_id is None:
        print("  [ERRO] Estado MG não encontrado no banco.")
        return 0, 0

    cur = conn.cursor()

    records = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        for row in reader:
            if len(row) < 9:
                continue
            try:
                records.append({
                    "matricula":       row[0].strip() or None,
                    "mes":             int(row[1].strip()),
                    "cargo":           row[2].strip().title(),
                    "salario_bruto":   float(row[3].strip()),
                    "beneficios":      float(row[4].strip()),
                    "descontos":       float(row[5].strip()),
                    "salario_liquido": float(row[7].strip()),
                    "ano":             int(row[8].strip()),
                })
            except (ValueError, IndexError):
                continue

    print(f"  CSV lido: {len(records):,} registros")

    descricoes = {r["cargo"] for r in records if r["cargo"]}
    cargo_map = upsert_cargos(cur, descricoes)

    existing_keys = get_existing_keys(cur, estado_id)

    rows_to_insert = []
    skipped = 0

    for rec in records:
        matricula = rec["matricula"]
        mes       = rec["mes"]
        ano       = rec["ano"]

        if matricula and (matricula, mes, ano) in existing_keys:
            skipped += 1
            continue

        cargo_id = cargo_map.get(rec["cargo"])
        sal_base = round(rec["salario_bruto"] - rec["beneficios"], 2)

        rows_to_insert.append((
            estado_id,
            cargo_id,
            matricula,
            None,
            None,
            "Desconhecido",
            mes,
            ano,
            sal_base,
            rec["beneficios"],
            rec["descontos"],
        ))

        if matricula:
            existing_keys.add((matricula, mes, ano))

    if skipped:
        print(f"  Pulados (duplicatas): {skipped:,}")

    sql = """
        INSERT INTO dbo.fato_remuneracao
            (estado_id, cargo_id, matricula, nome, lotacao, situacao,
             mes, ano, salario_base, beneficios, descontos)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """

    ok = 0
    erros = 0
    for i in range(0, len(rows_to_insert), batch_size):
        lote = rows_to_insert[i: i + batch_size]
        try:
            cur.fast_executemany = True
            cur.executemany(sql, lote)
            conn.commit()
            ok += len(lote)
        except pyodbc.Error as exc:
            conn.rollback()
            erros += len(lote)
            print(f"  [ERRO lote {i // batch_size + 1}] {exc}")
        print(f"  Lote {i // batch_size + 1}: {min(i + batch_size, len(rows_to_insert))}/{len(rows_to_insert)} inseridos")

    return ok, erros


def run(estado: Optional[str] = None, batch_size: int = 5000) -> None:
    if estado:
        arquivos = [NORMALIZED_DIR / f"remuneracoes_{estado.lower()}.json"]
    else:
        arquivos = sorted(NORMALIZED_DIR.glob("remuneracoes_??.json"))

    conn = get_connection()
    cur  = conn.cursor()
    estado_id_map = get_estado_map(cur)

    total_ok = 0
    total_erros = 0

    # Carrega MG via CSV (fonte preferencial)
    if (estado is None or estado.upper() == "MG") and MG_CSV_PATH.exists():
        print(f"\nCarregando MG via CSV: {MG_CSV_PATH.name}")
        ok, erros = load_mg_csv(MG_CSV_PATH, conn, estado_id_map, batch_size)
        print(f"  Ok: {ok:,}  Erros: {erros:,}")
        total_ok    += ok
        total_erros += erros

    for arquivo in arquivos:
        # Pular MG — CSV é a fonte preferencial
        if arquivo.stem == "remuneracoes_mg" and MG_CSV_PATH.exists():
            print(f"\n[INFO] Pulando {arquivo.name} — usando CSV direto para MG")
            continue

        if not arquivo.exists():
            print(f"[AVISO] Arquivo não encontrado: {arquivo}")
            continue

        print(f"\nCarregando: {arquivo.name}")
        with open(arquivo, encoding="utf-8") as f:
            records = json.load(f)

        ok, erros = load_records(records, conn, estado_id_map, batch_size)
        print(f"  Ok: {ok:,}  Erros: {erros:,}")
        total_ok    += ok
        total_erros += erros

    conn.close()
    print(f"\nConcluído. Total inserido: {total_ok:,}  Erros: {total_erros:,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga dos dados normalizados no SQL Server")
    parser.add_argument("--estado", help="Sigla do estado (ex: ES). Omitir para carregar todos.")
    parser.add_argument("--batch",  type=int, default=5000, help="Tamanho do lote (default 5000)")
    args = parser.parse_args()
    run(estado=args.estado, batch_size=args.batch)

