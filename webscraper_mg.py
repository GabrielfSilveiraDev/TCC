import os
import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

# --- Configuration ---
URL = "https://capmg.tce.mg.gov.br/view/xhtml/pesquisaRemuneracao.xhtml"
OUTPUT_FOLDER = os.path.abspath("Dados_MG")
ANO_LIMITE = 2020

# Dicionário para mapear os meses do texto para numerais
MESES_MAP = {
    "JANEIRO": "01", "FEVEREIRO": "02", "MARÇO": "03", "ABRIL": "04",
    "MAIO": "05", "JUNHO": "06", "JULHO": "07", "AGOSTO": "08",
    "SETEMBRO": "09", "OUTUBRO": "10", "NOVEMBRO": "11", "DEZEMBRO": "12"
}

# Create output directory if it does not exist
if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

def setup_driver():
    """
    Summary: Configures the Chrome driver with automatic download settings.
    """
    options = Options()
    # options.add_argument("--headless=new") # Uncomment for background execution
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    prefs = {
        "download.default_directory": OUTPUT_FOLDER,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_setting_values.automatic_downloads": 1 
    }
    options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(options=options)

def wait_primefaces_ajax(driver, timeout=20):
    """
    Summary: Waits for PrimeFaces (jQuery) active AJAX requests to finish to prevent DOM issues.
    """
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return typeof jQuery !== 'undefined' && jQuery.active === 0")
        )
        time.sleep(0.5) 
    except:
        pass

def select_primefaces_dropdown(driver, wait, field_name, xpath_hidden_select, target_text):
    """
    Summary: Selects an option from a PrimeFaces dropdown using its hidden select ID.
    """
    print(f"   🔄 Selecionando {field_name}: {target_text}...", end=" ")
    try:
        hidden_select = wait.until(EC.presence_of_element_located((By.XPATH, xpath_hidden_select)))
        dropdown_container = hidden_select.find_element(By.XPATH, "../..")
        
        trigger = dropdown_container.find_element(By.CSS_SELECTOR, ".ui-selectonemenu-trigger")
        driver.execute_script("arguments[0].click();", trigger)
        time.sleep(1) 
        
        try:
            xpath_option = f"//div[contains(@class, 'ui-selectonemenu-panel') and contains(@style, 'display: block')]//li[text()='{target_text}']"
            option = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_option)))
        except:
            xpath_option = f"//div[contains(@class, 'ui-selectonemenu-panel') and contains(@style, 'display: block')]//li[contains(text(), '{target_text}')]"
            option = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_option)))

        driver.execute_script("arguments[0].click();", option)
        
        print("OK.")
        wait_primefaces_ajax(driver)
        return True
    except Exception as e:
        print(f"Falha ({type(e).__name__}).")
        webdriver.ActionChains(driver).send_keys(webdriver.Keys.ESCAPE).perform()
        return False

