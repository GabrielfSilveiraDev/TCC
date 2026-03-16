import requests
from bs4 import BeautifulSoup
import json
import os
import time
import subprocess
from datetime import datetime

URL_BASE = "https://www.tce.sp.gov.br/transparencia-tcesp/gestao-pessoas/remuneracao/tabela"
PASTA_SAIDA = "Dados_SP"

MAPA_ANOS = {
    2025: 1,
    2024: 2,
    2023: 3,
    2022: 4,
    2021: 5
}

SITUACOES = {
    1: "ATIVO",
    2: "INATIVO"
}

def limpar_numero(texto):
    """
    Summary: Converte string de formato de moeda brasileira para float.
    Alteracoes: Nome e logica traduzidos para o portugues.
    """
    if not texto:
        return 0.0
    limpo = texto.strip().replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except Exception:
        return 0.0

def buscar_dados_mes(ano_rotulo, ano_id, mes):
    """
    Summary: Busca e pagina os dados de um mes e ano especifico para todas as situacoes.
    Alteracoes: Logs limpos e variaveis padronizadas.
    """
    dados_mes = []
    
    for cod_situacao, nome_situacao in SITUACOES.items():
        print(f"  > Processando: {nome_situacao}...")
        
        pagina = 1
        while True:
            parametros = {
                "vencimentos_ano": ano_id,
                "Mes": mes,
                "Situacao": cod_situacao,
                "Nome": "",
                "Identificacao": 1,
                "page": pagina
            }
            
            try:
                resposta = requests.get(URL_BASE, params=parametros, timeout=30)
                resposta.raise_for_status()
            except requests.RequestException as e:
                print(f"    Erro na requisicao (Pagina {pagina}): {e}")
                break

            sopa = BeautifulSoup(resposta.text, "html.parser")
            tabela = sopa.select_one("div.table-responsive table.table-hover.table-striped tbody")
            
            if not tabela:
                break
            
            linhas = tabela.find_all("tr")
            if not linhas:
                break
            
            for tr in linhas:
                td = tr.find_all("td")
                if len(td) < 21:
                    continue

                nome = td[3].text.strip()
                cargo = td[20].text.strip()
                
                proventos_brutos = [
                    ("Vencimentos", td[5].text.strip()),
                    ("Vantagens Pessoais", td[6].text.strip()),
                    ("Outras Verbas", td[7].text.strip()),
                    ("Eventuais", td[11].text.strip()),
                    ("Abono Permanencia", td[12].text.strip()),
                    ("Auxilios", td[13].text.strip()),
                    ("1/3 Ferias", td[14].text.strip()),
                    ("13 Salario", td[16].text.strip()),
                    ("13 Abono", td[17].text.strip()),
                ]
                proventos = [{"descricao": desc, "valor": val} for desc, val in proventos_brutos if limpar_numero(val) != 0]

                descontos_brutos = [
                    ("Redutor", td[8].text.strip()),
                    ("Descontos Legais", td[10].text.strip()),
                    ("Desconto Ferias", td[15].text.strip()),
                    ("Desconto 13", td[18].text.strip()),
                ]
                descontos = [{"descricao": desc, "valor": val} for desc, val in descontos_brutos if limpar_numero(val) != 0]

                total_prov = td[9].text.strip()
                sal_liq = td[19].text.strip()
                
                total_desc_float = sum(limpar_numero(d["valor"]) for d in descontos)
                total_desc_str = f"{total_desc_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                obj_servidor = {
                    "nome": nome,
                    "cargo": cargo,
                    "mes_ano": f"{mes:02d}/{ano_rotulo}",
                    "tipo": nome_situacao,
                    "proventos": proventos,
                    "descontos": descontos,
                    "total_proventos": total_prov,
                    "total_descontos": total_desc_str,
                    "salario_liquido": sal_liq,
                    "url_origem": resposta.url
                }
                
                dados_mes.append(obj_servidor)
            
            link_prox_pagina = sopa.find("a", {"rel": "next"})
            if not link_prox_pagina:
                break
            
            pagina += 1
            time.sleep(0.1)
            
    return dados_mes

def principal():
    """
    Summary: Funcao principal que orquestra a extracao do TCE-SP integrando salvamento e Rclone.
    Alteracoes: Caminho absoluto e blocos try-except para assegurar continuidade.
    """
    if not os.path.exists(PASTA_SAIDA):
        os.makedirs(PASTA_SAIDA)
        print(f"Pasta '{PASTA_SAIDA}' criada.")
    
    tempo_inicio = datetime.now()
    
    for ano_rotulo, ano_id in MAPA_ANOS.items():
        
        ultimo_mes = 10 if ano_rotulo == 2025 else 12
        
        for mes in range(1, ultimo_mes + 1):
            print(f"\n=== Iniciando extracao: {mes:02d}/{ano_rotulo} (ID Ano: {ano_id}) ===")
            
            dados = buscar_dados_mes(ano_rotulo, ano_id, mes)
            
            if not dados:
                print(f"Nenhum dado encontrado para {mes:02d}/{ano_rotulo}.")
                continue
            
            nome_arquivo = f"servidores_tce_sp_completo_{mes:02d}_{ano_rotulo}.json"
            caminho_absoluto = os.path.abspath(os.path.join(PASTA_SAIDA, nome_arquivo))
            
            try:
                with open(caminho_absoluto, "w", encoding="utf-8") as f:
                    json.dump(dados, f, ensure_ascii=False, indent=4)
                print(f"Salvo localmente: {nome_arquivo} ({len(dados)} registros)")

                comando_rclone = f'rclone move "{caminho_absoluto}" "meudrive:TCC_Scraping/{PASTA_SAIDA}/"'
                subprocess.run(comando_rclone, shell=True, check=True)
                print("Upload para o Drive concluido e arquivo local apagado.")
                
            except subprocess.CalledProcessError as erro_processo:
                print(f"Aviso: Rclone retornou erro. Arquivo garantido no HD local. {erro_processo}")
            except FileNotFoundError:
                print("Aviso: Rclone nao encontrado no PATH do Windows. Arquivo garantido no HD local.")
            except Exception as e:
                print(f"Erro inesperado ao salvar/enviar arquivo: {e}")
            
            time.sleep(0.5)

    tempo_fim = datetime.now()
    print(f"\nExtracao finalizada em {tempo_fim - tempo_inicio}.")

if __name__ == "__main__":
    principal()