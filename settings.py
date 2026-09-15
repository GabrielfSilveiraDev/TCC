"""
settings.py — Configuração centralizada, lida de variáveis de ambiente e do arquivo .env.

Nenhuma credencial fica no código: os valores vêm do .env (ignorado pelo Git).
Use .env.example como modelo. Variáveis de ambiente do sistema têm precedência
sobre o .env, o que permite apontar para outro banco sem editar arquivos.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent


class DatabaseSettings(BaseSettings):
    """Parâmetros de conexão com o SQL Server (variáveis DB_*)."""

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    server:   str = "localhost,1433"
    name:     str = "remuneracao_tce"
    user:     str = "sa"
    password: Optional[SecretStr] = None
    driver:   str = "ODBC Driver 17 for SQL Server"

    @model_validator(mode="after")
    def _exigir_senha_com_usuario(self) -> "DatabaseSettings":
        # Usuário vazio = autenticação integrada do Windows, que dispensa senha.
        if self.user and not self.password:
            raise ValueError(
                "DB_PASSWORD não definida. Copie .env.example para .env e preencha a senha."
            )
        return self

    def connection_string(self) -> str:
        base = f"DRIVER={{{self.driver}}};SERVER={self.server};DATABASE={self.name};"
        if not self.user:
            return base + "Trusted_Connection=yes;TrustServerCertificate=yes;"
        # Chaves protegem senhas com ';' ou '}' dentro da connection string ODBC.
        senha = self.password.get_secret_value().replace("}", "}}")
        return base + f"UID={self.user};PWD={{{senha}}};TrustServerCertificate=yes;"


@lru_cache
def get_database_settings() -> DatabaseSettings:
    """Instância única por processo (o .env é lido uma vez)."""
    return DatabaseSettings()
