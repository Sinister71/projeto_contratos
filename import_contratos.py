"""
Importa a planilha de contratos/ARPs (aba "GETI - Visão geral") para o banco.

Rodar com:
    python import_contratos.py Contratos_e_ARPs.xlsx
    python import_contratos.py Contratos_e_ARPs.xlsx --forcar-planilha   # planilha manda em tudo
    python import_contratos.py Contratos_e_ARPs.xlsx --sem-backup        # não faz o backup prévio

Antes de gravar, o script faz um backup automático do banco (pasta backups/).

Pode (e deve) ser rodado de novo sempre que a planilha for atualizada. Regras:

* A identidade de um contrato é  TIPO + Nº DO CONTRATO  (ex.: "Contrato 115-2025").
  O "ID do processo" NÃO é usado como chave porque muda a cada renovação
  (o 115-2025 foi do processo GDC-0710/2025 para o GDC-0672/2026).
* Contrato que já existe  -> é atualizado com o que MUDOU NA PLANILHA (datas, processo,
  fiscal...). Os itens cadastrados e as observações são preservados.
* O que VOCÊ editou no sistema é protegido: se um campo do sistema for diferente do que a
  planilha disse na última importação, ele é mantido e a importação apenas avisa que a
  planilha está diferente (ex.: renovação lançada à mão antes de a planilha ser atualizada).
  O aviso some sozinho quando a planilha passar a dizer o mesmo que o sistema.
  Use --forcar-planilha para a planilha sobrescrever tudo.
* Contrato novo           -> é inserido.
* Contrato que SAIU da planilha (vencido e retirado, por exemplo) -> é ARQUIVADO,
  não apagado: some do painel, mas os itens continuam guardados. Se voltar para
  a planilha, é reativado automaticamente.
* Contratos cadastrados manualmente na tela "Cadastros" nunca são arquivados
  por este script.
* Se a planilha tiver duas linhas do mesmo contrato (ex.: uma do processo de
  renovação ainda sem datas), vale a linha com a data de vencimento mais recente.
"""

import argparse
import glob
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from itertools import groupby
from typing import Optional

import pandas as pd  # type: ignore

from backup import MOTIVO_ANTES_IMPORTACAO, fazer_backup
from database import (
    ARQUIVADO_POR_IMPORTACAO,
    ARQUIVADO_POR_MANUAL,
    DB_PATH,
    ORIGEM_PLANILHA,
    PASTA_PROJETO,
    get_connection,
    inicializar_banco,
)
from exportar_dashboard import CHAVE_CONTRATOS, CHAVE_ITENS, publicar_dashboard

COLUNAS_OBRIGATORIAS = [
    "ID do processo",
    "Nome do contrato",
    "CPF/CNPJ",
    "Razão social",
    "Nome fantasia",
    "Nº do contrato",
    "Objeto resumido",
    "Vigência",
    "Vencimento",
    "Fiscal do contrato",
    "Unidade/Área",
    "Situação",
]


def limpar_nome_coluna(nome: str) -> str:
    # A planilha original tem caracteres invisíveis (U+200E) em alguns cabeçalhos
    return str(nome).replace("\u200e", "").strip()


def inferir_tipo(nome_contrato: str) -> str:
    nome_contrato = (nome_contrato or "").strip().lower()
    if nome_contrato.startswith("ata de registro de preços"):
        return "Ata de registro de preços"
    return "Contrato"


def _texto(valor) -> str:
    return "" if pd.isna(valor) else str(valor).strip()


def _data(valor):
    return None if pd.isna(valor) else pd.Timestamp(valor).date().isoformat()


def ler_planilha(caminho_xlsx: str) -> list[dict]:
    df = pd.read_excel(caminho_xlsx, sheet_name=0)
    df.columns = [limpar_nome_coluna(c) for c in df.columns]

    faltando = set(COLUNAS_OBRIGATORIAS) - set(df.columns)
    if faltando:
        raise ValueError(f"Colunas esperadas não encontradas na planilha: {sorted(faltando)}")

    registros = []
    for _, row in df.iterrows():
        nome = _texto(row["Nome do contrato"])
        registros.append(
            {
                "id_processo": _texto(row["ID do processo"]),
                "tipo": inferir_tipo(nome),
                "numero_contrato": _texto(row["Nº do contrato"]),
                "nome_contrato": nome,
                "razao_social": _texto(row["Razão social"]),
                "nome_fantasia": _texto(row["Nome fantasia"]),
                "cnpj": _texto(row["CPF/CNPJ"]),
                "objeto": _texto(row["Objeto resumido"]),
                "data_inicio": _data(row["Vigência"]),
                "data_fim": _data(row["Vencimento"]),
                "fiscal": _texto(row["Fiscal do contrato"]),
                "unidade_area": _texto(row["Unidade/Área"]),
                "situacao_planilha": _texto(row["Situação"]),
            }
        )
    return registros


