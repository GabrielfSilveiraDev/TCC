import os
import json
from abc import ABC, abstractmethod
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from datetime import datetime

class BaseScraper(ABC):
    """
    Classe base abstrata para web scrapers.
    """
    def __init__(self, name, output_folder):
        self.name = name
        self.output_folder = output_folder
        self.progress_file = os.path.join(self.output_folder, 'progress.json')
        self.log(f"Iniciando o scraper {self.name}.")
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder)

    def log(self, message):
        """
        Registra uma mensagem com o nome do scraper e timestamp.
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}][{self.name}] {message}")

    def _save_progress(self, state):
        """Salva o progresso do scraping."""
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.log(f"Erro ao salvar o progresso: {e}")

    def _load_progress(self):
        """Carrega o progresso do scraping."""
        if os.path.exists(self.progress_file):
            self.log(f"Carregando progresso de {self.progress_file}")
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError) as e:
                self.log(f"Arquivo de progresso não encontrado ou inválido, começando do início. Erro: {e}")
                return {}
        return {}

    def save_data(self, data, filename):
        """
        Salva os dados em um arquivo JSON.
        """
        if not data:
            self.log("Nenhum dado para salvar.")
            return

        filepath = os.path.join(self.output_folder, filename)
        self.log(f"Salvando {len(data)} registros em {filepath}...")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self.log("Arquivo salvo com sucesso.")
        except Exception as e:
            self.log(f"Erro ao salvar o arquivo: {e}")

    def limpar_numero_br(self, texto):
        """Converte string monetária BR ('1.234,56' ou 'R$ 1.234,56') para float."""
        if not texto:
            return 0.0
        limpo = str(texto).strip().replace('R$', '').replace('\xa0', '').replace(' ', '').replace('.', '').replace(',', '.')
        try:
            return float(limpo)
        except Exception:
            return 0.0

    def save_data_merge(self, data, filename, key_fields):
        """Adiciona registros a arquivo existente evitando duplicatas pelas key_fields fornecidas."""
        if not data:
            return
        filepath = os.path.join(self.output_folder, filename)
        existentes = []
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    existentes = json.load(f)
            except Exception:
                existentes = []
        chaves = {tuple(r.get(k) for k in key_fields) for r in existentes}
        novos = [r for r in data if tuple(r.get(k) for k in key_fields) not in chaves]
        if novos:
            self.save_data(existentes + novos, filename)

    @abstractmethod
    def scrape(self):
        """
        Método abstrato para o scraping. Deve ser implementado por subclasses.
        """
        pass

    def run(self):
        """
        Executa o scraper com logging de tempo.
        """
        start_time = time.time()
        self.log("Execução iniciada.")
        try:
            self.scrape()
        except Exception as e:
            self.log(f"Um erro crítico ocorreu: {e}")
        finally:
            end_time = time.time()
            duration = time.strftime("%H:%M:%S", time.gmtime(end_time - start_time))
            self.log(f"Execução finalizada. Duração: {duration}.")
            self.shutdown()

    def shutdown(self):
        """Método para limpeza de recursos."""
        pass


class SeleniumScraper(BaseScraper):
    def __init__(self, name, output_folder, headless=True):
        self.headless = headless
        super().__init__(name, output_folder)
        self.driver = self._setup_driver()

    def _setup_driver(self):
        """
        Configura o WebDriver do Selenium.
        """
        self.log("Configurando o WebDriver do Selenium...")
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        
        preferencias = {
            "download.default_directory": os.path.abspath(self.output_folder),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "profile.default_content_setting_values.automatic_downloads": 1 
        }
        options.add_experimental_option("prefs", preferencias)
        
        return webdriver.Chrome(options=options)
    
    def shutdown(self):
        """Fecha o WebDriver."""
        if self.driver:
            self.driver.quit()
        self.log("WebDriver fechado.")


class RequestsScraper(BaseScraper):
    def __init__(self, name, output_folder):
        super().__init__(name, output_folder)
        self.session = self._setup_session()

    def _setup_session(self):
        """
        Configura a sessão de requests com retry automático para erros de conexão.
        """
        self.log("Configurando a sessão de requests...")
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36"
        })
        retry_strategy = Retry(
            total=5,
            backoff_factor=10,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session
