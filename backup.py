"""
Backup do banco SQLite (projetos.db).

Usa a API de backup do próprio SQLite: a cópia sai consistente mesmo com o app
aberto e é conferida (PRAGMA integrity_check) antes de ser aceita. Copiar o
arquivo pelo Explorer também funciona quando o app está parado.

    python backup.py                      # backups/projetos_AAAA-MM-DD_HHMMSS_manual.db
    python backup.py --pasta D:\\Backups   # em outra pasta (pasta de rede, OneDrive...)
    python backup.py --manter 60          # quantas cópias guardar por tipo (padrão 30)

Para restaurar: feche o app, renomeie o projetos.db atual (guarde-o) e copie a
cópia desejada para a pasta do projeto com o nome projetos.db.
"""

import argparse
import glob
import os
import sqlite3
from datetime import datetime
from typing import Optional

from database import DB_PATH, PASTA_PROJETO

PASTA_BACKUPS = os.path.join(PASTA_PROJETO, "backups")
PREFIXO = "projetos_"
EXTENSAO = ".db"
FORMATO_DATA_ARQUIVO = "%Y-%m-%d_%H%M%S"
MANTER_PADRAO = 30

MOTIVO_MANUAL = "manual"
MOTIVO_ANTES_IMPORTACAO = "antes_importacao"
MOTIVO_SEMANAL = "semanal"


def _caminho_novo(pasta: str, motivo: str) -> str:
    base = f"{PREFIXO}{datetime.now().strftime(FORMATO_DATA_ARQUIVO)}_{motivo}"
    caminho = os.path.join(pasta, base + EXTENSAO)
    repeticao = 2
    while os.path.exists(caminho):  # dois backups no mesmo segundo
        caminho = os.path.join(pasta, f"{base}_{repeticao}{EXTENSAO}")
        repeticao += 1
    return caminho


def _copiar_com_api_sqlite(origem: str, destino: str) -> None:
    conn_origem = sqlite3.connect(origem)
    conn_destino = sqlite3.connect(destino)
    try:
        conn_origem.backup(conn_destino)
    finally:
        conn_destino.close()
        conn_origem.close()


def _banco_integro(caminho: str) -> bool:
    conn = sqlite3.connect(caminho)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def _limpar_antigos(pasta: str, motivo: str, manter: int) -> None:
    """Mantém só as `manter` cópias mais recentes de cada tipo (manual, semanal...)."""
    padrao = os.path.join(pasta, f"{PREFIXO}*_{motivo}*{EXTENSAO}")
    for antigo in sorted(glob.glob(padrao), reverse=True)[manter:]:
        os.remove(antigo)


def fazer_backup(
    pasta: Optional[str] = None, motivo: str = MOTIVO_MANUAL, manter: int = MANTER_PADRAO
) -> str:
    """Cria uma cópia do banco e devolve o caminho dela."""
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(f"Banco não encontrado: {DB_PATH}")

    pasta = pasta or PASTA_BACKUPS
    os.makedirs(pasta, exist_ok=True)
    destino = _caminho_novo(pasta, motivo)

    _copiar_com_api_sqlite(DB_PATH, destino)
    if not _banco_integro(destino):
        os.remove(destino)
        raise RuntimeError("A cópia do banco falhou na verificação de integridade e foi descartada.")

    _limpar_antigos(pasta, motivo, manter)
    return destino


def ultimo_backup(pasta: Optional[str] = None) -> Optional[tuple[str, datetime]]:
    """(caminho, data) do backup mais recente da pasta, ou None se não houver."""
    pasta = pasta or PASTA_BACKUPS
    arquivos = glob.glob(os.path.join(pasta, f"{PREFIXO}*{EXTENSAO}"))
    if not arquivos:
        return None
    recente = max(arquivos, key=os.path.getmtime)
    return recente, datetime.fromtimestamp(os.path.getmtime(recente))


def main() -> None:
    parser = argparse.ArgumentParser(description="Faz um backup do projetos.db.")
    parser.add_argument("--pasta", help="pasta de destino (padrão: backups/ do projeto)")
    parser.add_argument("--manter", type=int, default=MANTER_PADRAO, help="cópias a guardar por tipo")
    args = parser.parse_args()
    print(f"Backup criado: {fazer_backup(args.pasta, MOTIVO_MANUAL, args.manter)}")


if __name__ == "__main__":
    main()