def colapsar_duplicados(registros: list[dict]) -> tuple[list[dict], int]:
    """Mesmo tipo + nº duas vezes na planilha: fica a linha de vencimento mais recente."""
    melhores: dict[tuple, dict] = {}
    for r in registros:
        chave = (r["tipo"], r["numero_contrato"])
        atual = melhores.get(chave)
        if atual is None or (r["data_fim"] or "") > (atual["data_fim"] or ""):
            melhores[chave] = r
    return list(melhores.values()), len(registros) - len(melhores)


# ---------------------------------------------------------------------------
# Campos que vêm da planilha e como o resumo os chama
# ---------------------------------------------------------------------------
CAMPO_ID_PROCESSO = "id_processo"
CAMPO_NUMERO_CONTRATO = "numero_contrato"
CAMPO_DATA_INICIO = "data_inicio"
CAMPO_DATA_FIM = "data_fim"
CAMPO_ARQUIVADO = "arquivado"
CAMPO_QTD_ITENS = "qtd_itens"

# (campo no banco, nome usado no relatório) - fonte única da lista de campos da planilha
CAMPOS_E_ROTULOS = (
    (CAMPO_ID_PROCESSO, "Processo"),
    ("nome_contrato", "Descrição do contrato"),
    ("razao_social", "Fornecedor"),
    ("nome_fantasia", "Nome de fantasia"),
    ("cnpj", "CNPJ"),
    ("objeto", "Objeto"),
    (CAMPO_DATA_INICIO, "Início da vigência"),
    (CAMPO_DATA_FIM, "Data de vencimento"),
    ("fiscal", "Fiscal"),
    ("unidade_area", "Área"),
    ("situacao_planilha", "Situação na planilha"),
)
CAMPOS_PLANILHA = tuple(campo for campo, _ in CAMPOS_E_ROTULOS)
ROTULOS_CAMPOS = dict(CAMPOS_E_ROTULOS)
CAMPOS_DATA = (CAMPO_DATA_INICIO, CAMPO_DATA_FIM)

DECISAO_PLANILHA = "planilha"  # vale o que a planilha diz
DECISAO_MANTER = "manter"  # vale o que está no sistema (edição sua)
DECISAO_ALCANCOU = "alcancou"  # a planilha passou a dizer o mesmo que o sistema


@dataclass
class Divergencia:
    """Campo editado no sistema que a planilha contradiz."""

    tipo: str
    numero: str
    campo: str
    valor_sistema: str
    valor_planilha: str


@dataclass
class ResumoImportacao:
    novos: int = 0
    atualizados: int = 0
    reativados: int = 0
    colapsados: int = 0
    renovados: list = field(default_factory=list)
    arquivados: list = field(default_factory=list)
    substituidos: list = field(default_factory=list)
    mantidos: list = field(default_factory=list)
    alcancados: list = field(default_factory=list)
    backup: Optional[str] = None


@dataclass
class ContextoImportacao:
    cur: sqlite3.Cursor
    resumo: ResumoImportacao
    forcar: bool = False
    usados: set = field(default_factory=set)


@dataclass
class ResultadoMescla:
    valores: dict
    mantidos: list  # [(campo, valor_sistema, valor_planilha)]
    alcancados: list  # [campo]


