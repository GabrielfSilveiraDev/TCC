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
from selenium.common.exceptions import TimeoutException

# --- CONFIGURAÇÕES ---
OUTPUT_FOLDER = "Dados_RJ"

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)
    print(f"Pasta '{OUTPUT_FOLDER}' criada/verificada.")

# --- 1. OBTER A LISTA DE REFERÊNCIAS (VIA API) ---
print("📡 Obtendo lista de competências via API...")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tcerjtransparencia.admrh.inf.br/rhsysportaltransp/",
    "Cookie": "SESSIONCOOKIESISTEMA2=aVgwkXC61smoXTkV_FdVwHQ0.admrhapp" 
}

url_referencia = "https://tcerjtransparencia.admrh.inf.br/rhsysportaltransp/api/lov/referencia?busca=&page=1"

try:
    response = requests.get(url_referencia, headers=headers, verify=True)
    dados_api = response.json()
    lista_referencias = [item['descricao'] for item in dados_api['dados']]
    print(f"📅 Encontradas {len(lista_referencias)} referências para processar.")
except Exception as e:
    print(f"❌ Erro ao consultar API: {e}")
    lista_referencias = [] 

# --- 2. CONFIGURAÇÃO DO SELENIUM ---
options = Options()
options.add_argument("--headless=new") 
options.add_argument("--start-maximized")
options.add_argument("--no-sandbox")
driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 20)

print("🌍 Acessando o portal...")
driver.get("https://tcerjtransparencia.admrh.inf.br/rhsysportaltransp/")

# Espera inicial
wait.until(EC.presence_of_element_located((By.CLASS_NAME, "ui-select-container")))

def esperar_loading_angular(driver):
    """Espera o spinner de carregamento aparecer e sumir."""
    try:
        WebDriverWait(driver, 2).until(EC.visibility_of_element_located((By.CLASS_NAME, "loading-container")))
        WebDriverWait(driver, 30).until(EC.invisibility_of_element_located((By.CLASS_NAME, "loading-container")))
    except: pass
    time.sleep(0.5)

# --- 3. LOOP EXTERNO (DATAS) ---
for referencia in lista_referencias:
    print(f"\n🔵 Iniciando processamento da competência: {referencia}")
    
    dados_do_mes = []

    try:
        # A. Selecionar Data
        dropdown_container = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".ui-select-container .ui-select-toggle")))
        dropdown_container.click()

        input_busca = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input.ui-select-search")))
        input_busca.clear()
        input_busca.send_keys(referencia)
        time.sleep(0.5) 
        input_busca.send_keys(Keys.ENTER)

        esperar_loading_angular(driver)
        time.sleep(1) 
        
        rows = driver.find_elements(By.CSS_SELECTOR, "table.table-selectable tbody tr")
        if not rows or "nenhum registro" in driver.page_source.lower():
            print(f"⚠️ Nenhum dado encontrado para {referencia}. Pulando...")
            continue

    except Exception as e:
        print(f"❌ Erro ao selecionar a data {referencia}: {e}")
        continue

    # --- 4. LOOP INTERNO (PAGINAÇÃO) ---
    pagina = 1
    
    # Variável para a trava de segurança
    ultimo_primeiro_nome = None
    
    while True:
        print(f"  ↪️ Lendo página {pagina} de {referencia}...", end='\r')
        
        # 4.1 - Verificar se a página mudou (Trava de Segurança)
        try:
            primeiro_nome_atual = driver.find_element(By.CSS_SELECTOR, "table.table-selectable tbody tr td[data-title='Nome']").text.strip()
            if ultimo_primeiro_nome and primeiro_nome_atual == ultimo_primeiro_nome:
                print(f"\n✅ [TRAVA] Página não mudou (Fim da lista detectado por repetição).")
                break
            ultimo_primeiro_nome = primeiro_nome_atual
        except:
            # Se não conseguir ler o nome (tabela vazia), sai do loop
            break

        # 4.2 - Extração
        rows = driver.find_elements(By.CSS_SELECTOR, "table.table-selectable tbody tr")
        
        for i in range(len(rows)):
            rows = driver.find_elements(By.CSS_SELECTOR, "table.table-selectable tbody tr")
            if i >= len(rows): break
            row = rows[i]

            try:
                nome = row.find_element(By.CSS_SELECTOR, "td[data-title='Nome']").text.strip()
                cargo = row.find_element(By.CSS_SELECTOR, "td[data-title='Cargo']").text.strip()
                tipo = row.find_element(By.CSS_SELECTOR, "td[data-title='Vinculo']").text.strip()

                # Scroll e Click
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
                try: row.click()
                except: driver.execute_script("arguments[0].click();", row)
                
                wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".valores")))

                total_blocks = driver.find_elements(By.CSS_SELECTOR, ".valores")
                proventos = []
                total_proventos = 0.0
                total_descontos = 0.0
                salario_liquido = 0.0

                def parse_valor_br(v):
                    if not v: return 0.0
                    return float(v.replace(".", "").replace(",", ".").strip())

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
                    except: continue

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

        # 4.3 - Paginação
        try:
            # Rola para baixo para garantir que o botão está visível
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            
            btn_proximo = driver.find_element(By.CSS_SELECTOR, "a[title='Próxima']")
            parent_li = btn_proximo.find_element(By.XPATH, "./..")
            
            # Se estiver desabilitado visualmente
            if "disabled" in parent_li.get_attribute("class"):
                print(f"\n✅ Fim das páginas (Botão desabilitado).")
                break

            driver.execute_script("arguments[0].click();", btn_proximo)
            esperar_loading_angular(driver)
            pagina += 1
            
        except Exception as e:
            print(f"\n✅ Fim das páginas (Botão não encontrado).")
            break
    
    # --- 5. SALVAR ARQUIVO DO MÊS ---
    if dados_do_mes:
        nome_seguro = referencia.replace('/', '_')
        nome_arquivo = f"servidores_tce_rj_completo_{nome_seguro}.json"
        caminho_completo = os.path.join(OUTPUT_FOLDER, nome_arquivo)
        
        try:
            with open(caminho_completo, "w", encoding="utf-8") as f:
                json.dump(dados_do_mes, f, ensure_ascii=False, indent=4)
            print(f"💾 Arquivo salvo: {nome_arquivo} ({len(dados_do_mes)} registros)")
        except Exception as e:
            print(f"❌ Erro ao salvar arquivo {nome_arquivo}: {e}")

driver.quit()
print("🏁 Processo finalizado.")