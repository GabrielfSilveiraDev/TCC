import json
import os
import time
import re
import subprocess # Changes: Added to execute rclone commands
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# --- CONFIGURATIONS ---
URL_BASE = "https://portal.tce.rs.gov.br/aplicprod/f?p=10200:1:::NO:::"
OUTPUT_FOLDER = "Dados_RS"
ANO_LIMITE = 2020 

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    print(f"📁 Folder '{OUTPUT_FOLDER}' verified/created.")

def setup_server_driver():
    """
    Summary: Configures Chrome WebDriver with eager loading to prevent renderer timeouts.
    Changes: Renamed to setup_server_driver.
    """
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox") 
    options.add_argument("--disable-dev-shm-usage") 
    options.add_argument("--window-size=1920,1080") 
    options.add_argument("--disable-gpu") 
    options.add_argument("--disable-software-rasterizer") 
    options.add_argument("--disable-extensions")
    
    options.page_load_strategy = 'eager' 
    
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60) 
    return driver

def esperar_loading_apex(driver):
    """
    Summary: Waits for the Apex loading spinner to disappear.
    """
    try:
        WebDriverWait(driver, 2).until(EC.visibility_of_element_located((By.CLASS_NAME, "u-Processing")))
        WebDriverWait(driver, 30).until(EC.invisibility_of_element_located((By.CLASS_NAME, "u-Processing")))
    except: pass
    time.sleep(0.3)

def extrair_ano_seguro(texto):
    """
    Summary: Uses Regex to find a 4-digit year.
    """
    match = re.search(r'/.*?(\d{4})', texto)
    return int(match.group(1)) if match else None

def flush_buffer_to_drive(buffer_dados):
    """
    Summary: Saves accumulated records to a unique batch file and moves it to Google Drive to save disk space.
    Changes: Switched from appending existing files to creating unique chunk files. Added subprocess for rclone.
    """
    if not buffer_dados: return
    
    # Flatten the dictionary into a single list for the batch
    lote_dados = []
    for registros in buffer_dados.values():
        lote_dados.extend(registros)
        
    # Create a unique filename based on timestamp to avoid merging issues
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"servidores_tce_rs_lote_{timestamp}.json"
    caminho_arquivo = os.path.join(OUTPUT_FOLDER, nome_arquivo)
    
    try:
        # 1. Save locally
        with open(caminho_arquivo, 'w', encoding='utf-8') as f:
            json.dump(lote_dados, f, ensure_ascii=False, indent=4)
        
        print(f"  💾 Batch saved to disk: {nome_arquivo} ({len(lote_dados)} records)")
        
        # 2. Move to Drive
        print(f"  ☁️ Uploading batch to Google Drive...")
        subprocess.run(["rclone", "move", caminho_arquivo, "meudrive:TCC_Scraping/Dados_RS/"], check=True)
        print(f"  ✅ Upload complete and local file deleted.")
        
    except subprocess.CalledProcessError as e:
        print(f"    ❌ Error uploading batch to Drive: {e}")
    except Exception as e:
        print(f"    ❌ Error saving batch: {e}")
        
    buffer_dados.clear()

def extrair_dados_da_tela(driver, mes_ano_texto, nome_servidor):
    """
    Summary: Extracts financial data from specific span IDs.
    """
    dados = {"mes_ano": mes_ano_texto.strip(), "nome_servidor": nome_servidor}
    try:
        mapa_ids = {
            "P7_NOME": "nome", "P7_CARGO": "cargo", "P7_CLASSE": "classe", "P7_NIVEL": "nivel",
            "P7_FG": "funcao_gratificada", "P7_DT_INGRESSO_TCE": "data_ingresso",
            "P7_TEMPO_SERVICO_PUBLICO": "tempo_servico", "P7_VL_BRUTO_APOS_TETO": "remuneracao_bruta",
            "P7_VL_INDENIZATORIAS": "parcelas_indenizatorias", "P7_VL_ABONO_PERMANENCIA": "abono_permanencia",
            "P7_VL_TERCO_FERIAS": "terco_ferias", "P7_VL_GRATIFICACAO_NATALINA": "gratificacao_natalina",
            "P7_VL_DESCONTOS_LEGAIS": "descontos_legais", "P7_VL_LIQUIDO_APOS_DESCONTOS": "liquido"
        }
        for elemento in driver.find_elements(By.CSS_SELECTOR, "span.display_only"):
            elem_id = elemento.get_attribute("id")
            if elem_id in mapa_ids: dados[mapa_ids[elem_id]] = elemento.text.strip()
    except: pass
    return dados