# ---------------------------------------------------------------------------
# Mescla em três pontos: planilha da última vez x sistema agora x planilha de hoje
# ---------------------------------------------------------------------------
def _normalizar(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _carregar_snapshot(texto: Optional[str]) -> Optional[dict]:
    if not texto:
        return None
    try:
        return json.loads(texto)
    except ValueError:
        return None


def _decidir_campo(atual: str, planilha: str, referencia: str, forcar: bool) -> str:
    """atual = sistema agora; planilha = planilha de hoje; referencia = planilha da última importação."""
    if forcar:
        return DECISAO_PLANILHA
    if atual == planilha:
        return DECISAO_ALCANCOU if referencia != planilha else DECISAO_PLANILHA
    if atual == referencia:
        return DECISAO_PLANILHA  # ninguém mexeu no sistema: só a planilha mudou
    return DECISAO_MANTER  # você editou no sistema: não sobrescrever


def _mesclar_campos(existente: dict, r: dict, base: Optional[dict], forcar: bool) -> ResultadoMescla:
    valores: dict = {}
    mantidos: list = []
    alcancados: list = []
    for campo in CAMPOS_PLANILHA:
        atual = _normalizar(existente[campo])
        planilha = _normalizar(r[campo])
        # Sem histórico (primeira importação após esta atualização): assume que a planilha
        # não mudou, então qualquer diferença é tratada como edição sua e fica protegida.
        referencia = planilha if base is None else _normalizar(base.get(campo))
        decisao = _decidir_campo(atual, planilha, referencia, forcar)
        if decisao == DECISAO_MANTER:
            valores[campo] = existente[campo]
            mantidos.append((campo, existente[campo], r[campo]))
            continue
        valores[campo] = r[campo]
        if decisao == DECISAO_ALCANCOU:
            alcancados.append(campo)
    return ResultadoMescla(valores, mantidos, alcancados)


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------
def _selecionar_melhor_candidato(candidatos: list, r: dict) -> dict:
    """Prioridade: mesmo processo > itens cadastrados > vencimento > ID mais antigo."""

    def prioridade(c: dict):
        return (
            0 if c[CAMPO_ID_PROCESSO] == r[CAMPO_ID_PROCESSO] else 1,
            0 if c[CAMPO_QTD_ITENS] > 0 else 1,
            0 if c[CAMPO_DATA_FIM] else 1,
            c["id"],
        )

    return min(candidatos, key=prioridade)


def _estado_arquivamento(existente: dict) -> tuple[int, Optional[str]]:
    """(arquivado, arquivado_por) depois de o contrato reaparecer na planilha."""
    if existente[CAMPO_ARQUIVADO] and existente["arquivado_por"] == ARQUIVADO_POR_MANUAL:
        return 1, ARQUIVADO_POR_MANUAL  # foi você que arquivou: continua arquivado
    return 0, None


def _registrar_decisoes(ctx: ContextoImportacao, r: dict, existente: dict, mescla: ResultadoMescla) -> None:
    resumo = ctx.resumo
    if mescla.valores[CAMPO_ID_PROCESSO] != existente[CAMPO_ID_PROCESSO]:
        resumo.renovados.append((r["tipo"], r[CAMPO_NUMERO_CONTRATO], existente[CAMPO_ID_PROCESSO], r[CAMPO_ID_PROCESSO]))
    for campo, valor_sistema, valor_planilha in mescla.mantidos:
        resumo.mantidos.append(
            Divergencia(r["tipo"], r[CAMPO_NUMERO_CONTRATO], campo, _normalizar(valor_sistema), _normalizar(valor_planilha))
        )
    for campo in mescla.alcancados:
        resumo.alcancados.append((r["tipo"], r[CAMPO_NUMERO_CONTRATO], campo, _normalizar(r[campo])))


def _atualizar_contrato_existente(ctx: ContextoImportacao, r: dict, existente: dict) -> None:
    ctx.usados.add(existente["id"])
    base = _carregar_snapshot(existente["snapshot_planilha"])
    mescla = _mesclar_campos(existente, r, base, ctx.forcar)
    _registrar_decisoes(ctx, r, existente, mescla)

    arquivado, arquivado_por = _estado_arquivamento(existente)
    if existente[CAMPO_ARQUIVADO] and not arquivado:
        ctx.resumo.reativados += 1

    ctx.cur.execute(
        """
        UPDATE contratos
        SET id_processo = :id_processo, nome_contrato = :nome_contrato,
            razao_social = :razao_social, nome_fantasia = :nome_fantasia, cnpj = :cnpj,
            objeto = :objeto, data_inicio = :data_inicio, data_fim = :data_fim,
            fiscal = :fiscal, unidade_area = :unidade_area,
            situacao_planilha = :situacao_planilha, origem = :origem,
            arquivado = :arquivado, arquivado_por = :arquivado_por,
            snapshot_planilha = :snapshot
        WHERE id = :id
        """,
        {
            **mescla.valores,
            "origem": ORIGEM_PLANILHA,
            CAMPO_ARQUIVADO: arquivado,
            "arquivado_por": arquivado_por,
            "snapshot": _snapshot_json(r),
            "id": existente["id"],
        },
    )
    ctx.resumo.atualizados += 1


def _snapshot_json(r: dict) -> str:
    return json.dumps({campo: r[campo] for campo in CAMPOS_PLANILHA}, ensure_ascii=False)


def _inserir_novo_contrato(ctx: ContextoImportacao, r: dict) -> None:
    ctx.cur.execute(
        """
        INSERT INTO contratos
            (id_processo, tipo, numero_contrato, nome_contrato, razao_social, nome_fantasia,
             cnpj, objeto, data_inicio, data_fim, fiscal, unidade_area, situacao_planilha,
             observacoes, arquivado, origem, snapshot_planilha)
        VALUES (:id_processo, :tipo, :numero_contrato, :nome_contrato, :razao_social,
                :nome_fantasia, :cnpj, :objeto, :data_inicio, :data_fim, :fiscal,
                :unidade_area, :situacao_planilha, '', 0, :origem, :snapshot)
        """,
        {**r, "origem": ORIGEM_PLANILHA, "snapshot": _snapshot_json(r)},
    )
    ctx.usados.add(ctx.cur.lastrowid)
    ctx.resumo.novos += 1


def _arquivar_ausentes(ctx: ContextoImportacao, chaves_planilha: set) -> None:
    ctx.cur.execute(
        """
        SELECT c.id, c.tipo, c.numero_contrato, c.razao_social,
               (SELECT COUNT(*) FROM itens_contrato i WHERE i.contrato_id = c.id)
        FROM contratos c
        WHERE c.arquivado = 0 AND c.origem = ?
        """,
        (ORIGEM_PLANILHA,),
    )
    for cid, tipo, numero, razao, qtd_itens in ctx.cur.fetchall():
        if cid in ctx.usados:
            continue
        ctx.cur.execute(
            "UPDATE contratos SET arquivado = 1, arquivado_por = ? WHERE id = ?",
            (ARQUIVADO_POR_IMPORTACAO, cid),
        )
        destino = ctx.resumo.substituidos if (tipo, (numero or "").strip()) in chaves_planilha else ctx.resumo.arquivados
        destino.append((tipo, numero, razao, qtd_itens))


def _buscar_existentes(cur: sqlite3.Cursor) -> dict:
    cur.execute(
        """
        SELECT c.*, (SELECT COUNT(*) FROM itens_contrato i WHERE i.contrato_id = c.id) AS qtd_itens
        FROM contratos c ORDER BY c.id
        """
    )
    por_chave: dict = {}
    for linha in cur.fetchall():
        registro = dict(linha)
        por_chave.setdefault((registro["tipo"], (registro[CAMPO_NUMERO_CONTRATO] or "").strip()), []).append(registro)
    return por_chave


def importar(caminho_xlsx: str, forcar: bool = False, com_backup: bool = True) -> ResumoImportacao:
    backup = None
    if com_backup and os.path.isfile(DB_PATH):
        backup = fazer_backup(motivo=MOTIVO_ANTES_IMPORTACAO)  # antes de qualquer alteração

    inicializar_banco()
    registros, colapsados = colapsar_duplicados(ler_planilha(caminho_xlsx))

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    ctx = ContextoImportacao(conn.cursor(), ResumoImportacao(colapsados=colapsados, backup=backup), forcar)
    por_chave = _buscar_existentes(ctx.cur)

    for r in registros:
        candidatos = [c for c in por_chave.get((r["tipo"], r[CAMPO_NUMERO_CONTRATO]), []) if c["id"] not in ctx.usados]
        if candidatos:
            _atualizar_contrato_existente(ctx, r, _selecionar_melhor_candidato(candidatos, r))
        else:
            _inserir_novo_contrato(ctx, r)

    _arquivar_ausentes(ctx, {(r["tipo"], r[CAMPO_NUMERO_CONTRATO]) for r in registros})

    conn.commit()
    conn.close()
    return ctx.resumo


# ---------------------------------------------------------------------------
# Relatório no terminal
# ---------------------------------------------------------------------------
def _formatar_valor(campo: str, valor: str) -> str:
    if not valor:
        return "(vazio)"
    if campo in CAMPOS_DATA and len(valor) == 10:
        ano, mes, dia = valor.split("-")
        return f"{dia}/{mes}/{ano}"
    return valor


def _imprimir_mantidos(mantidos: list) -> None:
    if not mantidos:
        return
    print("\nEDITADOS POR VOCÊ E MANTIDOS (a planilha diz outra coisa):")
    for (tipo, numero), grupo in groupby(mantidos, key=lambda d: (d.tipo, d.numero)):
        print(f"  {tipo} {numero}")
        for d in grupo:
            print(
                f"      {ROTULOS_CAMPOS[d.campo]}: sistema {_formatar_valor(d.campo, d.valor_sistema)}"
                f"  |  planilha {_formatar_valor(d.campo, d.valor_planilha)}"
            )
    print(
        "  -> Atualize a planilha: quando ela ficar igual ao sistema, o aviso some sozinho.\n"
        "     (Para a planilha sobrescrever o sistema, rode de novo com --forcar-planilha.)"
    )


def _imprimir_alcancados(alcancados: list) -> None:
    if not alcancados:
        return
    print("\nA PLANILHA ALCANÇOU AS SUAS EDIÇÕES (aviso encerrado):")
    for tipo, numero, campo, valor in alcancados:
        print(f"  {tipo} {numero} - {ROTULOS_CAMPOS[campo]}: {_formatar_valor(campo, valor)}")


def imprimir_resumo(resumo: ResumoImportacao) -> None:
    if resumo.backup:
        print(f"Backup antes da importação: {resumo.backup}")
    print(
        f"{resumo.novos} novos | {resumo.atualizados} atualizados "
        f"({len(resumo.renovados)} com novo ID de processo = renovações) | "
        f"{resumo.reativados} reativados | {len(resumo.arquivados)} arquivados "
        f"(saíram da planilha) | {len(resumo.substituidos)} registros antigos substituídos"
    )
    if resumo.colapsados:
        print(f"  {resumo.colapsados} linha(s) repetida(s) na planilha foram unificadas (vale a de vencimento mais recente).")
    for tipo, numero, antigo, novo in resumo.renovados:
        print(f"  Renovado: {tipo} {numero}  ({antigo} -> {novo})")
    for tipo, numero, razao, qtd_itens in resumo.substituidos:
        extra = f"  [{qtd_itens} iten(s)]" if qtd_itens else ""
        print(f"  Registro antigo substituído (o contrato segue na planilha): {tipo} {numero} - {razao}{extra}")
    for tipo, numero, razao, qtd_itens in resumo.arquivados:
        extra = f"  [{qtd_itens} iten(s) preservado(s)]" if qtd_itens else ""
        print(f"  Arquivado (saiu da planilha): {tipo} {numero} - {razao}{extra}")
    _imprimir_mantidos(resumo.mantidos)
    _imprimir_alcancados(resumo.alcancados)


# ---------------------------------------------------------------------------
# Linha de comando
# ---------------------------------------------------------------------------
def _localizar_arquivo(caminho: str) -> str | None:
    candidatos = [caminho, os.path.join(PASTA_PROJETO, caminho)]
    return next((c for c in candidatos if os.path.isfile(c)), None)


def _avisar_arquivo_ausente(caminho: str) -> None:
    print(f"Arquivo não encontrado: {caminho}")
    encontrados = glob.glob("*.xlsx") + glob.glob(os.path.join(PASTA_PROJETO, "*.xlsx"))
    if not encontrados:
        print("Nenhuma planilha .xlsx na pasta atual. Copie o arquivo para cá ou informe o caminho completo.")
        return
    print("Planilhas .xlsx encontradas nesta pasta:")
    for e in sorted(set(encontrados)):
        print(f"  - {os.path.basename(e)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa a planilha de contratos/ARPs.")
    parser.add_argument("arquivo", help="caminho da planilha .xlsx")
    parser.add_argument("--forcar-planilha", action="store_true", help="a planilha sobrescreve também o que você editou")
    parser.add_argument("--sem-backup", action="store_true", help="não faz o backup automático antes de importar")
    args = parser.parse_args()

    arquivo = _localizar_arquivo(args.arquivo)
    if not arquivo:
        _avisar_arquivo_ausente(args.arquivo)
        sys.exit(1)

    imprimir_resumo(importar(arquivo, forcar=args.forcar_planilha, com_backup=not args.sem_backup))
    publicado = publicar_dashboard()
    print(f"\nDashboard web atualizado: {publicado[CHAVE_CONTRATOS]} contratos, {publicado[CHAVE_ITENS]} itens.")


if __name__ == "__main__":
    main()