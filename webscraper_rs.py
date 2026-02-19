import json
import os
import time
import re # Importamos Regex para limpar os dados
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURAÇÕES ---
URL_BASE = "https://portal.tce.rs.gov.br/aplicprod/f?p=10200:1:::NO:::"
OUTPUT_FOLDER = "Dados_RS"
ANO_LIMITE = 2020 # Irá baixar até Janeiro de 2020 (inclusive)

# --- FUNÇÕES AUXILIARES ---

def setup_driver():
    options = Options()
    options.add_argument("--headless=new") # Descomente para não ver o navegador
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=options)
    return driver

def esperar_loading_apex(driver):
    """Espera o spinner de carregamento (u-Processing) sumir."""
    try:
        # Espera aparecer
        WebDriverWait(driver, 2).until(EC.visibility_of_element_located((By.CLASS_NAME, "u-Processing")))
        # Espera sumir
        WebDriverWait(driver, 30).until(EC.invisibility_of_element_located((By.CLASS_NAME, "u-Processing")))
    except:
        pass
    time.sleep(0.3)

def extrair_ano_seguro(texto):
    """
    Usa Regex para encontrar 4 dígitos após uma barra, ignorando espaços.
    Ex: "  05 / 2025 \n" -> Retorna 2025
    """
    # Procura por uma barra /, qualquer coisa (.*?), e então 4 digitos (\d{4})
    match = re.search(r'/.*?(\d{4})', texto)
    if match:
        return int(match.group(1))
    return None

def salvar_registro_no_mes_correto(registro):
    """
    Salva o registro no arquivo JSON correspondente ao mês/ano.
    """
    mes_ano = registro.get("mes_ano")
    if not mes_ano: return

    # Remove barras e espaços para nome de arquivo seguro
    safe_date = mes_ano.replace('/', '_').strip()
    nome_arquivo = f"servidores_tce_rs_{safe_date}.json"
    
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        
    caminho_arquivo = os.path.join(OUTPUT_FOLDER, nome_arquivo)

    dados_existentes = []
    if os.path.exists(caminho_arquivo):
        try:
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                dados_existentes = json.load(f)
        except: pass

    dados_existentes.append(registro)

    try:
        with open(caminho_arquivo, 'w', encoding='utf-8') as f:
            json.dump(dados_existentes, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"    ❌ Erro ao salvar: {e}")

def extrair_dados_da_tela(driver, mes_ano_texto):
    dados = {"mes_ano": mes_ano_texto.strip()}
    
    try:
        # Mapeamento dos IDs para nomes legíveis
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
    print(f"  👤 {nome_servidor}...")
    
    try:
        driver.get(url_servidor)
        esperar_loading_apex(driver)
        
        # Localiza o Select
        select_elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "P7_PERIODO"))
        )
        select = Select(select_elem)
        
        # --- LÓGICA DE FILTRO CORRIGIDA ---
        todas_opcoes_texto = [opt.text for opt in select.options]
        datas_validas = []
        
        for texto in todas_opcoes_texto:
            ano = extrair_ano_seguro(texto)
            
            if ano:
                if ano >= ANO_LIMITE:
                    datas_validas.append(texto)
                # else:
                #    print(f"     Ignorando {texto} (Ano < {ANO_LIMITE})")
        
        print(f"    📅 Histórico filtrado: {len(datas_validas)} meses (Até {ANO_LIMITE}).")
        # ----------------------------------

        # Itera apenas nas datas filtradas
        for data_str in datas_validas:
            try:
                # Reencontra elemento (DOM refresh)
                select_elem = driver.find_element(By.ID, "P7_PERIODO")
                select = Select(select_elem)
                
                # Seleciona
                select.select_by_visible_text(data_str)
                esperar_loading_apex(driver)
                
                # Extrai e Salva
                registro = extrair_dados_da_tela(driver, data_str)
                salvar_registro_no_mes_correto(registro)
                
            except Exception as e:
                print(f"    ❌ Falha ao processar mês {data_str}: {e}")
                continue

    except Exception as e:
        print(f"  ❌ Erro ao acessar perfil: {e}")

def main():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        
    start_time = datetime.now()
    print(f"⏱️ Iniciando em {start_time.strftime('%H:%M:%S')}")
    
    driver = setup_driver()
    urls_processadas = set()
    
    try:
        driver.get(URL_BASE)
        print("🌐 Acessando lista...")
        esperar_loading_apex(driver)
        
        while True:
            # Raspa links da página atual
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

            print(f"\n📄 Página: {len(links_servidores)} servidores encontrados.")

            # Processa servidores
            for nome, url in links_servidores:
                if url in urls_processadas: continue
                
                # Nova aba para não perder a lista
                driver.execute_script("window.open('');")
                driver.switch_to.window(driver.window_handles[1])
                
                processar_servidor(driver, url, nome)
                
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                urls_processadas.add(url)

            # Próxima página
            try:
                btn_next = driver.find_element(By.CSS_SELECTOR, "button.a-IRR-button--pagination[title='Próximo']")
                if not btn_next.is_displayed():
                    print("🏁 Fim da lista.")
                    break
                driver.execute_script("arguments[0].click();", btn_next)
                esperar_loading_apex(driver)
                time.sleep(1)
            except:
                print("🏁 Fim (Botão Próximo não encontrado).")
                break

    except Exception as e:
        print(f"❌ Erro Fatal: {e}")
    finally:
        driver.quit()
        end = datetime.now()
        print(f"\n🏁 Tempo Total: {end - start_time}")

if __name__ == "__main__":
    main()