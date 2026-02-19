import json
import os
import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURAÇÕES ---
URL_BASE = "https://portal.tce.rs.gov.br/aplicprod/f?p=10200:1:::NO:::"
OUTPUT_FOLDER = "Dados_RS"
ANO_LIMITE = 2020 

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    print(f"📁 Pasta '{OUTPUT_FOLDER}' verificada/criada.")

# --- FUNÇÕES AUXILIARES ---

def setup_github_driver():
    """
    Summary: Configures the headless Chrome WebDriver for GitHub Actions environment.
    Changes: Removed Colab specific settings. Relies on standard Selenium Manager.
    """
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox") 
    options.add_argument("--disable-dev-shm-usage") 
    options.add_argument("--window-size=1920,1080") 
    options.add_argument("--disable-gpu") 
    
    return webdriver.Chrome(options=options)

def esperar_loading_apex(driver):
    """
    Summary: Waits for the Apex loading spinner (u-Processing) to disappear.
    """
    try:
        WebDriverWait(driver, 2).until(EC.visibility_of_element_located((By.CLASS_NAME, "u-Processing")))
        WebDriverWait(driver, 30).until(EC.invisibility_of_element_located((By.CLASS_NAME, "u-Processing")))
    except:
        pass
    time.sleep(0.3)

def extrair_ano_seguro(texto):
    """
    Summary: Uses Regex to find a 4-digit year after a slash.
    """
    match = re.search(r'/.*?(\d{4})', texto)
    if match:
        return int(match.group(1))
    return None

def flush_buffer_to_disk(buffer_dados):
    """
    Summary: Optimizes I/O by writing accumulated records to local disk in batches.
    Changes: Renamed from drive to disk to reflect standard local storage.
    """
    if not buffer_dados: return
    
    for mes_ano, registros in buffer_dados.items():
        safe_date = mes_ano.replace('/', '_').strip()
        nome_arquivo = f"servidores_tce_rs_{safe_date}.json"
        caminho_arquivo = os.path.join(OUTPUT_FOLDER, nome_arquivo)
        
        dados_existentes = []
        if os.path.exists(caminho_arquivo):
            try:
                with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                    dados_existentes = json.load(f)
            except Exception as e:
                print(f"    ⚠️ Erro ao ler arquivo existente {nome_arquivo}: {e}")
        
        dados_existentes.extend(registros)
        
        try:
            with open(caminho_arquivo, 'w', encoding='utf-8') as f:
                json.dump(dados_existentes, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"    ❌ Erro ao salvar {nome_arquivo}: {e}")
            
    buffer_dados.clear()
    print(f"  💾 Lote salvo no disco com sucesso!")

def extrair_dados_da_tela(driver, mes_ano_texto, nome_servidor):
    """
    Summary: Extracts financial data from specific span IDs.
    """
    dados = {
        "mes_ano": mes_ano_texto.strip(),
        "nome_servidor": nome_servidor 
    }
    
    try:
        mapa_ids = {
            "P7_NOME": "nome",
            "P7_CARGO": "cargo",
            "P7_CLASSE": "classe",
            "P7_NIVEL": "nivel",
            "P7_FG": "funcao_gratificada",
            "P7_DT_INGRESSO_TCE": "data_ingresso",
            "P7_TEMPO_SERVICO_PUBLICO": "tempo_servico",
            "P7_VL_BRUTO_APOS_TETO": "remuneracao_bruta",
            "P7_VL_INDENIZATORIAS": "parcelas_indenizatorias",
            "P7_VL_ABONO_PERMANENCIA": "abono_permanencia",
            "P7_VL_TERCO_FERIAS": "terco_ferias",
            "P7_VL_GRATIFICACAO_NATALINA": "gratificacao_natalina",
            "P7_VL_DESCONTOS_LEGAIS": "descontos_legais",
            "P7_VL_LIQUIDO_APOS_DESCONTOS": "liquido"
        }
        
        spans = driver.find_elements(By.CSS_SELECTOR, "span.display_only")
        for elemento in spans:
            elem_id = elemento.get_attribute("id")
            if elem_id in mapa_ids:
                dados[mapa_ids[elem_id]] = elemento.text.strip()
                
    except Exception as e:
        print(f"    ⚠️ Erro leitura tela: {e}")
        
    return dados

