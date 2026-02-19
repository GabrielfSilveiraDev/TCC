<<<<<<< HEAD
# Painel de Transparência de Servidores Públicos - TCEs SC, SP e RJ

Este projeto realiza a coleta, tratamento e visualização de dados de remuneração de servidores públicos dos Tribunais de Contas de Santa Catarina (TCE-SC), São Paulo (TCE-SP) e Rio de Janeiro (TCE-RJ).

Funcionalidades

- Webscraping com Selenium dos portais de transparência dos TCEs.
- Estruturação dos dados em JSON (padronizado).
- Dashboard interativo com **Streamlit** para análise dos dados:
  - Comparativo entre estados.
  - Filtros por nome, cargo, tipo (ativo/inativo) e faixa salarial.
  - Ranking de maiores salários e bonificações.
  - Gráficos de distribuição salarial e proventos.
  - Exportação de CSV dos dados filtrados.

# Tecnologias

- Python 3.11+
- Selenium
- BeautifulSoup
- Pandas
- Streamlit
- Plotly

# Como executar:

1. Clone o repositório

  git clone https://github.com/GabrielfSilveiraDev/Webscrapper-INE-5454.git
  cd Webscrapper-INE-5454

2. Instale as dependências
   
  pip install -r requirements.txt
  Dica: Use um ambiente virtual (venv)

3. Rode o webscraper para um dos estados
   
  python webscrapper_sc.py      # Para TCE-SC  
  python webscrapper_sp.py      # Para TCE-SP  
  python webscrapper_rj.py      # Para TCE-RJ

4. Rode o webscraper para um dos estados

  servidores_tce_sc_estruturado.json # Para TCE-SC
  servidores_tce_sp_estruturado.json # Para TCE-SP  
  servidores_tce_rj_estruturado.json # Para TCE-RJ

5. Inicie o dashboard

  streamlit run Dashboards.py
=======
# TCC
>>>>>>> c6f1cf2547da12dbc0801e60d145adef912b874b
