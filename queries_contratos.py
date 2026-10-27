"""
Funções de acesso a dados (CRUD) e cálculo de status para contratos/ARPs.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd  # type: ignore

from database import ARQUIVADO_POR_IMPORTACAO, ARQUIVADO_POR_MANUAL, get_connection

DIAS_ALERTA_VENCIMENTO = 90  # a partir de quantos dias antes do vencimento vira "alerta"
STATUS_SEM_DATA = "Sem data definida"

# Faixas usadas no painel (ordem de exibição)
FAIXAS_VENCIMENTO = [
    "Vencido",
    "Até 30 dias",
    "31 a 60 dias",
    "61 a 90 dias",
    "Acima de 90 dias",
    STATUS_SEM_DATA,
]


@dataclass
class ContratoDTO:
    """Estrutura de dados para evitar excesso de parâmetros (code smell S107)."""
    id_processo: Optional[str]
    tipo: str
    numero_contrato: str
    nome_contrato: Optional[str]
    razao_social: str
    nome_fantasia: Optional[str]
    cnpj: Optional[str]
    objeto: Optional[str]
    data_inicio: Optional[date]
    data_fim: Optional[date]
    fiscal: Optional[str]
    unidade_area: Optional[str]
    situacao_planilha: Optional[str]
    observacoes: Optional[str]
    arquivado: bool = False


def classificar_faixa(dias) -> str:
    if pd.isna(dias):
        return STATUS_SEM_DATA
    if dias < 0:
        return "Vencido"
    if dias <= 30:
        return "Até 30 dias"
    if dias <= 60:
        return "31 a 60 dias"
    if dias <= 90:
        return "61 a 90 dias"
    return "Acima de 90 dias"


def listar_contratos(incluir_arquivados: bool = False) -> pd.DataFrame:
    """Contratos e ARPs. Por padrão, os arquivados (que saíram da planilha) ficam de fora."""
    conn = get_connection()
    consulta = "SELECT * FROM contratos"
    if not incluir_arquivados:
        consulta += " WHERE arquivado = 0"
    df = pd.read_sql_query(consulta + " ORDER BY data_fim", conn)
    conn.close()

    if df.empty:
        return df

    df["data_inicio"] = pd.to_datetime(df["data_inicio"])
    df["data_fim"] = pd.to_datetime(df["data_fim"])

    hoje = pd.Timestamp(date.today())

    def calcular_status(row):
        if pd.isna(row["data_fim"]):
            return STATUS_SEM_DATA
        dias = (row["data_fim"] - hoje).days
        if dias < 0:
            return "Vencido"
        if dias <= DIAS_ALERTA_VENCIMENTO:
            return "Vencendo em breve"
        return "Vigente"

    df["status"] = df.apply(calcular_status, axis=1)
    df["dias_para_vencer"] = (df["data_fim"] - hoje).dt.days
    df["faixa_vencimento"] = df["dias_para_vencer"].map(classificar_faixa)
    return df


def buscar_contratos(df: pd.DataFrame, texto: str) -> pd.DataFrame:
    if not texto:
        return df
    texto = texto.lower()
    colunas_busca = [
        "id_processo",
        "numero_contrato",
        "nome_contrato",
        "razao_social",
        "nome_fantasia",
        "objeto",
        "fiscal",
    ]
    mascara = False
    for col in colunas_busca:
        mascara = mascara | df[col].fillna("").str.lower().str.contains(texto, na=False)
    return df[mascara]


def inserir_contrato(contrato: ContratoDTO) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO contratos
            (id_processo, tipo, numero_contrato, nome_contrato, razao_social, nome_fantasia,
             cnpj, objeto, data_inicio, data_fim, fiscal, unidade_area, situacao_planilha,
             observacoes, origem)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual')
        """,
        (
            contrato.id_processo,
            contrato.tipo,
            contrato.numero_contrato,
            contrato.nome_contrato,
            contrato.razao_social,
            contrato.nome_fantasia,
            contrato.cnpj,
            contrato.objeto,
            contrato.data_inicio.isoformat() if contrato.data_inicio else None,
            contrato.data_fim.isoformat() if contrato.data_fim else None,
            contrato.fiscal,
            contrato.unidade_area,
            contrato.situacao_planilha,
            contrato.observacoes,
        ),
    )
    conn.commit()
    conn.close()


def atualizar_contrato(contrato_id: int, contrato: ContratoDTO) -> None:
    """Grava a edição feita na tela. Regras do arquivamento:

    * arquivar à mão     -> arquivado_por = 'manual' (a importação nunca reativa);
    * reativar à mão um contrato que a importação tinha arquivado -> passa a ser
      'manual' e a importação não o arquiva de novo.
    """
    arquivar = 1 if contrato.arquivado else 0
    conn = get_connection()
    conn.execute(
        """
        UPDATE contratos
        SET id_processo = :id_processo, tipo = :tipo, numero_contrato = :numero_contrato,
            nome_contrato = :nome_contrato, razao_social = :razao_social,
            nome_fantasia = :nome_fantasia, cnpj = :cnpj, objeto = :objeto,
            data_inicio = :data_inicio, data_fim = :data_fim, fiscal = :fiscal,
            unidade_area = :unidade_area, situacao_planilha = :situacao_planilha,
            observacoes = :observacoes,
            origem = CASE WHEN :arquivar = 0 AND arquivado = 1
                               AND arquivado_por = :por_importacao
                          THEN :manual ELSE origem END,
            arquivado_por = CASE WHEN :arquivar = 0 THEN NULL
                                 WHEN arquivado = 1 THEN arquivado_por
                                 ELSE :manual END,
            arquivado = :arquivar
        WHERE id = :contrato_id
        """,
        {
            "id_processo": contrato.id_processo,
            "tipo": contrato.tipo,
            "numero_contrato": contrato.numero_contrato,
            "nome_contrato": contrato.nome_contrato,
            "razao_social": contrato.razao_social,
            "nome_fantasia": contrato.nome_fantasia,
            "cnpj": contrato.cnpj,
            "objeto": contrato.objeto,
            "data_inicio": contrato.data_inicio.isoformat() if contrato.data_inicio else None,
            "data_fim": contrato.data_fim.isoformat() if contrato.data_fim else None,
            "fiscal": contrato.fiscal,
            "unidade_area": contrato.unidade_area,
            "situacao_planilha": contrato.situacao_planilha,
            "observacoes": contrato.observacoes,
            "arquivar": arquivar,
            "por_importacao": ARQUIVADO_POR_IMPORTACAO,
            "manual": ARQUIVADO_POR_MANUAL,
            "contrato_id": int(contrato_id),
        },
    )
    conn.commit()
    conn.close()


def excluir_contrato(contrato_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM contratos WHERE id = ?", (contrato_id,))
    conn.commit()
    conn.close()


def calcular_kpis_contratos(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"vigentes": 0, "vencendo": 0, "vencidos": 0}
    return {
        "vigentes": int((df["status"] == "Vigente").sum()),
        "vencendo": int((df["status"] == "Vencendo em breve").sum()),
        "vencidos": int((df["status"] == "Vencido").sum()),
    }