def main():
    """
    Summary: Main execution flow for scraping TCE-MG.
    """
    print(f"⏱️ Iniciando Scraper TCE-MG em {datetime.now().strftime('%H:%M:%S')}")
    driver = setup_driver()
    wait = WebDriverWait(driver, 15)
    long_wait = WebDriverWait(driver, 300) 

    try:
        print("🌍 Acessando portal...")
        driver.get(URL)
        wait_primefaces_ajax(driver)

        # 1. CITIZEN LOGIN AND CAPTCHA
        print("👤 Entrando como Cidadão...")
        try:
            xpath_cidadao = "//button[.//span[text()='CLIQUE AQUI SE VOCÊ É CIDADÃO']]"
            btn_cidadao = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_cidadao)))
            driver.execute_script("arguments[0].click();", btn_cidadao)
            
            print("\n" + "="*60)
            print("🛑 ATENÇÃO: Verificando reCAPTCHA...")
            print("Se o CAPTCHA aparecer na tela, resolva manualmente e clique em ENTRAR.")
            print("⏳ O script aguardará até 5 minutos por você...")
            print("="*60 + "\n")

            xpath_select_ano = "//select[option[contains(text(), '2025')]]"
            long_wait.until(EC.presence_of_element_located((By.XPATH, xpath_select_ano)))
            print("✅ Acesso ao sistema confirmado! Retomando automação...\n")
            time.sleep(1) 
            
        except Exception as e:
            print(f"❌ Falha ao acessar ou tempo limite do CAPTCHA excedido.")
            return

        # 2. PHASE 1: QUEUE EXPORTS
        print("\n🚀 FASE 1: Enfileirando Exportações...")
        
        for ano in range(2025, ANO_LIMITE - 1, -1):
            if ano == 2025:
                meses = ["Setembro", "Agosto", "Julho", "Junho", "Maio", "Abril", "Março", "Fevereiro", "Janeiro"]
            else:
                meses = ["Dezembro", "Novembro", "Outubro", "Setembro", "Agosto", "Julho", "Junho", "Maio", "Abril", "Março", "Fevereiro", "Janeiro"]

            for mes in meses:
                print(f"\n🗓️ Preparando: {mes}/{ano}")
                
                select_primefaces_dropdown(driver, wait, "Ano", "//select[option[contains(text(), '2025')]]", str(ano))
                select_primefaces_dropdown(driver, wait, "Mês", "//select[option[contains(text(), 'Janeiro')]]", mes)
                select_primefaces_dropdown(driver, wait, "Esfera", "//select[contains(@id, 'idEsfera_input')]", "Estadual")
                time.sleep(1.5) 
                select_primefaces_dropdown(driver, wait, "Órgão", "//select[contains(@id, 'comboOrgao_input')]", "Tribunal de Contas do Estado de Minas Gerais")
                time.sleep(1)
                
                # CLICK 1: SEARCH
                try:
                    print("   🔎 Clicando em Pesquisar...", end=" ")
                    btn_pesquisar = driver.find_element(By.XPATH, "//button[.//span[text()='Pesquisar']]")
                    driver.execute_script("arguments[0].click();", btn_pesquisar)
                    wait_primefaces_ajax(driver)
                    time.sleep(1) 
                    print("OK.")
                except Exception as e:
                    print("Falha ao pesquisar.")
                    continue 

                # CLICK 2: EXPORT JSON 
                try:
                    export_success = False
                    for _ in range(3):
                        try:
                            wait_export = WebDriverWait(driver, 10)
                            btn_export = wait_export.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".btnExportar a.linksArquivosJson")))
                            driver.execute_script("arguments[0].click();", btn_export)
                            export_success = True
                            break 
                        except Exception as inner_e:
                            time.sleep(1)
                    
                    if export_success:
                        print("   📦 Exportação JSON solicitada!")
                        wait_primefaces_ajax(driver)
                        time.sleep(1)
                    else:
                        print("   ⚠️ Falha ao clicar no botão de exportar (DOM instável).")
                        
                except TimeoutException:
                    print("   ⚠️ Botão de exportar JSON não apareceu após 10s (Tabela vazia?).")
                except Exception as e:
                    print(f"   ⚠️ Erro inesperado ao exportar: {type(e).__name__}")

        print("\n⏳ Aguardando 10 segundos para o servidor processar as filas finais...")
        time.sleep(10)

        # 3. PHASE 2: MANAGE DOWNLOADS & RENAME FILES
        print("\n🚀 FASE 2: Baixando e Renomeando Arquivos Processados...")

        try:
            # Open downloads modal
            btn_gerenciar = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='Gerenciar downloads']]")))
            driver.execute_script("arguments[0].click();", btn_gerenciar)
            wait_primefaces_ajax(driver)
            
            # Wait specifically for the modal container to be visible
            modal_base_css = "div[id$='dialogArquivosExportados']"
            wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, modal_base_css)))
            time.sleep(1) 
        except Exception as e:
            print(f"❌ Não foi possível abrir o modal de downloads.")
            return

        pagina = 1
        while True:
            print(f"   📄 Lendo página {pagina} de downloads no modal...")
            
            try:
                # Summary: Strict CSS selectors forcing Selenium to look ONLY inside the modal
                rows_css = f"{modal_base_css} tbody[id$='dataTableResultados_data'] tr"
                rows = driver.find_elements(By.CSS_SELECTOR, rows_css)
                
                if not rows or "Nenhum registro" in rows[0].text:
                    print("   ⚠️ Nenhuma linha encontrada na tabela do modal.")
                    break

                primeira_linha_ref = rows[0]
                
                for i in range(len(rows)):
                    current_rows = driver.find_elements(By.CSS_SELECTOR, rows_css)
                    if i >= len(current_rows): break
                    row = current_rows[i]
                    
                    row_text = row.text.upper()
                    
                    if "FINALIZADO" in row_text and "JSON" in row_text:
                        
                        # --- INÍCIO DA LÓGICA DE NOMEAÇÃO DINÂMICA ---
                        try:
                            ano_ext = re.search(r'EXERCÍCIO:\s*(\d{4})', row_text).group(1)
                            mes_ext = re.search(r'MÊS:\s*([A-ZÇ]+)', row_text).group(1)
                            mes_num = MESES_MAP.get(mes_ext, "00")
                            nome_padrao = f"servidores_tce_mg_completo_{mes_num}_{ano_ext}.json"
                            caminho_padrao = os.path.join(OUTPUT_FOLDER, nome_padrao)
                            
                            if os.path.exists(caminho_padrao):
                                os.remove(caminho_padrao)
                        except Exception as e:
                            nome_padrao = f"servidores_tce_mg_completo_DESCONHECIDO_{int(time.time())}.json"
                            caminho_padrao = os.path.join(OUTPUT_FOLDER, nome_padrao)
                        
                        arquivos_antes = set(os.listdir(OUTPUT_FOLDER))
                        
                        btn_baixar = row.find_element(By.CSS_SELECTOR, "button.btnTabela")
                        driver.execute_script("arguments[0].click();", btn_baixar)
                        
                        timeout_dl = 30
                        start_dl = time.time()
                        renomeado = False
                        
                        while time.time() - start_dl < timeout_dl:
                            arquivos_agora = set(os.listdir(OUTPUT_FOLDER))
                            novos = arquivos_agora - arquivos_antes
                            
                            prontos = [f for f in novos if not f.endswith('.crdownload') and not f.endswith('.tmp')]
                            
                            if prontos:
                                caminho_original = os.path.join(OUTPUT_FOLDER, prontos[0])
                                try:
                                    os.rename(caminho_original, caminho_padrao)
                                    print(f"      💾 Salvo: {nome_padrao}")
                                    renomeado = True
                                except Exception as e:
                                    print(f"      ⚠️ Erro ao renomear {prontos[0]}: {e}")
                                break
                            time.sleep(1)
                        
                        if not renomeado:
                            print(f"      ⚠️ Timeout ao baixar: {nome_padrao}")
                        # --- FIM DA LÓGICA DE NOMEAÇÃO DINÂMICA ---
                
                # --- PAGINATION LOGIC STRICTLY INSIDE MODAL ---
                next_btn_css = f"{modal_base_css} div[id$='dataTableResultados_paginator_bottom'] .ui-paginator-next"
                next_buttons = driver.find_elements(By.CSS_SELECTOR, next_btn_css)
                
                if not next_buttons:
                    print("   ✅ Fim da tabela (sem botão de paginação no modal).")
                    break
                    
                next_button = next_buttons[0]
                
                if "ui-state-disabled" in next_button.get_attribute("class"):
                    print("   ✅ Fim das páginas alcançado.")
                    break 
                
                driver.execute_script("arguments[0].click();", next_button)
                wait_primefaces_ajax(driver)
                
                try:
                    WebDriverWait(driver, 10).until(EC.staleness_of(primeira_linha_ref))
                except TimeoutException:
                    print("   ✅ Fim da tabela detectado (A página não recarregou após o clique).")
                    break

                pagina += 1
                
            except Exception as e:
                print(f"   ✅ Leitura finalizada.")
                break

        print(f"\n📂 Processo de downloads concluído com sucesso na pasta: {OUTPUT_FOLDER}")

    except Exception as e:
        print(f"\n❌ Erro Crítico: {e}")
    finally:
        driver.quit()
        print(f"🏁 Processo finalizado.")

if __name__ == "__main__":
    main()