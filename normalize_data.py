"""
normalize_data.py — Normalização dos dados brutos de cada estado para o schema canônico.

Grão: uma linha por servidor × competência × folha. Tribunais que publicam uma única folha
consolidada por mês recebem folha = 'UNICA'.

Saída por registro:
    estado, matricula, nome, cargo, lotacao, situacao, mes, ano,
    folha, tipo_folha, folha_origem,
    salario_base, beneficios, descontos, salario_bruto, salario_liquido

Descartes e avisos (sem matrícula, competência inválida, fora do recorte, duplicatas,
conflitos de chave, divergências aritméticas) são gravados em logs/normalizacao_*.jsonl.

Uso:
    python normalize_data.py
Gera:
    Dados_Normalizados/remuneracoes_<ESTADO>.json
    Dados_Normalizados/remuneracoes_consolidado.json
"""

import os
import re
import csv
import json
import glob
from collections import Counter
from pathlib import Path

from registro_descartes import RegistroDescartes

BASE_DIR   = Path(__file__).parent / "Scrapers"
OUTPUT_DIR = Path(__file__).parent / "Dados_Normalizados"
OUTPUT_DIR.mkdir(exist_ok=True)

# Recorte temporal do trabalho: exercícios a partir de 2020 (TCC 1, Seção 4.1).
ANO_INICIAL = 2020
# Diferença aceita entre soma de componentes e totais publicados (arredondamento da fonte).
TOLERANCIA = 1.00

CAMPOS_VALOR = ("salario_base", "beneficios", "descontos")

FOLHA_UNICA = {"folha": "UNICA", "tipo_folha": "UNICA", "folha_origem": None}