def processar_servidor(driver, url_servidor, nome_servidor):
    """
    Summary: Processes a single server's historical data and returns a list of records.
    """
    print(f"  👤 [{nome_servidor}] Lendo histórico...", end='\r')
    registros_servidor = []
    
    try:
        driver.get(url_servidor)
        esperar_loading_apex(driver)
        
        select_elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "P7_PERIODO"))
        )
        select = Select(select_elem)
        
        todas_opcoes_texto = [opt.text for opt in select.options]
        datas_validas = []
        
        for texto in todas_opcoes_texto:
            ano = extrair_ano_seguro(texto)
            if ano and ano >= ANO_LIMITE:
                datas_validas.append(texto)
        
        print(f"  👤 [{nome_servidor}] Extraindo {len(datas_validas)} meses...    ")

        for data_str in datas_validas:
            try:
                select_elem = driver.find_element(By.ID, "P7_PERIODO")
                select = Select(select_elem)
                
                select.select_by_visible_text(data_str)
                esperar_loading_apex(driver)
                
                registro = extrair_dados_da_tela(driver, data_str, nome_servidor)
                registros_servidor.append(registro)
                
            except Exception as e:
                print(f"    ❌ Falha ao processar mês {data_str}: {type(e).__name__}")
                continue

    except Exception as e:
        print(f"  ❌ Erro ao acessar perfil {nome_servidor}: {type(e).__name__}")
        
    return registros_servidor

def main():
    """
    Summary: Main execution loop for scraping TCE-RS on GitHub Actions.
    """
    start_time = datetime.now()
    print(f"⏱️ Iniciando em {start_time.strftime('%H:%M:%S')}")
    
    driver = setup_github_driver()
    urls_processadas = set()
    buffer_por_mes = {} 
    servidores_processados_lote = 0
    BATCH_SIZE = 20 
    
    try:
        driver.get(URL_BASE)
        print("🌐 Acessando lista de servidores...")
        esperar_loading_apex(driver)
        
        pagina = 1
        while True:
            links_servidores = []
            try:
                rows = driver.find_elements(By.CSS_SELECTOR, "table.a-IRR-table tbody tr")
                for row in rows:
                    cols = row.find_elements(By.TAG_NAME, "td")
                    if cols:
                        try:
                            link = cols[0].find_element(By.TAG_NAME, "a")
                            url = link.get_attribute("href")
                            nome = link.text.strip()
                            links_servidores.append((nome, url))
                        except: pass
            except: pass

            print(f"\n📄 Página {pagina}: {len(links_servidores)} servidores encontrados na tabela.")

            for nome, url in links_servidores:
                if url in urls_processadas: continue
                
                driver.execute_script("window.open('');")
                driver.switch_to.window(driver.window_handles[1])
                
                registros_extraidos = processar_servidor(driver, url, nome)
                
                for reg in registros_extraidos:
                    mes_ano = reg.get("mes_ano")
                    if mes_ano:
                        if mes_ano not in buffer_por_mes:
                            buffer_por_mes[mes_ano] = []
                        buffer_por_mes[mes_ano].append(reg)
                
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                urls_processadas.add(url)
                servidores_processados_lote += 1
                
                if servidores_processados_lote >= BATCH_SIZE:
                    print(f"  🔄 Limite de {BATCH_SIZE} servidores atingido. Descarregando buffer...")
                    flush_buffer_to_disk(buffer_por_mes)
                    servidores_processados_lote = 0

            try:
                btn_next = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button.a-IRR-button--pagination[title='Próximo']"))
                )
                if not btn_next.is_displayed():
                    print("🏁 Fim da lista (Botão Próximo invisível).")
                    break
                
                driver.execute_script("arguments[0].click();", btn_next)
                esperar_loading_apex(driver)
                pagina += 1
            except Exception as e:
                print("🏁 Fim (Botão Próximo não encontrado ou inativo).")
                break
                
        if buffer_por_mes:
            print(f"  🔄 Processamento concluído. Descarregando registros finais...")
            flush_buffer_to_disk(buffer_por_mes)

    except Exception as e:
        print(f"❌ Erro Fatal: {e}")
        if buffer_por_mes:
            print(f"  🔄 Salvando buffer de emergência...")
            flush_buffer_to_disk(buffer_por_mes)
    finally:
        driver.quit()
        end = datetime.now()
        print(f"\n🏁 Tempo Total: {end - start_time}")

if __name__ == "__main__":
    main()