"""
Funções de acesso a dados (CRUD) e cálculo de KPIs.
Mantidas separadas do app.py para facilitar testes e reuso.
"""

from datetime import date

import pandas as pd  # type: ignore

from database import get_connection

# Constantes de status para evitar duplicação de literais (S1192)
STATUS_CONCLUIDO = "Concluído"
STATUS_ATRASADO = "Atrasado"
STATUS_EM_ANDAMENTO = "Em andamento"


def listar_etapas() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM etapas ORDER BY data_fim", conn)
    conn.close()

    if df.empty:
        return df

    df["data_inicio"] = pd.to_datetime(df["data_inicio"])
    df["data_fim"] = pd.to_datetime(df["data_fim"])

    hoje = pd.Timestamp(date.today())

    def calcular_status(row):
        if row["percentual_conclusao"] >= 100:
            return STATUS_CONCLUIDO
        if row["data_fim"] < hoje:
            return STATUS_ATRASADO
        return STATUS_EM_ANDAMENTO

    df["status"] = df.apply(calcular_status, axis=1)
    return df


def inserir_etapa(projeto, etapa, responsavel, data_inicio, data_fim, percentual, observacoes):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO etapas
            (projeto, etapa, responsavel, data_inicio, data_fim, percentual_conclusao, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (projeto, etapa, responsavel, data_inicio.isoformat(), data_fim.isoformat(), percentual, observacoes),
    )
    conn.commit()
    conn.close()


def atualizar_etapa(etapa_id, projeto, etapa, responsavel, data_inicio, data_fim, percentual, observacoes):
    conn = get_connection()
    conn.execute(
        """
        UPDATE etapas
        SET projeto = ?, etapa = ?, responsavel = ?, data_inicio = ?,
            data_fim = ?, percentual_conclusao = ?, observacoes = ?
        WHERE id = ?
        """,
        (
            projeto,
            etapa,
            responsavel,
            data_inicio.isoformat(),
            data_fim.isoformat(),
            percentual,
            observacoes,
            etapa_id,
        ),
    )
    conn.commit()
    conn.close()


def excluir_etapa(etapa_id):
    conn = get_connection()
    conn.execute("DELETE FROM etapas WHERE id = ?", (etapa_id,))
    conn.commit()
    conn.close()


def calcular_kpis(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"atrasadas": 0, "concluidas_mes": 0, "em_andamento": 0}

    hoje = pd.Timestamp(date.today())
    inicio_mes = hoje.replace(day=1)

    atrasadas = int((df["status"] == STATUS_ATRASADO).sum())
    em_andamento = int((df["status"] == STATUS_EM_ANDAMENTO).sum())
    concluidas_mes = int(
        ((df["status"] == STATUS_CONCLUIDO) & (df["data_fim"] >= inicio_mes)).sum()
    )

    return {
        "atrasadas": atrasadas,
        "concluidas_mes": concluidas_mes,
        "em_andamento": em_andamento,
    }


def carga_por_responsavel(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    pendentes = df[df["status"] != STATUS_CONCLUIDO]
    return (
        pendentes.groupby("responsavel")
        .size()
        .reset_index(name="etapas_pendentes")
        .sort_values("etapas_pendentes", ascending=False)
    )