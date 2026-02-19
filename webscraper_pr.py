import requests
import json
import os
import time
import urllib3
from datetime import datetime

# --- Configuração ---
API_PERIODOS = "https://www1.tce.pr.gov.br/proxy/remuneracoes/api/mes-ano"
API_DADOS = "https://www1.tce.pr.gov.br/proxy/remuneracoes/api/remuneracoes"
OUTPUT_FOLDER = "Dados_PR"

START_YEAR = 2020
END_YEAR = 2025

# Mapeamento para definir quem é ATIVO e quem é INATIVO
# O script usará isso para preencher o campo "situacao"
CATEGORIAS_MAP = {
    "ATIVO": [
        "Membros",
        "Efetivos",
        "Cargos Comissionados",
        "Assessoria Militar"
    ],
    "INATIVO": [
        "Aposentados"
    ]
}

# Desativar avisos de segurança (SSL)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Headers para passar pelo Proxy do governo
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www1.tce.pr.gov.br/",
    "Host": "www1.tce.pr.gov.br"
}

# --- Funções Auxiliares ---

def clean_currency(value_str):
    if not value_str: return 0.0
    clean = value_str.replace('.', '').replace(',', '.')
    try:
        return float(clean)
    except:
        return 0.0

def fetch_periods():
    """Busca a lista de meses disponíveis no site."""
    print("📡 Buscando períodos disponíveis...")
    try:
        response = requests.get(API_PERIODOS, headers=HEADERS, timeout=30, verify=False)
        response.raise_for_status()
        raw_list = response.json()
        
        grouped_periods = {}
        
        for item in raw_list:
            valor = item.get('valor', '')
            try:
                # Ex: "2025.05 Suplementar I" -> ano=2025, mes=05
                parts = valor.split(' ')[0].split('.') 
                year = int(parts[0])
                month = int(parts[1])
                
                if year < START_YEAR or year > END_YEAR:
                    continue
                
                key = f"{year}-{month:02d}" # Chave para agrupar (ex: 2025-05)
                
                if key not in grouped_periods:
                    grouped_periods[key] = []
                grouped_periods[key].append(valor)
            except:
                continue
        return grouped_periods
    except Exception as e:
        print(f"❌ Erro ao buscar períodos: {e}")
        return {}

def fetch_payroll_data(period_string, natureza):
    """Busca os dados da API. Retorna lista vazia se der erro 400 (categoria vazia)."""
    params = {
        "mesAno": period_string,
        "natureza": natureza,
        "cargo": "" 
    }
    
    try:
        response = requests.get(API_DADOS, params=params, headers=HEADERS, timeout=60, verify=False)
        
        if response.status_code == 400:
            # Categoria não existe nesse mês (ex: não teve Estagiário em 2020)
            return []
            
        response.raise_for_status()
        return response.json()

    except Exception as e:
        print(f"    ! Erro ao buscar '{natureza}' em '{period_string}': {e}")
        return []

def process_grid_details(detalhes_grid):
    """Achata a lista de detalhes em um dicionário simples."""
    flat_data = {}
    if not detalhes_grid: return flat_data
    
    for item in detalhes_grid:
        key = item.get('titulo', '').strip()
        val_str = item.get('valor', '').strip()
        
        # Se parece número e não é matrícula, converte para float
        if any(char.isdigit() for char in val_str) and "MATRICULA" not in key.upper() and "LOTAÇÃO" not in key.upper():
             flat_data[key] = clean_currency(val_str)
        else:
             flat_data[key] = val_str
    return flat_data

def main():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        print(f"Pasta '{OUTPUT_FOLDER}' verificada.")
    
    start_time = datetime.now()
    print(f"--- Iniciando Scraper PR em {start_time.strftime('%H:%M:%S')} ---")

    # 1. Pega os meses
    periods_map = fetch_periods()
    print(f"📅 Encontrados {len(periods_map)} meses para processar.")
    
    sorted_months = sorted(periods_map.keys(), reverse=True)

    # 2. Loop pelos Meses (Agrupados)
    for year_month in sorted_months:
        specific_periods = periods_map[year_month]
        print(f"\n============================================")
        print(f"  Processando Mês: {year_month}")
        print(f"    Folhas: {specific_periods}")
        print(f"============================================")
        
        month_consolidated_data = []

        # 3. Loop pelas Folhas do mês (Normal, Suplementar...)
        for period_str in specific_periods:
            
            # 4. Loop pelas Categorias (ATIVO / INATIVO)
            for situacao, lista_naturezas in CATEGORIAS_MAP.items():
                for nat in lista_naturezas:
                    
                    # Exibe progresso visual no terminal
                    print(f"  > Buscando: {nat} ({situacao}) em {period_str}...", end="\r")
                    
                    raw_data = fetch_payroll_data(period_str, nat)
                    
                    if not raw_data:
                        continue
                    
                    # Processa os dados
                    for entry in raw_data:
                        financial_details = process_grid_details(entry.get('detalhesGrid', []))
                        
                        clean_obj = {
                            "situacao": situacao,       
                            "natureza_detalhada": nat,  
                            "periodo_folha": period_str,
                            "matricula": entry.get('matricula'),
                            "nome": entry.get('nome'),
                            "lotacao": entry.get('lotacao'),
                            "cargo": entry.get('cargo'),
                            "financeiro": financial_details
                        }
                        month_consolidated_data.append(clean_obj)
                    
                    time.sleep(0.1) # Delay leve
        
        print("")

        if month_consolidated_data:
            filename = f"servidores_tce_pr_{year_month.replace('-', '_')}.json"
            path = os.path.join(OUTPUT_FOLDER, filename)
            
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(month_consolidated_data, f, ensure_ascii=False, indent=4)
                print(f"✅ SALVO: {filename} ({len(month_consolidated_data)} registros)")
            except Exception as e:
                print(f"❌ Erro ao salvar: {e}")
        else:
            print(f"⚠️ Sem dados para {year_month}")

    end_time = datetime.now()
    duration = end_time - start_time
    print(f"\n🏁 Finalizado em {duration}.")

if __name__ == "__main__":
    main()