def _parse_brl(value) -> float:
    """Converte qualquer representação monetária em float."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    text = re.sub(r"R\$\s*", "", text)
    text = text.replace(" ", "").replace("\xa0", "")
    negative = text.startswith("-")
    text = text.lstrip("-").replace(".", "").replace(",", ".")
    try:
        result = float(text)
        return -result if negative else result
    except ValueError:
        return 0.0


def _normalize_situacao(raw: str) -> str:
    if not raw:
        return "Desconhecido"
    raw_lower = raw.strip().lower()
    if any(k in raw_lower for k in ("ativo", "active")):
        return "Ativo"
    if any(k in raw_lower for k in ("inativo", "reformado", "aposentado", "pensionista")):
        return "Inativo/Aposentado"
    return raw.strip().title()


def _mes_ano_to_int(mes_ano: str):
    """'01/2024' → (1, 2024). Retorna (0, 0) se inválido."""
    try:
        parts = mes_ano.strip().split("/")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


_KEYWORDS_SALARIO = re.compile(
    r"vencimento|subsid|salari|ordenado|remuneracao|remuneração|piso|"
    r"cargo em comiss[aã]o|cargo efetivo|tabela vencimento",
    re.IGNORECASE,
)

def _classify_credito(descricao: str) -> str:
    if _KEYWORDS_SALARIO.search(str(descricao)):
        return "salario_base"
    return "beneficios"


def _parse_es(records: list, registro: RegistroDescartes) -> list:
    out = []
    for r in records:
        financeiro = r.get("financeiro", {})
        creditos   = financeiro.get("creditos", [])
        descontos  = financeiro.get("descontos", [])

        sal_base   = sum(_parse_brl(c["valor"]) for c in creditos
                         if _classify_credito(c.get("descricao", "")) == "salario_base")
        beneficios = sum(_parse_brl(c["valor"]) for c in creditos
                         if _classify_credito(c.get("descricao", "")) == "beneficios")
        total_desc = sum(abs(_parse_brl(d["valor"])) for d in descontos)

        bruto   = sal_base + beneficios
        liquido = bruto - total_desc

        mes = r.get("mes") or _mes_ano_to_int(r.get("mes_ano", ""))[0]
        ano = r.get("ano") or _mes_ano_to_int(r.get("mes_ano", ""))[1]

        out.append({
            "estado": "ES",
            "matricula": str(r.get("matricula", "") or ""),
            "nome": (r.get("nome") or "").strip().title(),
            "cargo": (r.get("cargo") or "").strip().title(),
            "lotacao": (r.get("lotacao") or "").strip(),
            "situacao": _normalize_situacao(r.get("situacao", "")),
            "mes": mes, "ano": ano,
            **FOLHA_UNICA,
            "salario_base": round(sal_base, 2),
            "beneficios": round(beneficios, 2),
            "descontos": round(total_desc, 2),
            "salario_bruto": round(bruto, 2),
            "salario_liquido": round(liquido, 2),
        })
    return out


def _parse_sp(records: list, registro: RegistroDescartes) -> list:
    out = []
    for r in records:
        proventos  = r.get("proventos", [])

        # Usar campos pré-calculados do JSON
        # salario_liquido já considera TODOS os proventos (inclusive Auxilios, etc.)
        # total_descontos é negativo no JSON
        total_desc = abs(_parse_brl(r.get("total_descontos", 0)))
        liquido    = _parse_brl(r.get("salario_liquido", 0))
        # bruto = liquido + descontos = soma real de todos os proventos
        bruto      = round(liquido + total_desc, 2)

        # Salario_base: itens classificados como base no array de proventos
        sal_base   = sum(_parse_brl(p["valor"]) for p in proventos
                         if _classify_credito(p.get("descricao", "")) == "salario_base")
        beneficios = round(bruto - sal_base, 2)

        mes, ano = _mes_ano_to_int(r.get("mes_ano", ""))

        out.append({
            "estado": "SP",
            "matricula": str(r.get("matricula", "") or ""),
            "nome": (r.get("nome") or "").strip().title(),
            "cargo": (r.get("cargo") or "").strip().title(),
            "lotacao": (r.get("lotacao") or "").strip(),
            "situacao": _normalize_situacao(r.get("tipo", "")),
            "mes": mes, "ano": ano,
            **FOLHA_UNICA,
            "salario_base": round(sal_base, 2),
            "beneficios": beneficios,
            "descontos": round(total_desc, 2),
            "salario_bruto": bruto,
            "salario_liquido": round(liquido, 2),
        })
    return out


# MG: CSV sem cabeçalho. Colunas confirmadas pela aritmética (bruto − descontos = líquido em 99,75%
# das linhas): 0 matrícula, 2 cargo, 3 bruto, 6 descontos totais, 7 líquido, 8 ano, 9 mês.
# HIPÓTESES não confirmadas pela fonte: coluna 1 = tipo de folha (1 normal, 2 complementar; o valor 2
# concentra-se em dez/jul/nov/jan) e coluna 4 = benefícios. A coluna 5 (parcela dos descontos) é ignorada.
_TIPOS_FOLHA_MG = {"1": "NORMAL", "2": "COMPLEMENTAR"}

def _parse_mg(records: list, registro: RegistroDescartes) -> list:
    out = []
    for row in records:
        try:
            tipo       = row[1].strip()
            bruto      = float(row[3])
            beneficios = float(row[4])
            total_desc = float(row[6])
            liquido    = float(row[7])
            ano, mes   = int(row[8]), int(row[9])
        except (ValueError, IndexError) as erro:
            registro.registrar("MG", "linha_csv_invalida", {"linha": row, "erro": str(erro)})
            continue

        if abs(bruto - total_desc - liquido) > TOLERANCIA:
            registro.aviso("MG", "liquido_diverge_de_bruto_menos_descontos",
                           {"matricula": row[0], "ano": ano, "mes": mes, "bruto": bruto,
                            "descontos": total_desc, "liquido_publicado": liquido})

        out.append({
            "estado": "MG",
            "matricula": row[0].strip(),
            "nome": None,
            "cargo": row[2].strip().title(),
            "lotacao": None,
            "situacao": "Desconhecido",
            "mes": mes, "ano": ano,
            "folha": f"TIPO {tipo}",
            "tipo_folha": _TIPOS_FOLHA_MG.get(tipo, "OUTRA"),
            "folha_origem": f"coluna 1 do CSV = {tipo}",
            "salario_base": round(bruto - beneficios, 2),
            "beneficios": round(beneficios, 2),
            "descontos": round(total_desc, 2),
            "salario_bruto": round(bruto, 2),
            "salario_liquido": round(bruto - total_desc, 2),
        })
    return out


def _parse_rs(records: list, registro: RegistroDescartes) -> list:
    out = []
    for r in records:
        sal_base   = _parse_brl(r.get("remuneracao_bruta", 0))
        beneficios = (
            _parse_brl(r.get("parcelas_indenizatorias", 0))
            + _parse_brl(r.get("abono_permanencia", 0))
            + _parse_brl(r.get("terco_ferias", 0))
            + _parse_brl(r.get("gratificacao_natalina", 0))
        )
        total_desc = abs(_parse_brl(r.get("descontos_legais", 0)))
        bruto   = sal_base + beneficios
        liquido = bruto - total_desc
        mes, ano = _mes_ano_to_int(r.get("mes_ano", ""))

        out.append({
            "estado": "RS",
            "matricula": str(r.get("matricula") or ""),
            "nome": (r.get("nome") or r.get("nome_servidor") or "").strip().title(),
            "cargo": (r.get("cargo") or "").strip().title(),
            "lotacao": (r.get("funcao_gratificada") or "").strip(),
            "situacao": "Desconhecido",
            "mes": mes, "ano": ano,
            **FOLHA_UNICA,
            "salario_base": round(sal_base, 2),
            "beneficios": round(beneficios, 2),
            "descontos": round(total_desc, 2),
            "salario_bruto": round(bruto, 2),
            "salario_liquido": round(liquido, 2),
        })
    return out


# PR: o rótulo do período identifica a folha ('2025.12', '2025.12 Suplementar I', '2021.04 1ª parcela 13º',
# '2020.01 + Suplementar I', '2020.13 2ª parcela 13º'). A competência 13 é o 13º pago em dezembro.
_RE_PERIODO_PR = re.compile(r"^(\d{4})\.(\d{2})\s*(.*)$")

def _folha_pr(periodo: str):
    m = _RE_PERIODO_PR.match(periodo.strip())
    if not m:
        return None
    ano, mes_rotulo = int(m.group(1)), int(m.group(2))
    resto = re.sub(r"\s+", " ", m.group(3).replace("°", "º")).strip().upper()
    resto = re.sub(r"^\+\s*", "+ ", resto)

    if "13" in resto or mes_rotulo == 13:
        parcela = re.search(r"([12])\s*ª?\s*PARCELA", resto)
        folha, tipo = (f"13º {parcela.group(1)}ª PARCELA" if parcela else "13º"), "DECIMO_TERCEIRO"
    elif resto.startswith("+"):
        folha, tipo = f"ORDINARIA {resto}", "NORMAL_COM_SUPLEMENTAR"
    elif "SUPLEMENTAR" in resto:
        folha, tipo = resto, "SUPLEMENTAR"
    elif not resto:
        folha, tipo = "ORDINARIA", "NORMAL"
    else:
        folha, tipo = resto, "OUTRA"

    if mes_rotulo == 13:
        folha += " [COMPETENCIA 13]"
    mes = 12 if mes_rotulo == 13 else mes_rotulo
    return ano, mes, {"folha": folha, "tipo_folha": tipo, "folha_origem": periodo}


def _parse_pr(records: list, registro: RegistroDescartes) -> list:
    out = []
    for r in records:
        competencia = _folha_pr(r.get("periodo_folha", ""))
        if competencia is None:
            registro.registrar("PR", "competencia_invalida", {"periodo_folha": r.get("periodo_folha")})
            continue
        ano, mes, folha = competencia
        # O TCE-PR publica cada folha por natureza funcional; a mesma matrícula pode receber em duas
        # naturezas na mesma folha (ex.: 2022.11), então a natureza compõe o identificador da folha.
        folha = {**folha, "folha": f"{folha['folha']} | {r.get('natureza') or 'SEM NATUREZA'}"}

        if r.get("valores_ausentes"):
            registro.aviso("PR", "valor_ausente_na_fonte",
                           {"matricula": r.get("matricula"), "periodo_folha": r["periodo_folha"],
                            "campos": r["valores_ausentes"]})
        # Campos sem valor na fonte (None) entram como zero; o aviso acima preserva o rastro.
        fin = {k: (v or 0.0) for k, v in r.get("financeiro", {}).items()}
        chave_bruto = next((k for k in fin if "total bruto" in k.lower()), None)
        if chave_bruto is None:
            registro.registrar("PR", "sem_total_bruto", {"matricula": r.get("matricula"), "periodo_folha": r["periodo_folha"]})
            continue

        # Total Bruto publicado é a fonte de verdade; confere-se a soma das rubricas que o antecedem no
        # grid (pela ordem, pois há rubricas publicadas sem o índice [n]).
        bruto = fin[chave_bruto]
        rubricas = list(fin)
        componentes = sum(fin[k] for k in rubricas[:rubricas.index(chave_bruto)])
        if abs(componentes - bruto) > TOLERANCIA:
            registro.aviso("PR", "componentes_divergem_do_total_bruto",
                           {"matricula": r.get("matricula"), "periodo_folha": r["periodo_folha"],
                            "total_bruto": bruto, "soma_componentes": round(componentes, 2)})
        if r.get("valores_originais_em_data"):
            registro.aviso("PR", "valor_publicado_como_data",
                           {"matricula": r.get("matricula"), "periodo_folha": r["periodo_folha"],
                            "campos": r["valores_originais_em_data"]})
        if r.get("valores_originais_em_traco"):
            registro.aviso("PR", "valor_publicado_como_traco",
                           {"matricula": r.get("matricula"), "periodo_folha": r["periodo_folha"],
                            "campos": r["valores_originais_em_traco"]})

        sal_base = sum(v for k, v in fin.items()
                       if any(p in k.lower() for p in ("vantagens fixas", "vantagens pessoais", "cargo em comiss")))
        total_desc = sum(abs(v) for k, v in fin.items()
                         if "descontos obrig" in k.lower() or "redutor constitucional" in k.lower())

        out.append({
            "estado": "PR",
            "matricula": str(r.get("matricula") or "").strip(),
            "nome": (r.get("nome") or "").strip().title(),
            "cargo": (r.get("cargo") or r.get("cargo_comissionado") or "").strip().title(),
            "lotacao": (r.get("lotacao") or "").strip(),
            "situacao": _normalize_situacao(r.get("natureza_descricao", "")),
            "mes": mes, "ano": ano,
            **folha,
            "salario_base": round(sal_base, 2),
            "beneficios": round(bruto - sal_base, 2),
            "descontos": round(total_desc, 2),
            "salario_bruto": round(bruto, 2),
            "salario_liquido": round(bruto - total_desc, 2),
        })
    return out


# SC: ID_Servidor_Completo = 'matricula##mes##ano##nº da folha'.
_TIPOS_FOLHA_SC = {"1": "NORMAL", "5": "DECIMO_TERCEIRO", "7": "ESTAGIARIOS", "90": "PENSIONISTAS"}

def _parse_sc(records: list, registro: RegistroDescartes) -> list:
    out = []
    for r in records:
        detalhes = r.get("Detalhes_Remuneracao")
        if not detalhes:
            registro.registrar("SC", "sem_detalhes_de_remuneracao", {"id": r.get("ID_Servidor_Completo")})
            continue
        proventos = detalhes.get("proventos", [])
        descontos = detalhes.get("descontos", [])

        sal_base   = sum(_parse_brl(p["valor"]) for p in proventos
                         if _classify_credito(p.get("descricao", "")) == "salario_base")
        beneficios = sum(_parse_brl(p["valor"]) for p in proventos
                         if _classify_credito(p.get("descricao", "")) == "beneficios")
        total_desc = sum(abs(_parse_brl(d["valor"])) for d in descontos)

        bruto   = sal_base + beneficios
        liquido = bruto - total_desc

        partes = (r.get("ID_Servidor_Completo") or "").split("##")
        try:
            matricula, mes, ano, numero_folha = partes[0], int(partes[1]), int(partes[2]), partes[3]
        except (IndexError, ValueError):
            registro.registrar("SC", "identificador_invalido", {"id": r.get("ID_Servidor_Completo")})
            continue

        out.append({
            "estado": "SC",
            "matricula": matricula,
            "nome": (r.get("Nome") or "").strip().title(),
            "cargo": (r.get("Cargo_Principal") or "").strip().title(),
            "lotacao": None,
            "situacao": _normalize_situacao(r.get("situacao", "")),
            "mes": mes, "ano": ano,
            "folha": f"FOLHA {numero_folha}",
            "tipo_folha": _TIPOS_FOLHA_SC.get(numero_folha, "OUTRA"),
            "folha_origem": r.get("Tipo_Folha"),
            "salario_base": round(sal_base, 2),
            "beneficios": round(beneficios, 2),
            "descontos": round(total_desc, 2),
            "salario_bruto": round(bruto, 2),
            "salario_liquido": round(liquido, 2),
        })
    return out


def _parse_rj(records: list, registro: RegistroDescartes) -> list:
    out = []
    for r in records:
        remuneracao = r.get("remuneracao", {})

        def _get_val(partial: str) -> float:
            """Retorna o primeiro valor cujo chave contenha partial (case-insensitive)."""
            for key, val in remuneracao.items():
                if partial.lower() in key.lower():
                    return _parse_brl(val)
            return 0.0

        # salario_base = apenas a remuneração do cargo efetivo (fixo permanente)
        sal_base   = _get_val("cargo efetivo")
        # bruto = total bruto pré-calculado (fonte de verdade)
        bruto      = _get_val("total bruto") or round(sal_base, 2)
        # beneficios = tudo no bruto que não é salário base
        # (outras verbas, função gratificada, cargo em comissão, indenizações, etc.)
        beneficios = round(bruto - sal_base, 2)
        # descontos = total descontos pré-calculado (fonte de verdade)
        total_desc = abs(_get_val("total descontos"))
        # liquido = total líquido pré-calculado; fallback = bruto - descontos
        liquido    = _get_val("total liquido") or round(bruto - total_desc, 2)

        try:
            partes = r.get("mes_ano", "").split("-")
            mes = int(partes[0].strip())
            ano = int(partes[1].strip())
        except Exception:
            mes, ano = 0, 0

        out.append({
            "estado":          "RJ",
            "matricula":       str(r.get("matricula", "") or ""),
            "nome":            (r.get("nome") or "").strip().title(),
            "cargo":           (r.get("cargo") or "").strip().title(),
            "lotacao":         (r.get("localizacao") or "").strip(),
            "situacao":        "Desconhecido",
            "mes":             mes,
            "ano":             ano,
            **FOLHA_UNICA,
            "salario_base":    round(sal_base, 2),
            "beneficios":      beneficios,
            "descontos":       round(total_desc, 2),
            "salario_bruto":   round(bruto, 2),
            "salario_liquido": round(liquido, 2),
        })
    return out


def _ler_jsons(pasta: Path, pattern: str):
    """Gera (nome do arquivo, lista de registros) para cada JSON bruto da pasta."""
    for filepath in sorted(glob.glob(str(pasta / pattern))):
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
        yield os.path.basename(filepath), (raw if isinstance(raw, list) else [raw])


def _ler_csv_mg(pasta: Path, pattern: str):
    caminho = pasta / pattern
    with open(caminho, encoding="utf-8", newline="") as f:
        yield caminho.name, list(csv.reader(f, delimiter=";"))


ESTADO_CONFIG = {
    "ES": {"pasta": "Dados_ES", "leitor": _ler_jsons,  "parser": _parse_es, "pattern": "tce_es_*.json"},
    "SP": {"pasta": "Dados_SP", "leitor": _ler_jsons,  "parser": _parse_sp, "pattern": "tce_sp_*.json"},
    "MG": {"pasta": "",         "leitor": _ler_csv_mg, "parser": _parse_mg, "pattern": "Remuneracao_mg.csv"},
    "RS": {"pasta": "Dados_RS", "leitor": _ler_jsons,  "parser": _parse_rs, "pattern": "tce_rs_*.json"},
    "PR": {"pasta": "Dados_PR", "leitor": _ler_jsons,  "parser": _parse_pr, "pattern": "tce_pr_*.json"},
    "SC": {"pasta": "Dados_SC", "leitor": _ler_jsons,  "parser": _parse_sc, "pattern": "tce_sc_*.json"},
    "RJ": {"pasta": "Dados_RJ", "leitor": _ler_jsons,  "parser": _parse_rj, "pattern": "tce_rj_*.json"},
}


def _validar(estado: str, registros: list, registro: RegistroDescartes) -> list:
    """Descarta registros sem chave válida, fora do recorte ou sem nenhum valor, registrando cada caso."""
    validos, fora_do_recorte, sem_valores = [], Counter(), Counter()
    for rec in registros:
        chave = {"matricula": rec["matricula"], "ano": rec["ano"], "mes": rec["mes"], "folha": rec["folha"]}
        if not rec["matricula"]:
            registro.registrar(estado, "sem_matricula", {**chave, "nome": rec.get("nome")})
        elif not (1 <= (rec["mes"] or 0) <= 12) or (rec["ano"] or 0) < 2000:
            registro.registrar(estado, "competencia_invalida", chave)
        elif rec["ano"] < ANO_INICIAL:
            fora_do_recorte[rec["ano"]] += 1
        elif all(rec[c] == 0 for c in CAMPOS_VALOR):
            # Competência gravada sem nenhum valor (ex.: servidores desligados no RJ).
            sem_valores[rec["ano"]] += 1
        else:
            validos.append(rec)
    # Casos esperados e volumosos são registrados de forma agregada, por ano.
    for ano, qtd in sorted(fora_do_recorte.items()):
        registro.registrar(estado, "fora_do_recorte_temporal", {"ano": ano, "quantidade": qtd})
    for ano, qtd in sorted(sem_valores.items()):
        registro.registrar(estado, "competencia_sem_valores", {"ano": ano, "quantidade": qtd})
    return validos


def _deduplicar(estado: str, registros: list, registro: RegistroDescartes) -> list:
    """Mantém um registro por (matrícula, ano, mês, folha); duplicatas idênticas e conflitos são registrados."""
    vistos, saida, repeticoes = {}, [], Counter()
    for rec in registros:
        chave = (rec["matricula"], rec["ano"], rec["mes"], rec["folha"])
        anterior = vistos.get(chave)
        if anterior is None:
            vistos[chave] = rec
            saida.append(rec)
        elif all(abs(anterior[c] - rec[c]) < 0.005 for c in CAMPOS_VALOR):
            repeticoes[chave] += 1
        else:
            registro.registrar(estado, "conflito_de_chave", {
                "chave": chave,
                "mantido": {c: anterior[c] for c in CAMPOS_VALOR},
                "descartado": {c: rec[c] for c in CAMPOS_VALOR},
            })
    for chave, qtd in repeticoes.items():
        registro.registrar(estado, "duplicata_identica", {"chave": chave, "repeticoes": qtd})
    return saida


def normalize_estado(estado: str, registro: RegistroDescartes) -> list:
    cfg    = ESTADO_CONFIG[estado]
    pasta  = BASE_DIR / cfg["pasta"]
    parser = cfg["parser"]

    all_records = []
    try:
        for nome_arquivo, raw in cfg["leitor"](pasta, cfg["pattern"]):
            parsed = parser(raw, registro)
            all_records.extend(parsed)
            print(f"  ✓ {nome_arquivo}: {len(parsed):,} registros")
    except (FileNotFoundError, json.JSONDecodeError) as erro:
        registro.registrar(estado, "arquivo_ilegivel", {"erro": str(erro)})
        print(f"  [ERRO] {estado}: {erro}")

    if not all_records:
        print(f"  [AVISO] Nenhum registro obtido para {estado}")
        return []

    validos = _validar(estado, all_records, registro)
    return _deduplicar(estado, validos, registro)


def run():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    registro = RegistroDescartes("normalizacao")
    todos = []
    for estado in ESTADO_CONFIG:
        print(f"\n-- Processando {estado} --")
        registros = normalize_estado(estado, registro)
        todos.extend(registros)

        out_file = OUTPUT_DIR / f"remuneracoes_{estado.lower()}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(registros, f, ensure_ascii=False, indent=2)
        print(f"  -> Salvo: {out_file.name}  ({len(registros):,} registros)")

    consolidado = OUTPUT_DIR / "remuneracoes_consolidado.json"
    with open(consolidado, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)

    print(f"\nTOTAL CONSOLIDADO: {len(todos):,} registros")
    print(f"Arquivo: {consolidado}")
    registro.imprimir_resumo()
    caminho_log = registro.salvar()
    if caminho_log:
        print(f"Log de descartes: {caminho_log}")


if __name__ == "__main__":
    run()
