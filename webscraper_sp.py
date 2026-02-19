import requests
from bs4 import BeautifulSoup
import json
import os
import time
from datetime import datetime

# --- Configurações ---
BASE_URL = "https://www.tce.sp.gov.br/transparencia-tcesp/gestao-pessoas/remuneracao/tabela"
OUTPUT_FOLDER = "Dados_SP"

# Mapeamento conforme o HTML que você forneceu:
# <option value="1">2025</option> ... <option value="5">2021</option>
YEAR_MAP = {
    2025: 1,
    2024: 2,
    2023: 3,
    2022: 4,
    2021: 5
}

# Códigos de situação (não mudaram)
SITUATIONS = {
    1: "ATIVO",
    2: "INATIVO"
}

# --- Funções Auxiliares ---

def parse_num(txt):
    """Converte string de moeda (PT-BR) para float."""
    if not txt:
        return 0.0
    t = txt.strip().replace(".", "").replace(",", ".")
    try:
        return float(t)
    except:
        return 0.0

def fetch_data_for_month(year_label, year_id, month):
    """
    Busca dados para um mês/ano específico em todas as situações.
    Recebe o ANO REAL (label) para salvar no JSON, e o ID (1-5) para enviar na requisição.
    """
    month_data = []
    
    for cod_situacao, nome_situacao in SITUATIONS.items():
        print(f"  > Processando: {nome_situacao}...")
        
        page = 1
        while True:
            # Params para o GET
            # Note que usamos 'year_id' (1 a 5) aqui
            params = {
                "vencimentos_ano": year_id,
                "Mes": month,
                "Situacao": cod_situacao,
                "Nome": "",
                "Identificacao": 1,
                "page": page
            }
            
            try:
                res = requests.get(BASE_URL, params=params, timeout=30)
                res.raise_for_status()
            except requests.RequestException as e:
                print(f"    ! Erro na requisição (Pág {page}): {e}")
                break

            soup = BeautifulSoup(res.text, "html.parser")
            tabela = soup.select_one("div.table-responsive table.table-hover.table-striped tbody")
            
            # Se a tabela não existe, acabaram as páginas ou não tem dados
            if not tabela:
                break
            
            rows = tabela.find_all("tr")
            if not rows:
                break
            
            count_new = 0
            for tr in rows:
                td = tr.find_all("td")
                if len(td) < 21:
                    continue

                # Extração dos dados
                nome = td[3].text.strip()
                cargo = td[20].text.strip()
                
                # Lista de Proventos
                proventos_raw = [
                    ("Vencimentos", td[5].text.strip()),
                    ("Vantagens Pessoais", td[6].text.strip()),
                    ("Outras Verbas", td[7].text.strip()),
                    ("Eventuais", td[11].text.strip()),
                    ("Abono Permanência", td[12].text.strip()),
                    ("Auxílios", td[13].text.strip()),
                    ("1/3 Férias", td[14].text.strip()),
                    ("13º Salário", td[16].text.strip()),
                    ("13º Abono", td[17].text.strip()),
                ]
                proventos = [{"descricao": desc, "valor": val} for desc, val in proventos_raw if parse_num(val) != 0]

                # Lista de Descontos
                descontos_raw = [
                    ("Redutor", td[8].text.strip()),
                    ("Descontos Legais", td[10].text.strip()),
                    ("Desconto Férias", td[15].text.strip()),
                    ("Desconto 13º", td[18].text.strip()),
                ]
                descontos = [{"descricao": desc, "valor": val} for desc, val in descontos_raw if parse_num(val) != 0]

                # Totais
                total_prov = td[9].text.strip()
                sal_liq = td[19].text.strip()
                
                # Cálculo manual do total de descontos para string
                total_desc_float = sum(parse_num(d["valor"]) for d in descontos)
                total_desc_str = f"{total_desc_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                server_obj = {
                    "nome": nome,
                    "cargo": cargo,
                    "mes_ano": f"{month:02d}/{year_label}", # Usa o ano real (ex: 2025)
                    "tipo": nome_situacao,
                    "proventos": proventos,
                    "descontos": descontos,
                    "total_proventos": total_prov,
                    "total_descontos": total_desc_str,
                    "salario_liquido": sal_liq,
                    "url_origem": res.url
                }
                
                month_data.append(server_obj)
                count_new += 1
            
            next_page_link = soup.find("a", {"rel": "next"})
            if not next_page_link:
                break
            
            page += 1
            time.sleep(0.1)
            
    return month_data

def main():
    """
    Orquestra a extração usando o YEAR_MAP.
    """
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        print(f"Pasta '{OUTPUT_FOLDER}' criada.")
    
    start_time = datetime.now()
    
    for year_label, year_id in YEAR_MAP.items():
        
        # Define limite de mês para 2025 (até Outubro)
        last_month = 10 if year_label == 2025 else 12
        
        for month in range(1, last_month + 1):
            print(f"\n=== Iniciando extração: {month:02d}/{year_label} (ID Ano: {year_id}) ===")
            
            data = fetch_data_for_month(year_label, year_id, month)
            
            if not data:
                print(f"Nenhum dado encontrado para {month:02d}/{year_label}.")
                continue
            
            filename = f"servidores_tce_sp_completo_{month:02d}_{year_label}.json"
            filepath = os.path.join(OUTPUT_FOLDER, filename)
            
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                print(f"Salvo: {filepath} ({len(data)} registros)")
            except IOError as e:
                print(f"Erro ao salvar arquivo: {e}")
            
            # Delay entre meses
            time.sleep(0.5)

    end_time = datetime.now()
    print(f"\nExtração finalizada em {end_time - start_time}.")

if __name__ == "__main__":
    main()