def processar_servidor(driver, url_servidor, nome_servidor):
    """
    Summary: Processes a single server, catching page load timeouts to prevent script death.
    """
    print(f"  👤 [{nome_servidor}] Reading history...")
    registros_servidor = []
    
    try:
        try:
            driver.get(url_servidor)
        except TimeoutException:
            driver.execute_script("window.stop();")
            
        esperar_loading_apex(driver)
        
        select = Select(WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "P7_PERIODO"))))
        
        todas_opcoes_texto = [opt.text for opt in select.options]
        datas_validas = []
        target_year = os.environ.get("TARGET_YEAR")
        
        for texto in todas_opcoes_texto:
            ano = extrair_ano_seguro(texto)
            if ano:
                if target_year:
                    if ano == int(target_year):
                        datas_validas.append(texto)
                elif ano >= ANO_LIMITE:
                    datas_validas.append(texto)

        print(f"  👤 [{nome_servidor}] Extracting {len(datas_validas)} months...")

        for data_str in datas_validas:
            try:
                select = Select(driver.find_element(By.ID, "P7_PERIODO"))
                select.select_by_visible_text(data_str)
                esperar_loading_apex(driver)
                registros_servidor.append(extrair_dados_da_tela(driver, data_str, nome_servidor))
            except: continue
    except Exception as e:
        print(f"  ❌ Error on profile: {type(e).__name__}")
        
    return registros_servidor

def main():
    """
    Summary: Main execution loop for scraping TCE-RS on a local server.
    """
    print(f"⏱️ Starting at {datetime.now().strftime('%H:%M:%S')}")
    driver = setup_server_driver()
    urls_processadas, buffer_por_mes = set(), {}
    servidores_processados_lote, BATCH_SIZE = 0, 20
    
    try:
        print("🌐 Accessing server list...")
        try:
            driver.get(URL_BASE)
        except TimeoutException:
            print("  ⚠️ Initial timeout. Forcing stop of heavy scripts/images...")
            driver.execute_script("window.stop();")

        esperar_loading_apex(driver)
        
        pagina = 1
        while True:
            links_servidores = []
            try:
                for row in driver.find_elements(By.CSS_SELECTOR, "table.a-IRR-table tbody tr"):
                    cols = row.find_elements(By.TAG_NAME, "td")
                    if cols:
                        link = cols[0].find_element(By.TAG_NAME, "a")
                        links_servidores.append((link.text.strip(), link.get_attribute("href")))
            except: pass

            print(f"\n📄 Page {pagina}: {len(links_servidores)} servers found.")

            for nome, url in links_servidores:
                if url in urls_processadas: continue
                driver.execute_script("window.open('');")
                driver.switch_to.window(driver.window_handles[1])
                
                for reg in processar_servidor(driver, url, nome):
                    mes_ano = reg.get("mes_ano")
                    if mes_ano:
                        if mes_ano not in buffer_por_mes: buffer_por_mes[mes_ano] = []
                        buffer_por_mes[mes_ano].append(reg)
                
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                urls_processadas.add(url)
                servidores_processados_lote += 1
                
                if servidores_processados_lote >= BATCH_SIZE:
                    flush_buffer_to_drive(buffer_por_mes)
                    servidores_processados_lote = 0

            try:
                btn_next = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.a-IRR-button--pagination[title='Próximo']")))
                if not btn_next.is_displayed(): break
                driver.execute_script("arguments[0].click();", btn_next)
                esperar_loading_apex(driver)
                pagina += 1
            except: break
                
        flush_buffer_to_drive(buffer_por_mes)
    except Exception as e:
        print(f"❌ Fatal Error: {e}")
        flush_buffer_to_drive(buffer_por_mes)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
