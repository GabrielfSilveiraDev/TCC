import requests
from bs4 import BeautifulSoup
import json
import os
import time
import urllib3
import re
from datetime import datetime

# --- Configuration ---
URL_LIST = "https://acessoidentificado.tcees.tc.br/Servidores"
URL_DETAILS_BASE = "https://acessoidentificado.tcees.tc.br" # Base for relative hrefs
OUTPUT_FOLDER = "Dados_ES"
YEAR_LIMIT = 2020 

# Map of situations to iterate: Name -> ID used in the POST request
SITUATIONS = [
    ("Ativo", "0"),   # Priority 1
    ("Inativo", "1")  # Priority 2 (Check if '1' is the correct ID for Inactives on this portal)
]

# Headers (Mimicking real browser to bypass security)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://acessoidentificado.tcees.tc.br",
    "Referer": "https://acessoidentificado.tcees.tc.br/Servidores/"
}

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Helper Functions ---

def clean_text(text):
    if not text: return ""
    return text.strip().replace('\n', '').replace('\r', '').replace('\t', ' ')

def append_record_to_monthly_file(record, year, month):
    """
    Summary: Opens the specific JSON file for that Month/Year, 
    appends the new record, and saves it back.
    """
    filename = f"servidores_tce_es_completo_{month:02d}_{year}.json"
    filepath = os.path.join(OUTPUT_FOLDER, filename)

    # Load existing data
    current_data = []
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                current_data = json.load(f)
        except json.JSONDecodeError:
            pass # File corrupted or empty, start fresh

    # Append new record
    current_data.append(record)

    # Save back
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"    ❌ Error saving to {filename}: {e}")

def parse_financial_history(credits_raw, debits_raw, base_info):
    """
    Summary: Merges raw lists of credits/debits into structured monthly records.
    Returns a list of processed records ready to be saved.
    """
    history_map = {}
    
    # 1. Process Credits
    for item in credits_raw:
        year = item.get('AnoReferencia')
        month = item.get('MesReferencia')
        
        # Filter by Year
        if not year or int(year) < YEAR_LIMIT:
            continue
            
        key = f"{year}-{month}"
        
        if key not in history_map:
            # Initialize the monthly object with the base server info
            history_map[key] = base_info.copy()
            history_map[key].update({
                "ano": int(year),
                "mes": int(month),
                "mes_ano": f"{int(month):02d}/{year}",
                "financeiro": {"creditos": [], "descontos": []}
            })
            
        history_map[key]["financeiro"]["creditos"].append({
            "descricao": item.get('DescricaoEvento'),
            "valor": item.get('ValorEvento')
        })

    # 2. Process Debits (Descontos)
    for item in debits_raw:
        year = item.get('AnoReferencia')
        month = item.get('MesReferencia')
        
        if not year or int(year) < YEAR_LIMIT:
            continue
            
        key = f"{year}-{month}"
        
        # Create entry if it implies a month where there were only debits (rare but possible)
        if key not in history_map:
            history_map[key] = base_info.copy()
            history_map[key].update({
                "ano": int(year),
                "mes": int(month),
                "mes_ano": f"{int(month):02d}/{year}",
                "financeiro": {"creditos": [], "descontos": []}
            })
            
        history_map[key]["financeiro"]["descontos"].append({
            "descricao": item.get('DescricaoEvento'),
            "valor": item.get('ValorEvento')
        })
        
    return list(history_map.values())

def fetch_server_details_and_distribute(session, url_relative, base_server_info):
    """
    Summary: GETs the details page, parses the hidden JSON, 
    splits the history by month, and saves to respective files.
    """
    url_full = f"{URL_DETAILS_BASE}{url_relative}"
    
    try:
        response = session.get(url_full, headers=HEADERS, verify=False)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract hidden inputs
        input_cred = soup.find('input', id='conteudo-tableCreditos')
        input_desc = soup.find('input', id='conteudo-tableDescontos')
        
        # Parse JSON inside value attribute
        credits_list = json.loads(input_cred['value']) if input_cred and input_cred.get('value') else []
        debits_list = json.loads(input_desc['value']) if input_desc and input_desc.get('value') else []
        
        # Process and Split by Month
        monthly_records = parse_financial_history(credits_list, debits_list, base_server_info)
        
        if not monthly_records:
            # If no history found (or filtered out), we might verify if there is fallback data on screen
            # For now, we assume the hidden inputs are the source of truth.
            return False

        # Save each month to its specific file
        for record in monthly_records:
            append_record_to_monthly_file(record, record['ano'], record['mes'])
            
        return True
        
    except Exception as e:
        print(f"    ❌ Error processing details: {e}")
        return False

def main():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        print(f"Folder '{OUTPUT_FOLDER}' ready.")
        
    print("🚀 Starting TCE-ES Scraper (Grouped by Month)...")
    session = requests.Session()

    # Loop through Situations (Active first, then Inactive)
    for sit_name, sit_id in SITUATIONS:
        print(f"\n=== Processing Situation: {sit_name} (ID: {sit_id}) ===")
        
        # 1. Fetch List
        payload = {
            "NomeFiltro": "",
            "MatriculaFiltro": "",
            "IdSetorFiltro": "",
            "IdCargoOuFuncaoFiltro": "",
            "IdcSituacaoEnum": sit_id
        }
        
        try:
            response = session.post(URL_LIST, data=payload, headers=HEADERS, verify=False)
            response.raise_for_status()
        except Exception as e:
            print(f"❌ Fatal error fetching list for {sit_name}: {e}")
            continue

        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.select("tbody tr")
        if not rows: rows = soup.find_all('tr')
        
        print(f"📋 Found {len(rows)} servers in {sit_name} list.")
        
        # 2. Iterate Servers
        for i, row in enumerate(rows):
            cols = row.find_all('td')
            if len(cols) < 3: continue

            try:
                # Parse Basic Info
                col_name = cols[0]
                link_elem = col_name.find('a')
                
                if not link_elem: continue
                
                name = clean_text(link_elem.get_text())
                url_details = link_elem['href']
                # Extract Matricula from URL
                matricula = url_details.split('matricula=')[1].split('&')[0]
                
                lotacao = clean_text(cols[1].get_text())
                cargo = clean_text(cols[2].get_text())
                # Situation column usually is the last or explicit. We use the loop variable.
                
                base_info = {
                    "matricula": matricula,
                    "nome": name,
                    "cargo": cargo,
                    "lotacao": lotacao,
                    "situacao": sit_name # "Ativo" or "Inativo"
                }

                print(f"  [{i+1}/{len(rows)}] {name}...", end="\r")
                
                # 3. Fetch Details and Distribute to Monthly Files
                fetch_server_details_and_distribute(session, url_details, base_info)
                
                time.sleep(0.1) # Polite delay

            except Exception as e:
                # print(f"Error on row {i}: {e}")
                continue
        
        print(f"\n✅ Completed {sit_name}.")

    print("\n🏁 All tasks finished.")

if __name__ == "__main__":
    main()