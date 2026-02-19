import time
import json
import requests
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATIONS ---
OUTPUT_FOLDER = "Dados_RJ"

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    print(f"📁 Folder '{OUTPUT_FOLDER}' verified/created.")

def setup_github_driver():
    """
    Summary: Configures the headless Chrome WebDriver for GitHub Actions environment.
    """
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox") 
    options.add_argument("--disable-dev-shm-usage") 
    options.add_argument("--window-size=1920,1080") 
    options.add_argument("--disable-gpu") 
    
    return webdriver.Chrome(options=options)

def wait_angular_loading(driver):
    """
    Summary: Waits for the Angular loading spinner to appear and disappear.
    """
    try:
        WebDriverWait(driver, 2).until(EC.visibility_of_element_located((By.CLASS_NAME, "loading-container")))
        WebDriverWait(driver, 30).until(EC.invisibility_of_element_located((By.CLASS_NAME, "loading-container")))
    except: 
        pass
    time.sleep(0.5)

def get_api_references():
    """
    Summary: Fetches the list of available competency periods via API.
    """
    print("📡 Fetching reference periods via API...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://tcerjtransparencia.admrh.inf.br/rhsysportaltransp/",
        "Cookie": "SESSIONCOOKIESISTEMA2=aVgwkXC61smoXTkV_FdVwHQ0.admrhapp" 
    }
    url_referencia = "https://tcerjtransparencia.admrh.inf.br/rhsysportaltransp/api/lov/referencia?busca=&page=1"

    try:
        response = requests.get(url_referencia, headers=headers, verify=True)
        response.raise_for_status()
        dados_api = response.json()
        return [item['descricao'] for item in dados_api['dados']]
    except Exception as e:
        print(f"❌ Error fetching API: {e}")
        return []

def parse_valor_br(v):
    """
    Summary: Converts BR currency string to float.
    """
    if not v: return 0.0
    return float(v.replace(".", "").replace(",", ".").strip())

