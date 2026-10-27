"""
Camada de banco de dados do Painel de Acompanhamento de Projetos e Demandas Técnicas.

Usa SQLite (arquivo único, sem servidor) — ideal para rodar localmente ou
numa máquina compartilhada na rede do setor.
"""

import os
import sqlite3
from datetime import date, timedelta

# Banco sempre na mesma pasta do código, não importa de onde o script for executado
PASTA_PROJETO = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PASTA_PROJETO, "projetos.db")

# Constantes para dados de exemplo (S1192)
# Origem do contrato e quem arquivou (valores gravados no banco)
ORIGEM_PLANILHA = "planilha"
ORIGEM_MANUAL = "manual"
ARQUIVADO_POR_IMPORTACAO = "importacao"
ARQUIVADO_POR_MANUAL = ORIGEM_MANUAL

PROJETO_MIGRACAO = "Migração de servidores"
PROJETO_REDE = "Atualização de rede"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def criar_schema():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS etapas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projeto TEXT NOT NULL,
            etapa TEXT NOT NULL,
            responsavel TEXT NOT NULL,
            data_inicio TEXT NOT NULL,
            data_fim TEXT NOT NULL,
            percentual_conclusao INTEGER NOT NULL DEFAULT 0,
            observacoes TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def seed_dados_exemplo():
    """Insere alguns registros de exemplo, só se a tabela estiver vazia."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM etapas")
    total = cur.fetchone()[0]
    if total > 0:
        conn.close()
        return

    hoje = date.today()
    exemplos = [
        (
            PROJETO_MIGRACAO,
            "Levantamento do inventário atual",
            "Carlos",
            hoje - timedelta(days=20),
            hoje - timedelta(days=10),
            100,
            "Concluído sem pendências",
        ),
        (
            PROJETO_MIGRACAO,
            "Provisionamento dos novos servidores",
            "Carlos",
            hoje - timedelta(days=9),
            hoje + timedelta(days=5),
            60,
            "",
        ),
        (
            PROJETO_MIGRACAO,
            "Migração dos dados e testes",
            "Ana",
            hoje + timedelta(days=6),
            hoje + timedelta(days=20),
            0,
            "Depende da etapa anterior",
        ),
        (
            PROJETO_REDE,
            "Substituição dos switches do prédio A",
            "Bruno",
            hoje - timedelta(days=15),
            hoje - timedelta(days=2),
            100,
            "",
        ),
        (
            PROJETO_REDE,
            "Reconfiguração de VLANs",
            "Bruno",
            hoje - timedelta(days=5),
            hoje - timedelta(days=1),
            80,
            "Atrasado — aguardando janela de manutenção",
        ),
        (
            PROJETO_REDE,
            "Testes de conectividade",
            "Ana",
            hoje + timedelta(days=2),
            hoje + timedelta(days=12),
            0,
            "",
        ),
    ]

    cur.executemany(
        """
        INSERT INTO etapas
            (projeto, etapa, responsavel, data_inicio, data_fim, percentual_conclusao, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (p, e, r, di.isoformat(), df.isoformat(), pc, obs)
            for (p, e, r, di, df, pc, obs) in exemplos
        ],
    )
    conn.commit()
    conn.close()


def criar_schema_contratos():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS contratos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_processo TEXT,
            tipo TEXT NOT NULL,
            numero_contrato TEXT,
            nome_contrato TEXT,
            razao_social TEXT NOT NULL,
            nome_fantasia TEXT,
            cnpj TEXT,
            objeto TEXT,
            data_inicio TEXT,
            data_fim TEXT,
            fiscal TEXT,
            unidade_area TEXT,
            situacao_planilha TEXT,
            observacoes TEXT,
            arquivado INTEGER NOT NULL DEFAULT 0,
            origem TEXT NOT NULL DEFAULT 'planilha',
            arquivado_por TEXT,
            snapshot_planilha TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def migrar_colunas_contratos():
    """Adiciona colunas novas a um banco de contratos criado com um schema
    mais antigo, sem apagar dados já existentes."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(contratos)")
    colunas_existentes = {linha[1] for linha in cur.fetchall()}

    colunas_necessarias = {
        "nome_contrato": "TEXT",
        "situacao_planilha": "TEXT",
        "arquivado": "INTEGER NOT NULL DEFAULT 0",
        "origem": "TEXT NOT NULL DEFAULT 'planilha'",
        # arquivado_por: 'importacao' (saiu da planilha) ou 'manual' (arquivado por você)
        "arquivado_por": "TEXT",
        # snapshot_planilha: o que a planilha dizia na última importação (JSON). Permite
        # distinguir o que VOCÊ editou no sistema do que apenas veio da planilha.
        "snapshot_planilha": "TEXT",
    }
    for coluna, tipo in colunas_necessarias.items():
        if coluna not in colunas_existentes:
            cur.execute(f"ALTER TABLE contratos ADD COLUMN {coluna} {tipo}")
            if coluna == "origem":
                cur.execute(
                    "UPDATE contratos SET origem = 'manual' "
                    "WHERE nome_contrato IS NULL OR TRIM(nome_contrato) = ''"
                )

    conn.commit()
    conn.close()


def criar_schema_itens_contrato():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS itens_contrato (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contrato_id INTEGER NOT NULL REFERENCES contratos(id) ON DELETE CASCADE,
            item_numero TEXT,
            descricao TEXT NOT NULL,
            local TEXT,
            unidade TEXT,
            quantidade REAL,
            valor_mensal REAL,
            valor_total_item REAL,
            valor_global_contrato REAL,
            vigencia_texto TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def criar_schema_pedidos():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arp TEXT,
            fornecedor TEXT NOT NULL,
            sic TEXT,
            numero_pedido TEXT,
            data_envio TEXT,
            prazo TEXT,
            situacao TEXT NOT NULL DEFAULT 'Aguardando envio'
        )
        """
    )
    conn.commit()
    conn.close()


def inicializar_banco():
    criar_schema()
    seed_dados_exemplo()
    criar_schema_contratos()
    migrar_colunas_contratos()
    criar_schema_itens_contrato()
    criar_schema_pedidos()


if __name__ == "__main__":
    inicializar_banco()
    print(f"Banco '{DB_PATH}' pronto.")