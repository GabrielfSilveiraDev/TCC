import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime
import os

# --- Configuration ---
MAIN_URL = 'https://servicos.tcesc.tc.br/contracheque_externo/index.php'
DETAILS_URL = 'https://servicos.tcesc.tc.br/contracheque_externo/folha-individual.php'
OUTPUT_FOLDER = 'Dados_SC'

START_YEAR = 2024
END_YEAR = 2025

# Categories map: Label -> ID needed for the POST request
CATEGORIES_MAP = {
    "ATIVO": "1,3,6,8,9,11,13,16,17,19",
    "INATIVO": "2,4,10,15,18"
}

# Robustness settings
POLITE_DELAY_SECONDS = 0.25 
COOLDOWN_SECONDS = 300 # 5 minutes wait on 403/429 errors

# --- Helper Functions ---

def clean_salary_to_float(salary_str):
    """
    Summary: Cleans a Brazilian currency string to float.
    """
    if not salary_str: return 0.0
    cleaned_str = salary_str.replace('.', '').replace(',', '.')
    try:
        return float(cleaned_str)
    except ValueError:
        return 0.0

def parse_server_list(html_content):
    """
    Summary: Parses the main table rows to get basic server info.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    table_body = soup.find('tbody', id='tabelaFolhasBody')
    
    if not table_body:
        return [] 

    server_list = []
    rows = table_body.find_all('tr')
    
    for row in rows:
        cells = row.find_all('td')
        if len(cells) == 4:
            server_list.append({
                'ID_Servidor_Completo': row.get('data-id-servidor'),
                'Nome': cells[0].get_text(strip=True),
                'Cargo_Principal': cells[1].get_text(strip=True),
                'Tipo_Folha': cells[2].get_text(strip=True),
                'Salario_Liquido_R$': clean_salary_to_float(cells[3].get_text(strip=True))
            })
    return server_list

def fetch_details_persistently(session, server_id, server_name):
    """
    Summary: Fetches details with persistent retry logic (handling 403/429).
    Formats 'proventos' and 'descontos' into dictionaries.
    """
    payload = {'servidorId': server_id}
    
    while True: 
        try:
            response = session.post(DETAILS_URL, json=payload)
            response.raise_for_status()
            
            raw_details = response.json()
            
            # Reformat nested lists [["Desc", "Value"], ...] to [{"descricao": "...", "valor": "..."}]
            # to match the standard used in other scrapers.
            if 'proventos' in raw_details:
                raw_details['proventos'] = [
                    {"descricao": item[0], "valor": item[1]} for item in raw_details['proventos']
                ]
            
            if 'descontos' in raw_details:
                raw_details['descontos'] = [
                    {"descricao": item[0], "valor": item[1]} for item in raw_details['descontos']
                ]
            
            return raw_details

        except requests.exceptions.HTTPError as http_err:
            status_code = http_err.response.status_code
            # If blocked, wait and retry indefinitely
            if status_code in [403, 429, 500, 502, 503, 504]:
                print(f"     !!! BLOCKED/ERROR ({status_code}) !!! Waiting {COOLDOWN_SECONDS}s...")
                time.sleep(COOLDOWN_SECONDS)
                continue 
            else:
                print(f"  -> Unrecoverable error {status_code} for {server_name}. Skipping.")
                return None

        except requests.exceptions.RequestException:
            print(f"  -> Connection error. Waiting 30s...")
            time.sleep(30)
            continue 

        except json.JSONDecodeError:
            print(f"  -> Invalid JSON response for {server_name}. Skipping.")
            return None

def main():
    # 1. Create Output Folder
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        print(f"Folder '{OUTPUT_FOLDER}' ready.")
    
    start_time = datetime.now()
    print(f"--- Starting SC Scraper at {start_time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    total_records_saved = 0
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': MAIN_URL 
    }

    session = requests.Session()
    session.headers.update(headers)
    
    # 2. Loop Years
    for year in range(START_YEAR, END_YEAR + 1):
        
        last_month = 10 if year == 2025 else 12
        
        # 3. Loop Months
        for month in range(1, last_month + 1):
            month_str = str(month).zfill(2)
            
            print(f"\n============================================")
            print(f" 🗓️ Processing: {month_str}/{year}")
            print(f"============================================")
            
            month_consolidated_data = []

            # 4. Loop Categories (Inside the month loop to consolidate data)
            for situacao, cat_ids in CATEGORIES_MAP.items():
                print(f"  > Fetching category: {situacao}...")
                
                main_payload = {
                    'mes': month_str,
                    'ano': str(year),
                    'categorias_string': cat_ids,
                    'nome': '' 
                }
                
                # Fetch List
                try:
                    response = session.post(MAIN_URL, data=main_payload)
                    response.raise_for_status()
                    server_list = parse_server_list(response.text)
                except Exception as e:
                    print(f"    ! Error fetching list: {e}")
                    continue

                if not server_list:
                    print(f"    -> No servers found for {situacao}.")
                    continue

                # Fetch Details for each server in list
                for i, server in enumerate(server_list):
                    # Progress indicator (overwrite line)
                    print(f"    [{i+1}/{len(server_list)}] {server['Nome']}...", end='\r')
                    
                    details = fetch_details_persistently(session, server['ID_Servidor_Completo'], server['Nome'])
                    
                    # Enrich server object
                    server['Detalhes_Remuneracao'] = details
                    server['situacao'] = situacao # Add 'situacao' field
                    
                    month_consolidated_data.append(server)
                    
                    time.sleep(POLITE_DELAY_SECONDS)
                
                print("") # New line after progress bar

            # 5. Save the consolidated monthly file
            if month_consolidated_data:
                filename = f"servidores_tce_sc_completo_{month_str}_{year}.json"
                output_path = os.path.join(OUTPUT_FOLDER, filename)
                
                try:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(month_consolidated_data, f, indent=4, ensure_ascii=False)
                    
                    count = len(month_consolidated_data)
                    total_records_saved += count
                    print(f"✅ SAVED: {filename} ({count} records)")
                    
                except Exception as e:
                    print(f"❌ Error saving file: {e}")
            else:
                print(f"⚠️ No data found for {month_str}/{year}")

    end_time = datetime.now()
    duration = end_time - start_time
    print(f"\n🏁 Finished in {duration}.")
    print(f"Total records processed: {total_records_saved}")

if __name__ == "__main__":
    main()