import os
import time
import json
import subprocess
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

URL_PAGINA = "https://www.tce.pr.gov.br/transparencia-do-tce-pr/pessoal/remuneracao.htm"
PASTA_SAIDA = "Dados_PR"

if not os.path.exists(PASTA_SAIDA):
    os.makedirs(PASTA_SAIDA)

def setup_webdriver():
    """
    Summary: Configures the Chrome WebDriver for headless execution and memory optimization.
    """
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-software-rasterizer")
    options.page_load_strategy = 'eager'
    
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver

def trigger_change(driver, element):
    """
    Summary: Forces the JavaScript 'change' event to fire, crucial for LumisXP reactive forms.
    """
    driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", element)

def get_valid_options(select_element, is_month=False):
    """
    Summary: Extracts valid options returning tuples of (value, text) to ensure robust selection.
    """
    valid_options = []
    for opt in select_element.options:
        val = opt.get_attribute("value")
        text = opt.text.strip()
        if val and str(val).strip() != "" and "Selecione" not in text: 
            if is_month:
                try:
                    year = int(val.split(".")[0])
                    if year >= 2020:
                        valid_options.append((val, text))
                except:
                    pass
            else:
                valid_options.append((val, text))
    return valid_options

def extract_table_data(html_item):
    """
    Summary: Extracts key-value financial data from the rendered HTML table.
    """
    financial_data = {}
    rows = html_item.find_elements(By.CSS_SELECTOR, "tr.tp_table--tbody-tr")
    
    for row in rows:
        columns = row.find_elements(By.TAG_NAME, "td")
        if len(columns) == 2:
            key = columns[0].get_attribute("textContent").strip()
            value = columns[1].get_attribute("textContent").strip()
            
            if "R$" in value:
                try:
                    clean_value = value.replace("R$", "").replace(".", "").replace(",", ".").replace(" ", "").strip()
                    financial_data[key] = float(clean_value)
                except:
                    financial_data[key] = value
            else:
                financial_data[key] = value
                
    return financial_data

def extract_pages(driver, mes_text, nat_text):
    """
    Summary: Iterates through pagination and extracts data after confirming the container has items.
    """
    dados = []
    pagina = 1
    
    while True:
        itens = driver.find_elements(By.CSS_SELECTOR, ".tp-dropdown-shadow--item")
        if not itens:
            break
            
        for item in itens:
            nome_servidor = item.find_element(By.CSS_SELECTOR, ".tp-dropdown-shadow--item-title").get_attribute("textContent").strip()
            detalhes = extract_table_data(item)
            
            registro = {
                "periodo_folha": mes_text,
                "natureza_detalhada": nat_text,
                "nome": nome_servidor,
                "financeiro": detalhes
            }
            dados.append(registro)

        botoes_prox = driver.find_elements(By.CSS_SELECTOR, "button.tp-pagination__btn-next")
        if not botoes_prox or "disabled" in botoes_prox[0].get_attribute("outerHTML"):
            break
            
        driver.execute_script("arguments[0].click();", botoes_prox[0])
        time.sleep(3) # Tempo fixo rapido apenas para a mudanca de pagina renderizar
        pagina += 1
        
    return dados

def main():
    """
    Summary: Main scraper flow with dynamic wait (up to 60 seconds) for slow data rendering.
    """
    print(f"Iniciando Scraper PR (Selenium) em {datetime.now().strftime('%H:%M:%S')}")
    driver = setup_webdriver()
    wait = WebDriverWait(driver, 15)

    try:
        print("Acessando portal e aguardando JavaScript...")
        driver.get(URL_PAGINA)
        time.sleep(5) 
        
        try:
            wait.until(lambda d: len(Select(d.find_element(By.NAME, "remuneracoes-mes-ano")).options) > 2)
        except:
            pass

        select_mes_element = Select(driver.find_element(By.NAME, "remuneracoes-mes-ano"))
        meses_disponiveis = get_valid_options(select_mes_element, is_month=True)
        print(f"Meses carregados: {len(meses_disponiveis)}")
        
        select_nat_element = Select(driver.find_element(By.NAME, "remuneracoes-natureza"))
        naturezas_disponiveis = get_valid_options(select_nat_element)
        print(f"Naturezas carregadas: {len(naturezas_disponiveis)}")

        for mes_val, mes_text in meses_disponiveis:
            print(f"\n=== Processando Mes: {mes_text} ===")
            dados_consolidados_mes = []

            for nat_val, nat_text in naturezas_disponiveis:
                print(f" > Buscando: {nat_text} (Aguardando dados...)", end="\r")
                
                try:
                    # Limpa a tabela anterior da tela para nao confundir o robô
                    driver.execute_script("document.getElementById('remuneracoes-result-container').innerHTML = '';")
                    
                    select_mes = driver.find_element(By.NAME, "remuneracoes-mes-ano")
                    Select(select_mes).select_by_value(mes_val)
                    trigger_change(driver, select_mes)
                    time.sleep(1)
                    
                    select_nat = driver.find_element(By.NAME, "remuneracoes-natureza")
                    Select(select_nat).select_by_value(nat_val)
                    trigger_change(driver, select_nat)

                    # A MAGICA ACONTECE AQUI: Espera ate 60 segundos os dados brotarem na tela
                    try:
                        WebDriverWait(driver, 60).until(
                            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".tp-dropdown-shadow--item")) > 0
                        )
                        # Sobrescreve o aviso de "Aguardando"
                        print(f" > Extraindo: {nat_text}                      ")
                        novos_dados = extract_pages(driver, mes_text, nat_text)
                        dados_consolidados_mes.extend(novos_dados)
                    except Exception:
                        print(f" > Sem dados para {nat_text} (Timeout 60s)    ")
                        continue
                        
                except Exception as e:
                    print(f"   ! Erro na requisicao de {nat_text}: {e}")
                    continue

            # Salvamento e envio mensal
            if dados_consolidados_mes:
                nome_seguro = mes_text.replace(" ", "_").replace(".", "_")
                nome_arquivo = f"servidores_tce_pr_{nome_seguro}.json"
                caminho_absoluto = os.path.abspath(os.path.join(PASTA_SAIDA, nome_arquivo))
                
                try:
                    with open(caminho_absoluto, 'w', encoding='utf-8') as f:
                        json.dump(dados_consolidados_mes, f, ensure_ascii=False, indent=4)
                    print(f" [OK] Salvo: {nome_arquivo} ({len(dados_consolidados_mes)} registros)")
                    
                    comando_rclone = f'rclone move "{caminho_absoluto}" "meudrive:TCC_Scraping/{PASTA_SAIDA}/"'
                    subprocess.run(comando_rclone, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(" [OK] Upload Drive concluido.")
                    
                except subprocess.CalledProcessError:
                    pass # Silencia o erro do rclone no terminal do Windows
                except Exception as e:
                    print(f" [ERRO] Salvamento: {e}")
            else:
                print(" [!] Sem dados para este mes inteiro.")

    except Exception as e:
        print(f"Erro critico: {e}")
    finally:
        driver.quit()
        print("Finalizado.")

if __name__ == "__main__":
    main()