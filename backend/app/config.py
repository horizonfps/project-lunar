# backend/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    anthropic_proxy_url: str = ""
    anthropic_proxy_key: str = "proxy"
    openai_proxy_url: str = ""
    openai_proxy_key: str = "proxy"
    debug: bool = False
    # Root directory for scenario assets (character cards, art). Served at /media.
    media_dir: str = "../local/media"

    model_config = {"env_file": [".env", "../.env"]}


settings = Settings()