def main():
    """
    Summary: Main scraper function for TCE-RJ using Selenium on GitHub Actions.
    Changes: Filters references by TARGET_YEAR from environment variables.
    """
    lista_referencias = get_api_references()
    
    # Filter by target year passed by GitHub Actions
    target_year = os.environ.get("TARGET_YEAR")
    if target_year:
        lista_referencias = [ref for ref in lista_referencias if ref.endswith(f"/{target_year}")]
        
    print(f"📅 Found {len(lista_referencias)} references to process for year {target_year or 'ALL'}.")
    
    if not lista_referencias:
        return

    driver = setup_github_driver()
    wait = WebDriverWait(driver, 20)

    print("🌍 Accessing portal...")
    driver.get("https://tcerjtransparencia.admrh.inf.br/rhsysportaltransp/")

    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "ui-select-container")))

    for referencia in lista_referencias:
        print(f"\n🔵 Starting competency: {referencia}")
        
        dados_do_mes = []

        try:
            dropdown_container = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".ui-select-container .ui-select-toggle")))
            driver.execute_script("arguments[0].click();", dropdown_container)

            input_busca = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input.ui-select-search")))
            input_busca.clear()
            input_busca.send_keys(referencia)
            time.sleep(0.5) 
            input_busca.send_keys(Keys.ENTER)

            wait_angular_loading(driver)
            time.sleep(1) 
            
            rows = driver.find_elements(By.CSS_SELECTOR, "table.table-selectable tbody tr")
            if not rows or "nenhum registro" in driver.page_source.lower():
                print(f"⚠️ No data found for {referencia}. Skipping...")
                continue

        except Exception as e:
            print(f"❌ Error selecting date {referencia}: {e}")
            continue

        pagina = 1
        ultimo_primeiro_nome = None 
        
        while True:
            print(f"  ↪️ Reading page {pagina} of {referencia}...")
            
            try:
                primeiro_nome_atual = driver.find_element(By.CSS_SELECTOR, "table.table-selectable tbody tr td[data-title='Nome']").text.strip()
                if ultimo_primeiro_nome and primeiro_nome_atual == ultimo_primeiro_nome:
                    print(f"  ✅ [LOCK] Page hasn't changed (End of list detected).")
                    break
                ultimo_primeiro_nome = primeiro_nome_atual
            except:
                break

            rows = driver.find_elements(By.CSS_SELECTOR, "table.table-selectable tbody tr")
            
            for i in range(len(rows)):
                rows = driver.find_elements(By.CSS_SELECTOR, "table.table-selectable tbody tr")
                if i >= len(rows): break
                row = rows[i]

                try:
                    nome = row.find_element(By.CSS_SELECTOR, "td[data-title='Nome']").text.strip()
                    cargo = row.find_element(By.CSS_SELECTOR, "td[data-title='Cargo']").text.strip()
                    tipo = row.find_element(By.CSS_SELECTOR, "td[data-title='Vinculo']").text.strip()

                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
                    try: 
                        row.click()
                    except: 
                        driver.execute_script("arguments[0].click();", row)
                    
                    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".valores")))

                    total_blocks = driver.find_elements(By.CSS_SELECTOR, ".valores")
                    proventos = []
                    total_proventos = 0.0
                    total_descontos = 0.0
                    salario_liquido = 0.0

                    for bloco in total_blocks:
                        try:
                            descricao = bloco.find_element(By.CSS_SELECTOR, ".column-string").text.strip()
                            valor_str = bloco.find_element(By.CSS_SELECTOR, ".column-number").text.strip()
                            valor = parse_valor_br(valor_str)

                            desc_lower = descricao.lower()
                            if "deduções" in desc_lower or "liquido" in desc_lower or "líquido" in desc_lower:
                                salario_liquido = valor
                            elif "desconto" in desc_lower or "retido" in desc_lower:
                                total_descontos += valor
                                if valor > 0:
                                    proventos.append({"descricao": descricao, "valor": valor_str, "tipo": "D"})
                            else:
                                total_proventos += valor
                                if valor > 0:
                                    proventos.append({"descricao": descricao, "valor": valor_str, "tipo": "P"})
                        except: 
                            continue

                    dados_do_mes.append({
                        "referencia": referencia,
                        "nome": nome,
                        "cargo": cargo,
                        "tipo": tipo,
                        "salario_liquido": f"{salario_liquido:,.2f}",
                        "total_proventos": f"{total_proventos:,.2f}",
                        "total_descontos": f"{total_descontos:,.2f}",
                        "detalhes": proventos
                    })

                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".valores")))

                except Exception as e:
                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    continue

            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                btn_proximo = driver.find_element(By.CSS_SELECTOR, "a[title='Próxima']")
                parent_li = btn_proximo.find_element(By.XPATH, "./..")
                
                if "disabled" in parent_li.get_attribute("class"):
                    print(f"  ✅ End of pages (Button disabled).")
                    break

                driver.execute_script("arguments[0].click();", btn_proximo)
                wait_angular_loading(driver)
                pagina += 1
                
            except Exception as e:
                print(f"  ✅ End of pages (Next button not found).")
                break
        
        if dados_do_mes:
            nome_seguro = referencia.replace('/', '_')
            nome_arquivo = f"servidores_tce_rj_completo_{nome_seguro}.json"
            caminho_completo = os.path.join(OUTPUT_FOLDER, nome_arquivo)
            
            try:
                with open(caminho_completo, "w", encoding="utf-8") as f:
                    json.dump(dados_do_mes, f, ensure_ascii=False, indent=4)
                print(f"💾 Saved file: {nome_arquivo} ({len(dados_do_mes)} records)")
            except Exception as e:
                print(f"❌ Error saving {nome_arquivo}: {e}")

    driver.quit()
    print("🏁 Scraper finished.")

if __name__ == "__main__":
    main()
